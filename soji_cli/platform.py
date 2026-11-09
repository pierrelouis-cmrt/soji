"""macOS integration kept behind small, testable JSON boundaries."""
from importlib.resources import files, as_file
import json
from .util import command

def native(operation,*args,timeout=10):
    resource=files('soji_cli').joinpath('native-bin','soji-native')
    if not resource.is_file():return {'error':'Native helper not built; run build_release.py on macOS'}
    with as_file(resource) as path:
        import os
        os.chmod(path,0o700)
        code,out,err=command([path,operation,*map(str,args)],timeout)
    if code:return {'error':err or out or 'Native helper failed'}
    try:return json.loads(out)
    except ValueError:return {'error':'Invalid native helper response'}

def events(roots,since,seconds=1):
    resource=files('soji_cli').joinpath('native-bin','soji-native')
    if not resource.is_file():return None
    with as_file(resource) as path:
        import os
        os.chmod(path,0o700)
        code,out,err=command([path,'events',str(since),str(seconds),*roots],seconds+8)
    if code:return None
    try:return [json.loads(line) for line in out.splitlines() if line.strip()]
    except ValueError:return None

class ExclusiveRenameUnavailable(OSError):
    """No atomic no-replace rename exists here; callers must not fall back."""

RENAME_EXCL=0x00000004  # <sys/stdio.h>: fail with EEXIST rather than replace

def rename_exclusive(src_dir_fd,src_name,dst_dir_fd,dst_name):
    """Atomically rename, refusing to replace anything at the destination.

    Uses macOS renameatx_np(..., RENAME_EXCL), which works for files and
    directories alike and fails with EEXIST if *any* object (including an
    empty directory) exists at the destination. There is deliberately no
    check-then-rename fallback: where the primitive is missing, or the file
    system rejects the flag (ENOTSUP/EINVAL), ExclusiveRenameUnavailable is
    raised and the source is left untouched.
    """
    import ctypes,errno,os
    try:
        libc=ctypes.CDLL(None,use_errno=True);call=libc.renameatx_np
    except (OSError,AttributeError) as e:raise ExclusiveRenameUnavailable(errno.ENOTSUP,'Exclusive rename (renameatx_np) unavailable') from e
    call.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];call.restype=ctypes.c_int
    if call(src_dir_fd,os.fsencode(src_name),dst_dir_fd,os.fsencode(dst_name),RENAME_EXCL)==0:return
    code=ctypes.get_errno()
    if code in (errno.ENOTSUP,errno.EINVAL,getattr(errno,'EOPNOTSUPP',errno.ENOTSUP)):
        raise ExclusiveRenameUnavailable(code,'Exclusive rename not supported by this file system: '+os.strerror(code))
    raise OSError(code,os.strerror(code),dst_name)
