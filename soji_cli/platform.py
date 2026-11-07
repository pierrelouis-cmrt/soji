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
