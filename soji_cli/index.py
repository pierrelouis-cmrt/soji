"""SQLite persistence, FSEvents replay, dirty-subtree reconciliation and snapshots."""
from __future__ import annotations
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import threading
import time
from .engine import Scanner,Node,within
from .platform import native,events

# Consumer Options.init at 0x10050f334 and its literal pool at 0x100884000.
# Keep independent scanner scheduling separate from the original worker timers.
RECOVERED_DEFAULTS = {
    'rollUpBytes': 50_000_000, 'forcedDepth': 1, 'latency': 30.0,
    'fullCheckInterval': 604800.0, 'snapshotDays': 60, 'cooldown': 60.0,
    'busyCooldown': 180.0, 'relaxedLatency': 300.0, 'relaxedCooldown': 300.0,
    'relaxedBusyCooldown': 900.0, 'rootRewalkDelay': 600.0,
    'rootRewalkEvery': 1800.0, 'eventIDSaveEvery': 60.0, 'folderCache': True,
}
# In addition to lost history, mount/unmount changes invalidate device boundaries.
RESCAN_FLAGS = 0x1 | 0x2 | 0x4 | 0x8 | 0x20 | 0x40 | 0x80
HISTORY_DONE = 0x10

SCHEMA='''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS nodes(path TEXT PRIMARY KEY,parent TEXT,data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS nodes_parent ON nodes(parent);
CREATE TABLE IF NOT EXISTS snapshots(day TEXT NOT NULL,path TEXT NOT NULL,bytes INTEGER NOT NULL,PRIMARY KEY(day,path));
CREATE TABLE IF NOT EXISTS verdicts(path TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,judged_at REAL NOT NULL,data TEXT NOT NULL,content TEXT);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,started_at REAL,finished_at REAL,outcome TEXT,usage TEXT);
'''

class IndexStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,timeout=10)
        self.db.executescript(SCHEMA)
        # Existing terminal indexes predate the content reuse contract.
        if 'content' not in {row[1] for row in self.db.execute('PRAGMA table_info(verdicts)')}:
            self.db.execute('ALTER TABLE verdicts ADD COLUMN content TEXT')
            self.db.commit()
    def close(self):self.db.close()
    def meta(self,key,default=None):
        row=self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default
    def set_meta(self,key,value):self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,json.dumps(value)))
    def load(self):
        return {p:Node(**json.loads(data)) for p,data in self.db.execute('SELECT path,data FROM nodes')}
    def save(self,scanner,event_id,signature,*,full_scan=True,volumes=None):
        with self.db:
            self.db.execute('DELETE FROM nodes')
            self.db.executemany('INSERT INTO nodes VALUES(?,?,?)',((p,str(Path(p).parent),json.dumps(dataclasses.asdict(n))) for p,n in scanner.nodes.items()))
            self.set_meta('signature',signature);self.set_meta('eventID',event_id)
            now=time.time()
            complete=not scanner.limited and not scanner.cancel.is_set() and not scanner.error and not any(n.own_errors for n in scanner.nodes.values())
            self.set_meta('updatedAt',now);self.set_meta('complete',complete)
            self.set_meta('roots',scanner.roots)
            if full_scan and complete:self.set_meta('fullCheckedAt',now)
            if volumes is not None:self.set_meta('volumes',volumes)
            day=time.strftime('%Y-%m-%d',time.localtime(now))
            # snapshotIfDue (0x100515ff8) returns if ANY snapshot exists today.
            # A partial walk must never establish the daily growth baseline.
            if complete and not self.db.execute('SELECT 1 FROM snapshots WHERE day=? LIMIT 1',(day,)).fetchone():
                self.db.executemany('INSERT INTO snapshots VALUES(?,?,?)',((day,p,n.size) for p,n in scanner.nodes.items() if n.directory))
            cutoff=time.strftime('%Y-%m-%d',time.localtime(now-RECOVERED_DEFAULTS['snapshotDays']*86400))
            self.db.execute('DELETE FROM snapshots WHERE day<?',(cutoff,))
    def growth(self,limit=30,since=None):
        # Original IndexStore.growth (0x100534dcc) compares LIVE rows with
        # MAX(snapshot.day <= requested day), falling back to MIN(day).
        day=time.strftime('%Y-%m-%d',time.localtime(since)) if since is not None else ''
        baseline=self.db.execute('SELECT MAX(day) FROM snapshots WHERE day<=?',(day,)).fetchone()[0]
        if baseline is None:baseline=self.db.execute('SELECT MIN(day) FROM snapshots').fetchone()[0]
        if baseline is None:return []
        previous=dict(self.db.execute('SELECT path,bytes FROM snapshots WHERE day=?',(baseline,)))
        roots=set(self.meta('roots',[]));result=[]
        for path,data in self.db.execute('SELECT path,data FROM nodes'):
            n=json.loads(data)
            if not n.get('directory') or path in roots:continue
            size=n.get('size',0);delta=size-previous.get(path,0)
            if delta>0:result.append({'path':path,'bytes':size,'delta':delta})
        return sorted(result,key=lambda r:(-r['delta'],r['path']))[:max(0,limit)]
    def verdict(self,path,fingerprint,now,max_age=7*86400):
        row=self.db.execute('SELECT data,judged_at,fingerprint FROM verdicts WHERE path=?',(path,)).fetchone()
        return json.loads(row[0]) if row and row[2]==fingerprint and now-row[1]<max_age else None
    def verdict_record(self,path):
        row=self.db.execute('SELECT fingerprint,judged_at,data,content FROM verdicts WHERE path=?',(path,)).fetchone()
        if row is None:return None
        return {'fingerprint':row[0],'judgedAt':row[1],'data':json.loads(row[2]),'content':json.loads(row[3]) if row[3] is not None else None}
    def save_verdict(self,path,fingerprint,data,now,content=None):
        with self.db:self.db.execute('INSERT OR REPLACE INTO verdicts(path,fingerprint,judged_at,data,content) VALUES(?,?,?,?,?)',(path,fingerprint,now,json.dumps(data),json.dumps(content) if content is not None else None))

