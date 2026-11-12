"""Installed-app ownership and installed-tool dependency discovery."""
from __future__ import annotations
import fnmatch
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import plistlib
from .util import read_plist,read_json,inside,command,SubtreeIndex
from .platform import native

CODESIGN='/usr/bin/codesign'
PKGUTIL='/usr/sbin/pkgutil'
TEAM_RE=re.compile(r'^[A-Z0-9]{10}$')
NO_IDENTITY={'team':None,'groups':[]}


def safe_component(value):
    return isinstance(value,str) and bool(value) and value not in ('.','..') and '/' not in value and '\x00' not in value


def code_identity(app_path):
    """Read-only signing identity {'team','groups'} from codesign.
    Unsigned, ad-hoc or unreadable apps yield no team and no groups."""
    code,_,err=command([CODESIGN,'-dv','--verbose=4',str(app_path)],timeout=10)
    if code!=0:return dict(NO_IDENTITY,groups=[])
    team=next((l.split('=',1)[1].strip() for l in err.splitlines() if l.startswith('TeamIdentifier=')),None)
    # Ad-hoc signatures print "TeamIdentifier=not set".
    if not team or not TEAM_RE.match(team):return dict(NO_IDENTITY,groups=[])
    code,out,_=command([CODESIGN,'-d','--entitlements','-','--xml',str(app_path)],timeout=10)
    groups=[]
    if code==0 and out.strip():
        try:ent=plistlib.loads(out.encode())
        except Exception:ent={}
        raw=ent.get('com.apple.security.application-groups') if isinstance(ent,dict) else None
        if isinstance(raw,list):groups=sorted({g for g in raw if safe_component(g)})
    return {'team':team,'groups':groups}


def user_receipts(home,limit=64):
    """User-domain pkg receipts as {pkgid: [absolute paths]}: ~/Library/Receipts
    plists plus read-only `pkgutil --volume HOME --files`. Bounded, best-effort."""
    h=Path(home);result={}
    for plist in sorted((h/'Library/Receipts').glob('*.plist'))[:limit]:
        info=read_plist(plist);pkg=info.get('PackageIdentifier')
        if not isinstance(pkg,str) or not pkg:continue
        prefix=str(info.get('InstallPrefixPath') or '').strip('/')
        code,out,_=command([PKGUTIL,'--volume',str(h),'--files',pkg],timeout=10)
        if code!=0:continue
        base=h/prefix if prefix else h
        result[pkg]=[str(base/l.strip()) for l in out.splitlines() if l.strip() and '..' not in Path(l.strip()).parts]
    return result


def apple_group(group):
    """group.com.apple.*, com.apple.* and TEAMID.com.apple.* are Apple-owned."""
    g=group.casefold()
    if g.startswith('group.'):g=g[6:]
    elif len(group)>11 and group[10]=='.' and TEAM_RE.match(group[:10]):g=g[11:]
    return g.startswith('com.apple.') or g=='com.apple'


