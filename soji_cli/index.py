"""SQLite persistence, FSEvents replay, dirty-subtree reconciliation and snapshots."""
from __future__ import annotations
import dataclasses
import hashlib
import json
import marshal
import os
from pathlib import Path
import sqlite3
import stat
import threading
import time
import zlib
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
# Port choice: per incremental run, re-stat at most this many cached single-link
# files of at least this size to catch new hardlinks made outside the roots.
LINK_PROBE_MIN_BYTES = 1 << 20
LINK_PROBE_LIMIT = 20_000

SCHEMA='''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS nodes(path TEXT PRIMARY KEY,parent TEXT,data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS nodes_parent ON nodes(parent);
CREATE TABLE IF NOT EXISTS snapshots(day TEXT NOT NULL,path TEXT NOT NULL,bytes INTEGER NOT NULL,PRIMARY KEY(day,path));
CREATE TABLE IF NOT EXISTS verdicts(path TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,judged_at REAL NOT NULL,data TEXT NOT NULL,content TEXT);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,started_at REAL,finished_at REAL,outcome TEXT,usage TEXT);
CREATE TABLE IF NOT EXISTS links(path TEXT PRIMARY KEY,device INTEGER NOT NULL,inode INTEGER NOT NULL,nlink INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS links_identity ON links(device,inode);
CREATE TABLE IF NOT EXISTS node_snapshot(id INTEGER PRIMARY KEY CHECK(id=1),format INTEGER NOT NULL,data BLOB NOT NULL);
'''
# Node rows are persisted as one zlib-compressed marshal snapshot of field
# tuples (marshal builds plain values only and never runs code). One JSON row
# per node cost ~5 s to write and ~3 s to read at 560k nodes; this is ~1 s
# each way. Legacy per-row `nodes` tables are still read, then cleared.
SNAPSHOT_FORMAT = 2
UNCACHED = -2  # match decided by a marker condition: recomputed every run

NODE_FIELDS=tuple(f.name for f in dataclasses.fields(Node))


UNREADABLE_PROBES = 16


def unreadable_sample(rows,limit=UNREADABLE_PROBES):
    """Evenly spaced rows of a path-sorted list (deterministic)."""
    rows=sorted(rows,key=lambda r:r[0])
    if len(rows)<=limit:return rows
    step=len(rows)/limit
    return [rows[int(i*step)] for i in range(limit)]


def readable_now(path,node):
    """Would visit() now measure this unreadable row?"""
    try:
        if node.directory and node.reason!='Unreadable entry':
            fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|getattr(os,'O_NOFOLLOW',0))
            try:
                with os.scandir(fd) as it:next(it,None)
            finally:os.close(fd)
        else:os.lstat(path)
        return True
    except OSError:return False


def outermost(paths):
    """Sorted unique paths with any path inside another one dropped."""
    kept=SubtreeSet(())
    for p in sorted(set(paths),key=lambda p:(p.count('/'),p)):
        if not kept(p):kept.add(p)
    return sorted(kept.roots)


class SubtreeSet:
    """`within(path, root)` for any root, in O(depth) with a per-folder memo."""
    def __init__(self,roots):
        self.roots=set(roots);self._memo={}
    def add(self,root):
        self.roots.add(root);self._memo.clear()
    def __call__(self,path):
        memo=self._memo;chain=[]
        while True:
            if path in self.roots:result=True;break
            known=memo.get(path)
            if known is not None:result=known;break
            parent=os.path.dirname(path)
            if parent==path:result=False;break
            chain.append(path);path=parent
        for p in chain:memo[p]=result
        return result


def snapshot_blob(nodes,catalog=None):
    # Node holds only scalars and a list of str, all marshal-native. Path-only
    # catalog matches (Catalog.pure) ride along, keyed by the catalog contents.
    rows=[tuple(getattr(n,f) for f in NODE_FIELDS) for n in nodes.values()]
    pure=getattr(catalog,'pure',None) or {}
    codes=[pure.get(p,UNCACHED) for p in nodes] if pure else []
    return zlib.compress(marshal.dumps((NODE_FIELDS,rows,getattr(catalog,'key',''),codes)),1)


