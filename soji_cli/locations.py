"""Configured cache roots without sourcing or executing shell initialization files."""
from pathlib import Path
import os
import re
from .util import read_plist,read_json

VARIABLES={'NPM_CONFIG_CACHE':'npm-cache','npm_config_cache':'npm-cache','PIP_CACHE_DIR':'pip-cache','UV_CACHE_DIR':'uv-cache','GOCACHE':'go-build-cache','GOMODCACHE':'go-mod-cache','HOMEBREW_CACHE':'homebrew-cache','PRE_COMMIT_HOME':'pre-commit-cache','YARN_CACHE_FOLDER':'yarn-cache','BUN_INSTALL_CACHE_DIR':'bun-cache'}

def cache_locations(home,environment=None):
    home=Path(home);values={'HOME':str(home)}
    # A synthetic home must not inherit the operator's real cache locations.
    inherited=(dict(os.environ) if home.resolve()==Path.home().resolve() else {}) if environment is None else environment
    for p in [home/n for n in ('.profile','.bash_profile','.bashrc','.zshenv','.zprofile','.zshrc')]:
        try:
            if p.is_symlink() or p.stat().st_size>500000:continue
            for line in p.read_text(errors='replace').splitlines():
                m=re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$',line)
                if not m:continue
                key,value=m.groups()
                if key not in VARIABLES and key not in ('XDG_CACHE_HOME','GOPATH','CARGO_HOME','BUN_INSTALL','GRADLE_USER_HOME'):continue
                if any(c in value for c in ('`','$(',';','|','>','<')):continue
                value=value.split(' #',1)[0].strip().strip('"\'')
                value=re.sub(r'\$\{?(\w+)\}?',lambda m:values.get(m.group(1),'$'+m.group(1)),value)
                if '$' not in value:values[key]=value.replace('~',str(home),1)
        except OSError:pass
    values.update({k:v for k,v in inherited.items() if k in VARIABLES or k in ('XDG_CACHE_HOME','GOPATH','CARGO_HOME','BUN_INSTALL','GRADLE_USER_HOME')})
    result=[]
    for variable,hint in VARIABLES.items():
        path=values.get(variable)
        if path and os.path.isabs(path):
            if hint=='npm-cache':path=str(Path(path)/'_cacache')
            result.append((hint,os.path.normpath(path),variable))
    # ToolCaches.locate: BUN_INSTALL_CACHE_DIR is direct;
    # BUN_INSTALL identifies the installation whose cache is install/cache.
    bun=values.get('BUN_INSTALL')
    if bun and os.path.isabs(bun):result.append(('bun-cache',str(Path(bun)/'install/cache'),'BUN_INSTALL'))
    for n,hint in [('.npmrc','npm-cache'),('.yarnrc','yarn-cache')]:
        p=home/n
        try:
            if p.is_symlink() or p.stat().st_size>100000:continue
            for line in p.read_text().splitlines():
                m=re.match(r'\s*(?:cache|cache-folder)\s*[= ]\s*["\']?([^"\'\n]+)',line)
                if m:
                    path=m.group(1).replace('${HOME}',str(home)).replace('~',str(home),1)
                    if path.startswith('/') and not any(c in path for c in ('$','`')):result.append((hint,str(Path(path)/'_cacache') if hint=='npm-cache' else path,n))
        except OSError:pass
    xcode=read_plist(home/'Library/Preferences/com.apple.dt.Xcode.plist')
    for k,hint in [('IDECustomDerivedDataLocation','xcode-derived-data'),('IDECustomDistributionArchivesLocation','xcode-archives')]:
        path=xcode.get(k)
        if isinstance(path,str) and path.startswith('/'):result.append((hint,path.rstrip('/')+'/*',k))
    return result