class AppCatalog:
    # System-wide roots are class-level so hermetic tests can pin them.
    SYSTEM_ROOTS=(Path('/Applications'),Path('/System/Applications'))
    def __init__(self,home,processes=()):
        self.home=Path(home);self.apps=[];self.processes=processes;self.running=[];self.running_available=False;self._identities={}
    def identity(self,app):
        """Signing identity, looked up lazily: only uninstall planning and verification call this."""
        if app['path'] not in self._identities:
            apple=app['bundle'].startswith('com.apple.') or app['path'].startswith('/System/')
            self._identities[app['path']]=dict(NO_IDENTITY,groups=[]) if apple else code_identity(app['path'])
        return self._identities[app['path']]
    def group_owners(self,group):
        """Installed apps attributable to a group container: entitlement or Team ID prefix."""
        owners=[]
        for app in self.apps:
            ident=self.identity(app)
            if group in ident['groups'] or (ident['team'] and group.startswith(ident['team']+'.')):owners.append(app)
        return owners
    def build(self):
        for root in [*self.SYSTEM_ROOTS,self.home/'Applications']:
            if not root.exists():continue
            for folder,dirs,files in os.walk(root):
                if len(Path(folder).relative_to(root).parts)>3:dirs[:]=[];continue
                for name in list(dirs):
                    if not name.endswith('.app'):continue
                    dirs.remove(name);p=Path(folder,name);info=read_plist(p/'Contents/Info.plist')
                    self.apps.append({'path':str(p),'bundle':info.get('CFBundleIdentifier',''),'name':info.get('CFBundleDisplayName') or info.get('CFBundleName') or p.stem,'version':info.get('CFBundleShortVersionString','')})
        try:running=native('apps')
        except Exception:running=None
        self.running_available=isinstance(running,list) and all(isinstance(r,dict) and (isinstance(r.get('bundleID'),str) and bool(r['bundleID']) or isinstance(r.get('path'),str) and r['path'].startswith('/')) for r in running)
        if self.running_available:self.running=running
        return self
    def owner(self,path):
        parts=Path(path).parts;tokens=[]
        for marker in ['Caches','Application Support','Containers','Group Containers','Preferences']:
            if marker in parts:
                i=parts.index(marker)
                if i+1<len(parts):tokens.append(parts[i+1].removesuffix('.plist'))
        tokens += [Path(path).name.removesuffix('.plist')]
        result=[]
        keys=[(token.casefold(),re.sub(r'[^a-z0-9]','',token.casefold().removeprefix('group.'))) for token in tokens]
        for app,name,bundle in self._app_keys():
            for folded,normalized in keys:
                if folded==bundle or (bundle and folded.startswith(bundle+'.')) or (normalized and normalized==name):result.append(app);break
        return result
    def vendor_owners(self,path):
        """Installed apps whose reverse-DNS vendor names the folder directly under
        a library marker (com.mathworks.matlab -> Application Support/MathWorks).
        Broader than owner(): use it only to add holds, never to permit removal."""
        parts=Path(path).parts;tokens=set()
        for marker in ['Caches','Application Support','Containers','Group Containers','Preferences']:
            if marker in parts:
                i=parts.index(marker)
                if i+1<len(parts):
                    name=parts[i+1].removesuffix('.plist').casefold().removeprefix('group.');dotted=name.split('.')
                    # A reverse-DNS folder (com.mathworks.matlabconnector) names its vendor second.
                    tokens.add(re.sub(r'[^a-z0-9]','',dotted[1] if len(dotted)>=3 else name))
        tokens.discard('')
        result=[]
        for app,_,bundle in self._app_keys():
            segments=bundle.split('.')
            if len(segments)>=3 and re.sub(r'[^a-z0-9]','',segments[1]) in tokens:result.append(app)
        return result
    def _app_keys(self):
        # Normalized (name, bundle) per app, rebuilt if the app list changes.
        stamp=(id(self.apps),len(self.apps))
        if getattr(self,'_keys_stamp',None)!=stamp:
            self._keys=[(app,re.sub(r'[^a-z0-9]','',app['name'].casefold()),app['bundle'].casefold()) for app in self.apps]
            self._keys_stamp=stamp
        return self._keys
    def is_running(self,app):
        return any(r.get('bundleID')==app['bundle'] or r.get('path')==app['path'] for r in self.running) or any(inside(p.casefold(),app['path'].casefold()) for p in self.processes if p.startswith('/'))