class IndexedScanner(Scanner):
    def __init__(self,*args,database=None,refresh=False,**kw):
        super().__init__(*args,**kw)
        self.database=str(Path(database or Path.home()/'Library/Application Support/Soji/index.sqlite').expanduser().resolve())
        self.refresh=refresh;self.index_info={};self.growth=[]
    def signature(self):
        return hashlib.sha256(json.dumps({'roots':self.roots,'home':self.home,'protected':self.protected,'measure':6,'hints':self.catalog.hints,'locations':self.catalog.locations},sort_keys=True).encode()).hexdigest()
    def recompute(self):
        # Reassign hardlink payload once over the entire persisted tree, then
        # propagate all aggregates bottom-up (no filesystem traversal needed).
        seen=set()
        for p,n in sorted(self.nodes.items()):
            if not n.directory:
                identity=(n.device,n.inode)
                duplicate=identity in seen and n.inode!=0
                if n.inode:seen.add(identity)
                # Link/unlink can change a surviving cached name's share even
                # when FSEvents dirties only the other link's parent directory.
                if getattr(n,'link_count',0)>0:
                    try:
                        current=os.lstat(p)
                        if (current.st_dev,current.st_ino)!=(n.device,n.inode) or not stat.S_ISREG(current.st_mode):
                            raise OSError('Cached regular-file identity changed')
                        n.link_count=max(1,current.st_nlink)
                        n.own_size=(getattr(current,'st_blocks',0)*512)//n.link_count
                    except OSError:
                        n.own_errors=max(1,n.own_errors);n.errors=max(1,n.errors)
                    n.size=n.own_size
                else:n.size=0 if duplicate else n.own_size
                n.apparent=0 if duplicate else n.own_apparent
        for p in sorted(self.nodes,key=lambda p:p.count('/'),reverse=True):
            n=self.nodes[p]
            n.children=[c for c in n.children if c in self.nodes]
            if n.directory and not n.reason:
                kids=[self.nodes[c] for c in n.children]
                n.size=n.own_size+sum(k.size for k in kids)
                n.apparent=n.own_apparent+sum(k.apparent for k in kids)
                n.newest=max([n.own_newest]+[k.newest for k in kids])
                n.files=sum(k.files for k in kids);n.errors=n.own_errors+sum(k.errors for k in kids)
                n.secret=any(k.secret for k in kids);n.skipped=any(k.skipped for k in kids)
        self.bytes=sum(self.nodes[p].size for p in self.roots if p in self.nodes)
        self.unreadable=sum(n.own_errors>0 for n in self.nodes.values())
        self.skipped=sum(bool(n.reason) for n in self.nodes.values())
    def run(self):
        self.started=time.monotonic();store=None
        self.visited=0;self.bytes=0;self.unreadable=0;self.skipped=0;self.limited=False;self.error='';self._inodes=set()
        self.catalog.markers_cache.clear()
        try:
            store=IndexStore(self.database);signature=self.signature()
            self.collect_context()
            can_reuse=not self.refresh and store.meta('signature')==signature and store.meta('complete',False) and time.time()-store.meta('fullCheckedAt',0)<RECOVERED_DEFAULTS['fullCheckInterval']
            saved=store.meta('eventID',0);current=native('event-id',*self.roots);event_id=current.get('eventID',0) if isinstance(current,dict) else 0
            if saved and (not event_id or event_id<saved):can_reuse=False
            volumes=current.get('volumes') if isinstance(current,dict) else None
            if volumes is not None and store.meta('volumes')!=volumes:can_reuse=False
            changes=events(self.roots,saved,0.8) if can_reuse and saved else None
            # MustScanSubDirs/UserDropped/KernelDropped/IDsWrapped/RootChanged.
            lost=changes is None or any(x.get('flags',0)&RESCAN_FLAGS for x in changes)
            if changes is not None and event_id>saved and any(x.get('replayComplete') is False for x in changes):lost=True
            if not can_reuse or lost:
                self.nodes={}
                self.index_info={'strategy':'full','reason':'refresh, stale configuration, unavailable watcher, or event history lost'}
                for root in self.roots:
                    if self.budget():self.visit(root)
            else:
                self.nodes=store.load();dirty=[]
                for event in changes:
                    if event.get('flags',0)&HISTORY_DONE:continue  # HistoryDone is a cursor marker, not a changed root
                    path=event.get('path')
                    if not path or not any(within(path,r) for r in self.roots):continue
                    target=path if path in self.nodes and self.nodes[path].directory else str(Path(path).parent)
                    while target not in self.nodes and target!='/':target=str(Path(target).parent)
                    if any(within(target,r) for r in self.roots):dirty.append(target)
                dirty=sorted(set(dirty));dirty=[p for p in dirty if not any(p!=q and within(p,q) for q in dirty)]
                for root in dirty:
                    for p in list(self.nodes):
                        if within(p,root):del self.nodes[p]
                    if os.path.lexists(root):
                        scan_root=next(r for r in self.roots if within(root,r))
                        depth=len(Path(root).parts)-len(Path(scan_root).parts)
                        device=self.nodes[scan_root].device if scan_root in self.nodes and root!=scan_root else None
                        self.visit(root,depth,device)
                self.recompute();self.index_info={'strategy':'incremental','dirtySubtrees':dirty,'reusedEntries':len(self.nodes)-self.visited}
                if not dirty:self.current='Persistent index reused; FSEvents history checked'
            if any(r not in self.nodes for r in self.roots):self.limited=True
            self._build_findings()
            from .ai import AIAnalyzer,fingerprint
            from . import ai
            reusable=getattr(ai,'reusable_verdict',None)
            now=time.time()
            cached=[reusable(store,f,now,trigger='ordinary') if callable(reusable) else store.verdict(f.path,fingerprint(f),now) for f in self.findings]
            cached=[v for v in cached if v is not None]
            if cached:AIAnalyzer(Path(self.database).parent).apply(self,cached)
            self.index_info['cachedVerdicts']=len(cached)
            checkpoints=[x['checkpoint'] for x in (changes or []) if x.get('checkpoint')]
            # For a full walk retain the pre-walk cursor so mid-walk changes replay.
            checkpoint=max(checkpoints+[saved]) if can_reuse and not lost else event_id
            store.save(self,checkpoint,signature,full_scan=not can_reuse or lost,volumes=volumes);self.growth=store.growth()
        except Exception as e:self.error=type(e).__name__+': '+str(e)
        finally:
            if store:store.close()
            self.done=True;self.finished=time.monotonic()
    def report(self,mode):
        result=super().report(mode);result.update(index=self.index_info,growth=self.growth,database=self.database);return result
    def watch(self,interval=5,on_update=None):
        while not self.cancel.is_set():
            self.done=False;self.now=time.time();self.run()
            if on_update:on_update(self.report('balanced'))
            if self.cancel.wait(interval):break
            self.catalog.markers_cache.clear()
