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
    return os.path.commonpath([os.path.abspath(path),os.path.abspath(root)])==os.path.abspath(root)


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