class InstalledTools:
    SYSTEM_AGENT_ROOTS=(Path('/Library/LaunchAgents'),Path('/Library/LaunchDaemons'))
    def __init__(self,home):self.home=Path(home);self.targets=[];self.errors=[]
    def add(self,path,source):
        if isinstance(path,str) and path.startswith('/'):
            self.targets.append((os.path.realpath(path),source))
    def extract(self,obj,source,depth=0):
        if depth>16 or len(self.targets)>=100000:return
        if isinstance(obj,dict):
            command=obj.get('command');args=obj.get('args') or obj.get('arguments') or []
            if isinstance(command,str):
                resolved=command if command.startswith('/') else shutil.which(command)
                if resolved:self.add(resolved,source)
            if isinstance(args,list):
                for a in args:
                    if isinstance(a,str) and a.startswith('/') and os.path.exists(a):self.add(a,source)
            for value in obj.values():self.extract(value,source,depth+1)
        elif isinstance(obj,list):
            for value in obj:self.extract(value,source,depth+1)
    def config_json(self,path):
        """Bounded JSON/JSONC reader; comments inside strings remain literal."""
        try:
            if path.is_symlink() or path.stat().st_size>4_000_000:return None
            text=path.read_text()
            # Tokenize strings before comments so https:// and quoted // survive.
            text=re.sub(r'("(?:[^"\\]|\\.)*")|//[^\n]*|/\*[\s\S]*?\*/',
                        lambda m:m.group(1) or ' ',text)
            return json.loads(text)
        except FileNotFoundError:return None
        except (OSError,ValueError):
            self.errors.append('Tool config unreadable: '+path.name);return None

    def build(self):
        for folder in os.environ.get('PATH','').split(os.pathsep):
            p=Path(folder)
            if not p.is_dir():continue
            try:
                for entry in p.iterdir():
                    if entry.is_symlink() or entry.is_file() and os.access(entry,os.X_OK):self.add(str(entry.resolve()),'PATH command '+entry.name)
            except OSError:pass
        configs=['.claude/settings.json','.claude/settings.local.json','.cursor/mcp.json','.gemini/settings.json','.gemini/antigravity/mcp_config.json','.config/opencode/opencode.json','.config/opencode/opencode.jsonc','.config/opencode/config.json','.qwen/settings.json','.kimi/config.json','.grok/settings.json','.grok/user-settings.json','.copilot/mcp-config.json','.codeium/windsurf/mcp_config.json','Library/Application Support/Claude/claude_desktop_config.json','Library/Application Support/Code/User/mcp.json','Library/Application Support/Code/User/settings.json','Library/Application Support/Windsurf/User/settings.json','.config/zed/settings.json','.continue/config.json','.amp/settings.json','.config/amp/settings.json','.factory/mcp.json','.kiro/settings/mcp.json','Library/Application Support/Cursor/User/settings.json']
        for rel in configs:
            data=self.config_json(self.home/rel)
            if data:self.extract(data,rel)
        # TOML support on Python 3.11+, bounded parser fallback before that.
        p=self.home/'.codex/config.toml'
        try:
            if p.is_file() and p.stat().st_size<4_000_000:
                try:
                    import tomllib
                    self.extract(tomllib.loads(p.read_text()),'Codex MCP config')
                except ImportError:
                    for line in p.read_text().splitlines():
                        if re.match(r'\s*(command|args)\s*=',line):
                            for value in re.findall(r'["\'](/[^"\']+)["\']',line):self.add(value,'Codex MCP config')
        except (OSError,ValueError):self.errors.append('Codex config unreadable')
        for root in [self.home/'Library/LaunchAgents',*self.SYSTEM_AGENT_ROOTS]:
            for p in root.glob('*.plist'):
                info=read_plist(p)
                for value in [info.get('Program'),*(info.get('ProgramArguments') or [])]:self.add(value,'Launch agent '+p.stem)
        return self
    def use(self,path):
        # First matching target in list order, via a prefix index.
        key=(id(self.targets),len(self.targets))
        if getattr(self,'_index_key',None)!=key:
            entries=[]
            for i,(p,source) in enumerate(self.targets):
                a=os.path.abspath(p)
                if a.startswith('//'):entries=None;break
                entries.append((a,-i,(p,source)))
            self._index=SubtreeIndex(entries) if entries is not None else None;self._index_key=key
        root=os.path.abspath(path)
        if self._index is None or root.startswith('//'):
            return next(({'path':p,'source':source} for p,source in self.targets if inside(p,path)),None)
        hit=self._index.subtree(root)
        return {'path':hit[1][0],'source':hit[1][1]} if hit else None
