"""Stable filesystem identities and content digests shared by every layer."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import stat


def file_identity(path):
    p=Path(path);s=os.lstat(p);parent=os.stat(p.parent,follow_symlinks=False)
    return {'device':s.st_dev,'inode':s.st_ino,'type':stat.S_IFMT(s.st_mode),'parentDevice':parent.st_dev,'parentInode':parent.st_ino,'mtimeNs':s.st_mtime_ns,'ctimeNs':s.st_ctime_ns}


def same_trash_identity(current,expected):
    # macOS Trash xattrs may change ctime without changing the object.
    return bool(expected) and {k:v for k,v in current.items() if k!='ctimeNs'}=={k:v for k,v in expected.items() if k!='ctimeNs'}


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
