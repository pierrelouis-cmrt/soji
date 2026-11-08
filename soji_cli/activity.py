"""Activity sources visible in the consumer build; normalized to project/time pairs.
No transcript text, credentials, or model output is returned by these adapters.
"""
from __future__ import annotations
import dataclasses
import json
import os
import math
import re
import datetime as dt
from pathlib import Path
import sqlite3
import time
from .util import read_json, ro_sqlite, timestamp, inside, SubtreeIndex
try:  # Python 3.14+ standard library; older Pythons rely on the Codex state DB.
    from compression import zstd as _zstd
except ImportError:
    _zstd = None

ZSTD_SUFFIX = '.jsonl.zst'


def compressed_head(fileobj, limit):
    """First `limit` decompressed bytes of a zstd stream, or None without zstd.
    Output is capped, so a hostile file cannot expand past the head budget."""
    if _zstd is None:
        return None
    decoder = _zstd.ZstdDecompressor(); out = b''
    while len(out) < limit and not decoder.eof:
        chunk = fileobj.read(65536)
        if not chunk:
            break
        out += decoder.decompress(chunk, max_length=limit - len(out))
        while len(out) < limit and not decoder.needs_input and not decoder.eof:
            more = decoder.decompress(b'', max_length=limit - len(out))
            if not more:
                break
            out += more
    return out[:limit]

@dataclasses.dataclass
class Activity:
    path: str
    at: float
    source: str
    active: bool=False

