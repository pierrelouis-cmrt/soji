"""Bounded local inspection and stable value conversion."""
from __future__ import annotations
from contextlib import contextmanager
import datetime as dt
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import subprocess
from urllib.parse import quote


def inside(path,root):
    a=os.path.abspath(path);r=os.path.abspath(root)
    if a.startswith('//') or r.startswith('//'):  # POSIX leading-// edge: exact commonpath rule
        return os.path.commonpath([a,r])==r
    return a==r or r=='/' or a.startswith(r+'/')


class SubtreeIndex:
    """Best-scoring entry at or below a path, in O(log n) per query.

    `entries` are (normalized absolute path, score, payload); among entries
    for the same path the highest score is kept. `subtree(root)` returns the
    payload whose path is `root` or inside it with the highest score, which is
    what a linear `max(... if inside(path, root))` returns when scores encode
    the linear scan's tie-break order.
    """
    def __init__(self,entries):
        best={}
        for path,score,payload in entries:
            cur=best.get(path)
            if cur is None or score>cur[0]:best[path]=(score,payload)
        self.best=best;self.keys=sorted(best);vals=[best[k] for k in self.keys]
        table=[vals]
        span=1
        while span*2<=len(vals):
            prev=table[-1];table.append([max(prev[i],prev[i+span],key=_score) for i in range(len(vals)-span*2+1)]);span*=2
        self.table=table
    def _range(self,lo,hi):
        if lo>=hi:return None
        level=(hi-lo).bit_length()-1;row=self.table[level]
        return max(row[lo],row[hi-(1<<level)],key=_score)
    def subtree(self,root):
        """(score, payload) of the best entry inside `root`, or None."""
        import bisect
        if root=='/':return self._range(0,len(self.keys))
        exact=self.best.get(root)
        q=root+'/';lo=bisect.bisect_left(self.keys,q);hi=bisect.bisect_left(self.keys,root+'0',lo)
        found=self._range(lo,hi)
        if exact is None:return found
        return exact if found is None else max(exact,found,key=_score)
    def ancestors(self,path):
        """(score, payload) of the best entry at `path` or any ancestor."""
        found=None
        while True:
            hit=self.best.get(path)
            if hit is not None and (found is None or hit[0]>found[0]):found=hit
            if path=='/' or not path:return found
            parent=os.path.dirname(path)
            if parent==path:return found
            path=parent


def _score(item):return item[0]


def read_json(path,limit=8_000_000):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:return None
    try:return json.loads(p.read_text(errors='replace'))
    except (OSError,ValueError):return None


def read_plist(path):
    try:
        p=Path(path)
        if p.is_symlink() or p.stat().st_size>8_000_000:return {}
        with p.open('rb') as f:return plistlib.load(f)
    except (OSError,ValueError,plistlib.InvalidFileException):return {}


def timestamp(value):
    if isinstance(value,(int,float)):
        # Epoch milliseconds in some editor and T3 records.
        return float(value)/1000 if value>100_000_000_000 else float(value)
    if isinstance(value,str):
        try:return float(value)
        except ValueError:pass
        try:return dt.datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
        except ValueError:pass
    return None


@contextmanager
def ro_sqlite(path):
    con=sqlite3.connect('file:'+quote(str(Path(path).resolve()))+'?mode=ro',uri=True,timeout=2)
    try:
        con.execute('PRAGMA query_only=ON')
        yield con
    finally:con.close()


def command(argv,timeout=8,env=None):
    try:
        r=subprocess.run([str(x) for x in argv],capture_output=True,text=True,timeout=timeout,env=env)
        return r.returncode,r.stdout[:16_000_000],r.stderr[:4000]
    except (OSError,subprocess.TimeoutExpired) as e:return -1,'',str(e)


def json_command(argv,timeout=8):
    code,out,_=command(argv,timeout)
    try:return json.loads(out) if code==0 else None
    except ValueError:return None


def atomic_json(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    import tempfile
    fd,name=tempfile.mkstemp(prefix='.'+p.name+'-',dir=p.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(name,p)
    finally:
        if os.path.exists(name):os.unlink(name)
