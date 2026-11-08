"""Official cleanup commands: exact allowlist plus live scope checks."""
from pathlib import Path
import os
import shutil
from importlib.resources import files
import json
from .util import command

def may_remove_permanently(finding):
    """Cleanup-command gate (not a general delete authorization)."""
    def value(name, default=None):
        return finding.get(name, default) if isinstance(finding, dict) else getattr(finding, name, default)
    return (value('tier') == 'regenerable' and value('recommendation') == 'remove'
            and value('comes_back') in ('rebuilds', 'downloads') and not value('holds', [])
            and not value('hold'))


class CommandPolicy:
    def __init__(self):self.hints={h['id']:h for h in json.loads(files('soji_cli').joinpath('data/hints.json').read_text())}
    def bound(self,action,path,home):
        hint=self.hints.get(action.get('hint'))
        if not hint or action.get('argv')!=hint.get('cleanCommand'):raise ValueError('Command differs from allowlist')
        if os.path.realpath(home)!=str(Path.home().resolve()):raise ValueError('Official commands cannot target a synthetic/alternate home')
        from .engine import Catalog
        matched=Catalog(home).match(str(path))
        if not matched or matched[0]['id'] != hint['id']:
            raise ValueError('Command hint does not match target path')
        argv=list(action['argv']);executable=shutil.which(argv[0])
        if not executable:raise ValueError('Official cleanup tool not installed')
        actual=None;tool=argv[0]
        probes={'npm':['npm','config','get','cache'],'pip':['pip','cache','dir'],'uv':['uv','cache','dir'],'go':['go','env','GOMODCACHE' if '-modcache' in argv else 'GOCACHE'],'bun':['bun','pm','cache'],'dotnet':['dotnet','nuget','locals','global-packages','--list']}
        if tool in probes:
            code,out,_=command([executable,*probes[tool][1:]])
            if code==0:
                lines=[l.strip() for l in out.splitlines() if l.strip()]
                if lines:actual=lines[-1].split(': ',1)[-1]
                if tool=='npm' and actual:actual=str(Path(actual)/'_cacache')
        else:
            defaults={'pod':Path(home)/'Library/Caches/CocoaPods','pre-commit':Path(os.environ.get('PRE_COMMIT_HOME',str(Path(home)/'.cache/pre-commit'))),'mise':Path(os.environ.get('MISE_CACHE_DIR',str(Path(home)/'Library/Caches/mise'))),'tart':Path(os.environ.get('TART_HOME',str(Path(home)/'.tart')))/'cache'}
            actual=str(defaults.get(tool,''))
            if tool=='pod' and os.environ.get('CP_HOME_DIR'):raise ValueError('Custom CocoaPods scope cannot be confirmed')
        if not actual or os.path.realpath(actual)!=os.path.realpath(path):raise ValueError('Tool cache scope differs or cannot be verified')
        return [executable,*argv[1:]]
    def execute(self,action,path,home):
        argv=self.bound(action,path,home)
        code,out,err=command(argv,timeout=120)
        if code:raise OSError(err or out)
        return {'argv':argv,'output':out[:4000]}