class ActivityIndex:
    def __init__(self,home,now=None,max_records=100000):
        self.home=Path(home);self.now=time.time() if now is None else now;self.max_records=max_records
        self.records=[];self.errors=[];self.sources={};self.visited=0

    def add(self,path,at,source,active=False):
        stamp=timestamp(at)
        if not isinstance(path,str) or not path.startswith('/') or stamp is None or not math.isfinite(stamp):return
        # Future timestamps are kept as recent, never used to age something out.
        self.records.append(Activity(os.path.realpath(path),stamp,source,active))

    def jsonl_metadata(self,path,source,head_bytes=65536):
        """Read only the first cwd string and filesystem mtime, never transcript time.

        Activity readers use 64 KiB for Claude, 16 KiB for Codex. A small JSON
        string extractor also works when the first transcript line exceeds the
        byte budget. No message body is decoded or retained. Codex compresses
        older rollouts to `.jsonl.zst` and keeps their mtime; the budget then
        applies to decompressed bytes. Returns False if the file was unreadable.
        """
        try:
            p=Path(path)
            if p.is_symlink() or not p.is_file():return True
            with p.open('rb') as f:
                if p.name.endswith(ZSTD_SUFFIX):
                    raw=compressed_head(f,head_bytes)
                    if raw is None:return False
                else:raw=f.read(head_bytes)
            head=raw.decode('utf-8',errors='replace')
            match=re.search(r'"cwd"\s*:\s*("(?:[^"\\]|\\.)*")',head)
            if match:
                cwd=json.loads(match.group(1))
                self.add(cwd,p.stat().st_mtime,source)
            return True
        except Exception as e:  # OSError, ValueError, zstd.ZstdError
            self.errors.append(source+': '+type(e).__name__);return True

    def walk(self,root,suffix):
        if not Path(root).exists():return
        for folder,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if not Path(folder,d).is_symlink() and d not in ('node_modules','.git','memory')]
            for name in files:
                if self.visited>=self.max_records:
                    self.errors.append('Activity record budget reached');return
                if name.endswith(suffix if isinstance(suffix,str) else tuple(suffix)):
                    self.visited+=1;yield Path(folder,name)

    def claude(self):
        # projectFolders includes .claude and sibling .claude-* profiles.
        roots=[p/'projects' for p in self.home.glob('.claude*')
               if p.name=='.claude' or p.name.startswith('.claude-')]
        self.sources['claude']=any(root.is_dir() for root in roots)
        for root in roots:
            for path in self.walk(root,'.jsonl') or []:self.jsonl_metadata(path,'Claude Code')

    def codex(self):
        base=Path(os.environ.get('CODEX_HOME') or self.home/'.codex')
        root=base/'sessions';self.sources['codex']=root.exists()
        # The activity source visits exactly today and the previous 29 local
        # calendar dates. This is separate from SessionCatalog's recursive scan.
        today=dt.datetime.fromtimestamp(self.now).date()
        unreadable=[]
        for offset in range(30):
            day=root/(today-dt.timedelta(days=offset)).strftime('%Y/%m/%d')
            for path in self.walk(day,('.jsonl',ZSTD_SUFFIX)) or []:
                if not self.jsonl_metadata(path,'Codex',16384):unreadable.append(path)
        # Compatibility extension for newer Codex installations (not observed
        # in the recovered activity reader). Its rollout_path keeps the
        # pre-compression `.jsonl` name.
        listed=set()
        for db in base.glob('state_*.sqlite'):
            try:
                with ro_sqlite(db) as c:
                    names={r[1] for r in c.execute('PRAGMA table_info(threads)')}
                    if {'cwd','updated_at'}<=names:
                        query='SELECT cwd,updated_at'+(',rollout_path' if 'rollout_path' in names else ",''")+' FROM threads LIMIT ?'
                        for cwd,at,rollout in c.execute(query,(self.max_records,)):
                            self.add(cwd,at,'Codex DB')
                            if isinstance(rollout,str) and rollout:listed.add(os.path.realpath(rollout))
            except sqlite3.Error:self.errors.append('Codex DB schema unavailable')
        # Without zstd support, a compressed rollout counts only if the DB lists
        # it; otherwise project clocks could look older than they are.
        missing=[p for p in unreadable if os.path.realpath(str(p)[:-len('.zst')]) not in listed]
        self.sources['codexCompressed']={'read':_zstd is not None,'unreadable':len(unreadable),'uncovered':len(missing)}
        if missing:self.errors.append(f'Codex: {len(missing)} compressed session(s) unreadable without zstd (Python 3.14+)')

    def t3(self):
        db=self.home/'.t3/userdata/statev2.sqlite';self.sources['t3']=db.exists()
        if not db.exists():return
        try:
            with ro_sqlite(db) as c:
                query="SELECT json_extract(payload_json, '$.worktreePath'), updated_at, archived_at FROM orchestration_v2_projection_threads WHERE deleted_at IS NULL LIMIT ?"
                for path,updated,archived in c.execute(query,(self.max_records,)):
                    # A NULL archive column means live now; archived threads use
                    # the later of update/archive times (0x100557b8c..7c3c).
                    at=self.now if archived is None else max(timestamp(updated) or 0,timestamp(archived) or 0)
                    self.add(path,at,'T3 Code',active=archived is None)
        except sqlite3.Error:self.errors.append('T3 activity database unavailable or incompatible')

    def editors(self):
        from urllib.parse import unquote,urlparse
        for app in ('Code','Cursor','Windsurf','VSCodium'):
            root=self.home/'Library/Application Support'/app/'User/workspaceStorage'
            self.sources[app]=root.exists()
            for i,p in enumerate(root.glob('*/workspace.json')):
                if i>=self.max_records:
                    self.errors.append('Editor record budget reached');break
                if p.is_symlink() or p.stat().st_size>1_000_000:continue
                data=read_json(p)
                if not isinstance(data,dict):continue
                target=data.get('folder')
                if not isinstance(target,str):continue
                parsed=urlparse(target)
                if parsed.scheme!='file' or parsed.netloc not in ('','localhost'):continue
                path=unquote(parsed.path) if parsed.scheme else target
                try:
                    at=max(x.stat().st_mtime for x in [p.parent,p.parent/'state.vscdb'] if x.exists())
                    self.add(path,at,app)
                except OSError:continue

    def build(self):
        for adapter in (self.claude,self.codex,self.t3,self.editors):
            try:adapter()
            except (OSError,ValueError,sqlite3.Error) as e:self.errors.append(adapter.__name__+': '+str(e))
        return self

    def _index(self):
        # Rebuilt when records change; same answer as a linear max over
        # records (newest time, first-added on ties).
        key=(id(self.records),len(self.records))
        if getattr(self,'_index_key',None)!=key:
            entries=[]
            for i,r in enumerate(self.records):
                p=os.path.abspath(r.path)
                if p.startswith('//'):entries=None;break
                entries.append((p,(r.at,-i),r))
            self._index_value=SubtreeIndex(entries) if entries is not None else None
            self._index_key=key
        return self._index_value

    def last(self,path,include_ancestors=False):
        path=os.path.realpath(path)
        index=self._index()
        if index is None or path.startswith('//'):
            matches=[r for r in self.records if inside(r.path,path) or (include_ancestors and inside(path,r.path))]
            return max(matches,key=lambda r:r.at) if matches else None
        hits=[h for h in (index.subtree(path),index.ancestors(path) if include_ancestors else None) if h is not None]
        return max(hits,key=lambda h:h[0])[1] if hits else None

    def report(self,path=None):
        records=self.records if path is None else [r for r in self.records if inside(r.path,path) or inside(path,r.path)]
        return {'sources':self.sources,'errors':list(dict.fromkeys(self.errors)),'records':[dataclasses.asdict(r) for r in records]}
