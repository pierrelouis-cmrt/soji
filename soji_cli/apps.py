"""Installed-app ownership and installed-tool dependency discovery."""
from __future__ import annotations
import fnmatch
import json
import os
from pathlib import Path
import re
import shlex
import shutil
from .util import read_plist,read_json,inside
from .platform import native

class AppCatalog:
    # System-wide roots are class-level so hermetic tests can pin them.
    SYSTEM_ROOTS=(Path('/Applications'),Path('/System/Applications'))
    def __init__(self,home,processes=()):
        self.home=Path(home);self.apps=[];self.processes=processes;self.running=[]
    def build(self):
        for root in [*self.SYSTEM_ROOTS,self.home/'Applications']:
            if not root.exists():continue
            for folder,dirs,files in os.walk(root):
                if len(Path(folder).relative_to(root).parts)>3:dirs[:]=[];continue
                for name in list(dirs):
                    if not name.endswith('.app'):continue
                    dirs.remove(name);p=Path(folder,name);info=read_plist(p/'Contents/Info.plist')
                    self.apps.append({'path':str(p),'bundle':info.get('CFBundleIdentifier',''),'name':info.get('CFBundleDisplayName') or info.get('CFBundleName') or p.stem,'version':info.get('CFBundleShortVersionString','')})
        running=native('apps')
        if isinstance(running,list):self.running=running
        return self
    def owner(self,path):
        parts=Path(path).parts;tokens=[]
        for marker in ['Caches','Application Support','Containers','Group Containers','Preferences']:
            if marker in parts:
                i=parts.index(marker)
                if i+1<len(parts):tokens.append(parts[i+1].removesuffix('.plist'))
        tokens += [Path(path).name.removesuffix('.plist')]
        result=[]
        for app in self.apps:
            for token in tokens:
                normalized=re.sub(r'[^a-z0-9]','',token.casefold().removeprefix('group.'))
                name=re.sub(r'[^a-z0-9]','',app['name'].casefold())
                bundle=app['bundle'].casefold()
                if token.casefold()==bundle or (bundle and token.casefold().startswith(bundle+'.')) or (normalized and normalized==name):result.append(app);break
        return result
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
        # TOML support on Python 3.11+, bounded parser fallback on 3.10.
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
        return next(({'path':p,'source':source} for p,source in self.targets if inside(p,path)),None)