def read_snapshot(db):
    """(nodes in walk order, (catalog key, {path: match code})): the snapshot,
    else legacy JSON rows (no match cache)."""
    row=db.execute('SELECT format,data FROM node_snapshot WHERE id=1').fetchone() if db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='node_snapshot'").fetchone() else None
    if row and row[0]!=SNAPSHOT_FORMAT:raise ValueError('Index snapshot format is not supported; a full walk rebuilds it')
    if row:
        fields,rows,key,codes=marshal.loads(zlib.decompress(row[1]))
        if tuple(fields)==NODE_FIELDS:
            nodes={r[0]:Node(*r) for r in rows}
        else:
            index={f:i for i,f in enumerate(fields)}
            nodes={r[index['path']]:Node(**{f:r[index[f]] for f in NODE_FIELDS if f in index}) for r in rows}
        seed={p:c for p,c in zip(nodes,codes) if c!=UNCACHED} if len(codes)==len(nodes) else {}
        return nodes,(key,seed)
    return {p:Node(**json.loads(data)) for p,data in db.execute('SELECT path,data FROM nodes')},('',{})


def read_nodes(db):
    return read_snapshot(db)[0]


def _link_rows(items):
    # Regular files with nlink > 1: the only cached names whose allocated
    # share can change when a different name of the same inode is touched.
    for p,n in items:
        if not n.directory and not n.reason and n.inode and getattr(n,'link_count',0)>1:
            yield (p,n.device,n.inode,n.link_count)

class IndexStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,timeout=10)
        had_links=self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='links'").fetchone() is not None
        self.db.executescript(SCHEMA)
        # The index is a rebuildable cache; WAL + NORMAL stays consistent on a
        # crash and skips an fsync per commit.
        self.db.execute('PRAGMA synchronous=NORMAL')
        # Existing indexes predate the hardlink identity table; backfill it
        # from persisted node rows so incremental reconciliation stays exact.
        if not had_links:
            with self.db:
                rows=list(read_nodes(self.db).items())
                self.db.executemany('INSERT OR REPLACE INTO links VALUES(?,?,?,?)',list(_link_rows(rows)))
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
        nodes,self.match_seed=read_snapshot(self.db)
        return nodes
    def match_seed_only(self):
        """(catalog key, {path: code}) without building nodes."""
        row=self.db.execute('SELECT format,data FROM node_snapshot WHERE id=1').fetchone()
        if not row or row[0]!=SNAPSHOT_FORMAT:return '',{}
        fields,rows,key,codes=marshal.loads(zlib.decompress(row[1]))
        at=list(fields).index('path')
        return key,({r[at]:c for r,c in zip(rows,codes) if c!=UNCACHED} if len(codes)==len(rows) else {})
    def loadable(self):
        """A current-format snapshot, or a legacy per-row table, is present."""
        row=self.db.execute('SELECT format FROM node_snapshot WHERE id=1').fetchone()
        if row is not None:return row[0]==SNAPSHOT_FORMAT
        return self.db.execute('SELECT 1 FROM nodes LIMIT 1').fetchone() is not None
    def links_for(self,identities):
        result={}
        for device,inode in identities:
            result[(device,inode)]=[r[0] for r in self.db.execute('SELECT path FROM links WHERE device=? AND inode=?',(device,inode))]
        return result
    def external_links(self):
        """Identities with fewer cached names than their stored link count:
        some links live outside the indexed roots and fire no in-root event."""
        rows=self.db.execute('SELECT device,inode,MAX(nlink),GROUP_CONCAT(path,char(0)) FROM links GROUP BY device,inode HAVING COUNT(*)<MAX(nlink)')
        return {(d,i):(n,paths.split('\0')) for d,i,n,paths in rows}
    def save(self,scanner,event_id,signature,*,full_scan=True,volumes=None):
        with self.db:
            self.db.execute('DELETE FROM nodes')
            self.db.execute('INSERT OR REPLACE INTO node_snapshot VALUES(1,?,?)',(SNAPSHOT_FORMAT,snapshot_blob(scanner.nodes,getattr(scanner,'catalog',None))))
            self.db.execute('DELETE FROM links')
            self.db.executemany('INSERT INTO links VALUES(?,?,?,?)',list(_link_rows(scanner.nodes.items())))
            self.set_meta('signature',signature);self.set_meta('eventID',event_id)
            now=time.time()
            finished=not scanner.limited and not scanner.cancel.is_set() and not scanner.error
            complete=finished and not any(n.own_errors for n in scanner.nodes.values())
            self.set_meta('updatedAt',now);self.set_meta('complete',complete)
            # Port choice: a walk that finished but met unreadable entries (TCC
            # denials such as ~/Library/Caches/com.apple.Safari) is reusable.
            # Incremental runs probe a sample of unreadable rows and re-walk
            # them all if any became readable; `complete` still gates snapshots.
            self.set_meta('reusable',finished)
            self.set_meta('roots',scanner.roots)
            if full_scan and complete:self.set_meta('fullCheckedAt',now)
            if full_scan and finished:self.set_meta('walkedAt',now)
            if volumes is not None:self.set_meta('volumes',volumes)
            day=time.strftime('%Y-%m-%d',time.localtime(now))
            # snapshotIfDue (0x100515ff8) returns if ANY snapshot exists today.
            # A partial walk must never establish the daily growth baseline.
            if complete and not self.db.execute('SELECT 1 FROM snapshots WHERE day=? LIMIT 1',(day,)).fetchone():
                self.db.executemany('INSERT INTO snapshots VALUES(?,?,?)',((day,p,n.size) for p,n in scanner.nodes.items() if n.directory))
            cutoff=time.strftime('%Y-%m-%d',time.localtime(now-RECOVERED_DEFAULTS['snapshotDays']*86400))
            self.db.execute('DELETE FROM snapshots WHERE day<?',(cutoff,))
    def growth(self,limit=30,since=None,nodes=None):
        # Original IndexStore.growth (0x100534dcc) compares LIVE rows with
        # MAX(snapshot.day <= requested day), falling back to MIN(day).
        day=time.strftime('%Y-%m-%d',time.localtime(since)) if since is not None else ''
        baseline=self.db.execute('SELECT MAX(day) FROM snapshots WHERE day<=?',(day,)).fetchone()[0]
        if baseline is None:baseline=self.db.execute('SELECT MIN(day) FROM snapshots').fetchone()[0]
        if baseline is None:return []
        previous=dict(self.db.execute('SELECT path,bytes FROM snapshots WHERE day=?',(baseline,)))
        roots=set(self.meta('roots',[]));result=[]
        # Live rows: the scanner's own nodes when it just saved them.
        for path,n in (nodes if nodes is not None else read_nodes(self.db)).items():
            if not n.directory or path in roots:continue
            size=n.size;delta=size-previous.get(path,0)
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
    def reconcile(self,store,dirty):
        """Re-walk dirty subtrees, then refresh only cached names sharing a
        hardlink identity with a name added, removed or changed inside them.
        Aggregates are recomputed only for ancestors of changed rows."""
        inside=SubtreeSet(dirty)
        def identity(n):return (n.device,n.inode)
        def multi(n):return not n.directory and not n.reason and n.inode and getattr(n,'link_count',0)>1
        old={p:n for p,n in self.nodes.items() if inside(p)}
        for p in old:del self.nodes[p]
        walks=[]
        for root in dirty:
            if os.path.lexists(root):
                scan_root=next(r for r in self.roots if within(root,r))
                depth=len(Path(root).parts)-len(Path(scan_root).parts)
                device=self.nodes[scan_root].device if scan_root in self.nodes and root!=scan_root else None
                walks.append((root,depth,device,True))
        self.walk(walks)
        fresh={p:n for p,n in self.nodes.items() if inside(p)}
        removed_ids={identity(n) for n in old.values() if multi(n)}
        added_ids={identity(n) for n in fresh.values() if multi(n)}
        affected=removed_ids|added_ids
        # Links outside the roots: re-stat one cached name per such identity
        # and treat it as affected if its link count moved.
        external_checked=0
        for ident,(nlink,paths) in store.external_links().items():
            if ident in affected:continue
            probe=next((q for q in sorted(paths) if q in self.nodes and not inside(q)),None)
            if probe is None:continue
            external_checked+=1
            try:
                current=os.lstat(probe)
                moved=(current.st_dev,current.st_ino)!=ident or current.st_nlink!=nlink
            except OSError:moved=True
            if moved:affected.add(ident)
        # A new outside link to a file cached with nlink == 1 produces no event
        # inside the roots. Re-stat the largest such files (bounded); smaller
        # ones wait for the weekly full check, since they barely move estimates.
        grown={};link_probed=0
        candidates=[(n.own_size,p) for p,n in self.nodes.items() if not n.directory and not n.reason and n.inode
                    and getattr(n,'link_count',0)==1 and n.own_size>=LINK_PROBE_MIN_BYTES and not inside(p) and identity(n) not in affected]
        for _,p in sorted(candidates,reverse=True)[:LINK_PROBE_LIMIT]:
            n=self.nodes[p];link_probed+=1
            try:current=os.lstat(p)
            except OSError:current=None
            if current is None or (current.st_dev,current.st_ino)!=identity(n) or current.st_nlink!=1:
                affected.add(identity(n));grown.setdefault(identity(n),[]).append(p)
        cached=store.links_for(affected)
        for ident,paths in grown.items():
            cached.setdefault(ident,[]).extend(q for q in paths if q not in cached[ident])
        # A brand-new link to a file cached with nlink == 1 is not in the
        # links table; fall back to an in-memory (stat-free) identity lookup.
        new_ids={i for i in added_ids-removed_ids if not cached.get(i)}
        if new_ids:
            for p,n in self.nodes.items():
                if not n.directory and not inside(p) and identity(n) in new_ids:cached.setdefault(identity(n),[]).append(p)
        touched=set(dirty);restatted=0
        for ident in affected:
            for p in cached.get(ident,[]):
                n=self.nodes.get(p)
                if n is None or inside(p) or n.directory:continue
                before=(n.own_size,n.link_count,n.own_errors);restatted+=1
                try:
                    current=os.lstat(p)
                    if (current.st_dev,current.st_ino)!=identity(n) or not stat.S_ISREG(current.st_mode):
                        raise OSError('Cached regular-file identity changed')
                    n.link_count=max(1,current.st_nlink)
                    n.own_size=(getattr(current,'st_blocks',0)*512)//n.link_count
                except OSError:
                    n.own_errors=max(1,n.own_errors);n.errors=max(1,n.errors)
                n.size=n.own_size
                if before!=(n.own_size,n.link_count,n.own_errors):touched.add(p)
            # Logical bytes are attributed once per identity to the first name.
            names=sorted(q for q in set(cached.get(ident,[]))|{q for q,m in fresh.items() if not m.directory and identity(m)==ident} if q in self.nodes)
            for i,q in enumerate(names):
                m=self.nodes[q];value=m.own_apparent if i==0 else 0
                if m.apparent!=value:m.apparent=value;touched.add(q)
        dirs=set()
        for p in touched:
            if p in self.nodes and self.nodes[p].directory:dirs.add(p)
            for parent in Path(p).parents:
                q=str(parent)
                if q in self.nodes:dirs.add(q)
                if any(q==r for r in self.roots) or q=='/':break
        # Within dirty subtrees visit() already aggregated; re-aggregate them
        # only when a descendant's attribution changed afterwards.
        for p in sorted(dirs,key=lambda p:p.count('/'),reverse=True):
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
        return {'affectedIdentities':len(affected),'restatted':restatted,'externalChecked':external_checked,'linkProbed':link_probed,'recomputedDirectories':len(dirs)}
    def run(self):
        self.started=time.monotonic();store=None;pool=None
        self.set_progress('scan',path='Checking disk index')
        self.visited=0;self.bytes=0;self.unreadable=0;self.skipped=0;self.limited=False;self.error='';self._inodes=set()
        self.catalog.markers_cache.clear()
        try:
            store=IndexStore(self.database);signature=self.signature()
            # Process/open-file snapshot runs alongside the index work below.
            from concurrent.futures import ThreadPoolExecutor
            pool=ThreadPoolExecutor(1);context=pool.submit(self.collect_context)
            reusable=store.meta('reusable',store.meta('complete',False))
            walked=store.meta('walkedAt',store.meta('fullCheckedAt',0))
            can_reuse=not self.refresh and store.meta('signature')==signature and reusable and time.time()-walked<RECOVERED_DEFAULTS['fullCheckInterval'] and store.loadable()
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
                # Path-only catalog matches stay valid across a full walk.
                if store.loadable():
                    try:self.catalog.seed(*store.match_seed_only())
                    except (ValueError,TypeError,EOFError,zlib.error):pass
                self.index_info={'strategy':'full','reason':'refresh, stale configuration, unavailable watcher, or event history lost'}
                self.walk([(root,0,None,False) for root in self.roots])
            else:
                self.nodes=store.load();dirty=[]
                self.catalog.seed(*store.match_seed)
                for event in changes:
                    if event.get('flags',0)&HISTORY_DONE:continue  # HistoryDone is a cursor marker, not a changed root
                    path=event.get('path')
                    if not path or not any(within(path,r) for r in self.roots):continue
                    target=path if path in self.nodes and self.nodes[path].directory else str(Path(path).parent)
                    while target not in self.nodes and target!='/':target=str(Path(target).parent)
                    if any(within(target,r) for r in self.roots):dirty.append(target)
                # A permission grant fires no event, and each denied open costs
                # a privacy (TCC) check of several ms. Probe a spread sample of
                # unreadable rows; if any became readable, re-walk them all.
                # Unreadable rows always hold their findings, so a stale denial
                # is never a cleanup risk; full walks and --refresh recheck all.
                errored=[(p,n) for p,n in self.nodes.items() if n.own_errors]
                probed=unreadable_sample(errored)
                rechecked=any(readable_now(p,n) for p,n in probed)
                if rechecked:
                    for path,n in errored:
                        target=path if n.directory and os.path.lexists(path) else os.path.dirname(path)
                        if any(within(target,r) for r in self.roots):dirty.append(target)
                dirty=outermost(dirty)
                stats=self.reconcile(store,dirty)
                self.index_info={'strategy':'incremental','dirtySubtrees':dirty,'unreadableRows':len(errored),'unreadableProbed':len(probed),'unreadableRechecked':rechecked,'reusedEntries':len(self.nodes)-self.visited,**stats}
                if not dirty:self.current='Persistent index reused; FSEvents history checked'
            if any(r not in self.nodes for r in self.roots):self.limited=True
            context.result();pool.shutdown();pool=None
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
            store.save(self,checkpoint,signature,full_scan=not can_reuse or lost,volumes=volumes);self.growth=store.growth(nodes=self.nodes)
        except Exception as e:self.error=type(e).__name__+': '+str(e)
        finally:
            if pool is not None:pool.shutdown()
            if store:store.close()
            self.set_progress('done',1,1);self.done=True;self.finished=time.monotonic()
    def report(self,mode):
        result=super().report(mode);result.update(index=self.index_info,growth=self.growth,database=self.database);return result
    def watch(self,interval=5,on_update=None):
        while not self.cancel.is_set():
            self.done=False;self.now=time.time();self.run()
            if on_update:on_update(self.report('balanced'))
            if self.cancel.wait(interval):break
            self.catalog.markers_cache.clear()
