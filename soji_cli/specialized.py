"""Executable interpretations of every `rule` field in the hint catalog.
Evidence entries make each interpretation inspectable. data/README.md
documents the fields.
"""
from __future__ import annotations
import collections
import datetime as dt
import stat
import json
import os
from pathlib import Path
import re
import tempfile
import time
from .util import read_plist,read_json,json_command,command,inside

FIELDS={'minIdleDays','minProjectIdleDays','keepNewest','keepNewestPer','newestGoesAtAggressiveAfterDays','keepVersionPointedToBy','keepProjectPinnedVersions','minSizeBytes','notWhileRunning','notWhileOwnerRuns','onlyIfOwnerInstalled','onlyIfOwnerNotInstalled','notIfAppleOwned','checkWorkspaceExists','checkDeviceBuilds','checkSimulatorDevice','sameIdleAtEveryLevel','checkCodexRuntime'}
# How `keepNewestPer` reads in a hold.
KEEP_PER_TEXT={'app':'app','device':'device','product':'product','majorVersion':'major version','minorVersion':'minor version','folder':'folder'}

def version_key(name):
    return tuple((0,int(t)) if t.isdigit() else (1,t.casefold()) for t in re.findall(r'\d+|[^\d]+',str(name)))

def split_version(name):
    """Leaf name -> (product tokens, first version-like token or '')."""
    prefix=[]
    for token in (t for t in re.split('[-_ ]+',str(name)) if t):
        if token[0].isnumeric() or len(token)>1 and token[0]=='v' and token[1].isnumeric():
            return prefix,token
        prefix.append(token)
    return prefix,''

def version_number(name):
    """Numeric parts of the leaf's version token, or None when it has none."""
    parts=re.findall(r'\d+',split_version(Path(name).name)[1])
    return tuple(int(n) for n in parts) if parts else None

def version_match(version,pin):
    """Project pin match: literal major/minor prefixes only."""
    def bare(value):
        value=value.lower()
        for prefix in ('ruby-','node-','v'):
            value=value.removeprefix(prefix)
        return value
    version,pin=bare(version),bare(pin)
    return bool(pin) and (version==pin or version.startswith(pin+'.'))

def retention_count(count,mode):
    """Keep-newest count for a mode (not a base age policy)."""
    return count+1 if mode=='careful' else max(1,count-1) if mode=='aggressive' else count

def rule_threshold_days(rule,mode):
    """Rule age gates (minIdleDays, minProjectIdleDays), not CleanupLevel.forIdle.

    Consumers must evaluate both clocks. None means the rule has no such gate.
    Early outcomes (workspace missing, superseded device build, simulator) need
    to be resolved before applying these gates.
    """
    scale={'careful':(2,4),'balanced':(1,1),'aggressive':(.5,.25)}[mode]
    result={}
    for key,factor in zip(('minIdleDays','minProjectIdleDays'),scale):
        value=rule.get(key)
        if value is not None:
            days=value*factor
            result[key]=max(1,days) if mode=='aggressive' else days
    return result

def codex_bundle_version(folder):
    """bundleVersion of a Codex runtime folder (its own or payload/*/runtime.json).

    Returns (version tuple or None, readable). No runtime.json at all:
    (None, True) -- absence says nothing about whether the install is in use.
    An unreadable/malformed one, or an unreadable folder: (None, False).
    """
    root=Path(folder)
    try:
        # Listed explicitly: glob() would silently skip unreadable folders.
        os.listdir(root)
        candidates=[root/'runtime.json']
        payload=root/'payload'
        if payload.is_dir() and not payload.is_symlink():
            for name in sorted(os.listdir(payload)):
                entry=payload/name
                if entry.is_dir() and not entry.is_symlink():
                    os.listdir(entry)
                    candidates.append(entry/'runtime.json')
    except OSError:return None,False
    versions=set()
    for candidate in candidates:
        try:
            if candidate.is_symlink():return None,False
            if not candidate.is_file():continue
            data=json.loads(candidate.read_text(encoding='utf-8'))
            version=data.get('bundleVersion') if isinstance(data,dict) else None
            if not isinstance(version,str) or not re.fullmatch(r'[0-9]+(\.[0-9]+)*',version):return None,False
            versions.add(tuple(int(x) for x in version.split('.')))
        except (OSError,ValueError):return None,False
    if len(versions)>1:return None,False
    return next(iter(versions),None),True


CODEX_INSTALL_PREFIX='codex-runtime-install-'


def codex_runtime_reference(runtimes):
    """The codex-runtime-install-* root `codex-primary-runtime` resolves into.

    Returns (install root path or None, why it is not usable). Only a readable
    symlink that resolves inside a sibling install directory with a readable
    bundleVersion counts. A plain directory (an extracted copy), a missing or
    dangling link, anything resolving elsewhere, or missing/malformed metadata
    at the target identifies nothing.
    """
    runtimes=Path(runtimes)
    primary=runtimes/'codex-primary-runtime'
    try:
        if not primary.is_symlink():
            return None,('codex-primary-runtime is missing' if not os.path.lexists(primary)
                         else 'codex-primary-runtime is not a reference to an install')
        base=os.path.realpath(runtimes)
        target=os.path.realpath(primary)
    except OSError:return None,'codex-primary-runtime unreadable'
    rel=os.path.relpath(target,base)
    first=rel.split(os.sep,1)[0]
    if rel.startswith('..') or not first.startswith(CODEX_INSTALL_PREFIX):
        return None,'codex-primary-runtime resolves outside the Codex runtime installs'
    install=os.path.join(base,first)
    try:
        if not os.path.isdir(target) or os.path.islink(install) or not os.path.isdir(install):
            return None,'codex-primary-runtime target is missing'
    except OSError:return None,'codex-primary-runtime target unreadable'
    version,ok=codex_bundle_version(install)
    if not ok or version is None:return None,'runtime metadata of the referenced install is missing or unreadable'
    target_version,target_ok=codex_bundle_version(target)
    if not target_ok or target_version!=version:
        return None,'primary target has unknown runtime layout or metadata'
    return install,''


def codex_runtime_current(path,siblings=()):
    """Why a codex-runtime-install-* folder must be kept, or ''.

    Supersession must be positively identified: an install is a candidate only
    when `codex-primary-runtime` is a readable reference resolving to a
    DIFFERENT install with readable metadata. Without that (no primary, an
    extracted primary directory, unknown layout, unreadable or malformed
    metadata) every install is held: the in-use one cannot be told apart, and
    a version number, a date or missing metadata is no proof (Nov 8: the
    in-use L2Mqle matched neither the primary's version nor the highest one).
    """
    mine,ok=codex_bundle_version(path)
    if mine is None or not ok:return 'Codex runtime metadata unreadable; cannot tell whether it is current'
    try:
        roots=Path(path).parent
        for entry in roots.iterdir():
            if entry.name.startswith(CODEX_INSTALL_PREFIX):
                version,readable=codex_bundle_version(entry)
                if entry.is_symlink() or version is None or not readable:
                    return 'Codex runtime inventory has unknown metadata or layout; every install is kept'
    except OSError:return 'Codex runtime inventory unreadable; every install is kept'
    install,why=codex_runtime_reference(Path(path).parent)
    if install is None:return 'No readable reference identifies the Codex runtime in use ('+why+'); every install is kept'
    try:same=os.path.samefile(install,path)
    except OSError:return 'Codex runtime install unreadable; cannot tell whether it is current'
    if same:return 'codex-primary-runtime points to this install'
    return ''


def workspace_missing(path):
    """True when a DerivedData project's workspace no longer exists.

    Unreadable/malformed/missing metadata and empty WorkspacePath all return
    true. WorkspacePath is checked as a literal path (not URL-decoded).
    """
    info=read_plist(Path(path)/'info.plist')
    workspace=info.get('WorkspacePath') if isinstance(info,dict) else None
    return not isinstance(workspace,str) or not workspace or not os.path.exists(workspace)

def device_build_prepared(path):
    """A prepared device-support folder: marker plus visible entry."""
    try:names=os.listdir(path)
    except OSError:return False
    return any(n.startswith('.processed_dyld_shared_cache') for n in names) and any(not n.startswith('.') for n in names)

def device_support_name(name):
    """Parse `[DEVICE ]VERSION (BUILD)` -> (device, version, build) or None.

    `[DEVICE ]VERSION (BUILD)`: ends with ')', BUILD (after the last '(') is
    non-empty letters/digits; the rest splits on spaces into 1 or 2 words, the
    last (VERSION) starting with a digit; with 2 words the first (DEVICE) must
    contain ','.
    """
    if not isinstance(name,str) or not name.endswith(')') or '(' not in name:return None
    i=name.rindex('(')
    build=name[i+1:-1]
    if not build or not all(c.isalpha() or c.isnumeric() for c in build):return None
    words=[w for w in name[:i].split(' ') if w]
    if not words or len(words)>2 or not words[-1][0].isnumeric():return None
    if len(words)==2 and ',' not in words[0]:return None
    return (words[0] if len(words)==2 else None),words[-1],build

def build_number(build):
    """Parse a build number -> (train, number) or None.

    Digits, one letter, then 1-3 digits: '21A329' -> ('21A', 329). Anything
    else (e.g. beta '22A5316k') is None and newerBuild falls back to dates.
    """
    letter=next((i for i,c in enumerate(build) if c.isalpha()),None)
    if not letter or not all(c.isnumeric() for c in build[:letter]):return None
    rest=build[letter+1:]
    if not rest or len(rest)>3 or not rest.isascii() or not rest.isdigit():return None
    return build[:letter+1],int(rest)

def is_device_support(path):
    """Path is .../Xcode/<* DeviceSupport>/<name>."""
    p=Path(path)
    return p.parent.name.endswith(' DeviceSupport') and p.parent.parent.name=='Xcode'

def _birth_seconds(path):
    # lstat st_birthtimespec.tv_sec (struct stat +0x50), whole seconds.
    try:return int(os.lstat(path).st_birthtime)
    except (OSError,AttributeError):return None

def newer_build(path):
    """Newer prepared build of the same device and version, if any.

    Returns the build of a prepared sibling with the same device and version and
    a newer build, else None. Newer means: same BuildNumber train and a higher
    number; when either build does not parse or the trains differ, a strictly
    later creation time (whole seconds). Unreadable dates never count as newer.
    """
    if not is_device_support(path):return None
    me=device_support_name(Path(path).name)
    if me is None:return None
    parent=Path(path).parent
    try:names=os.listdir(parent)
    except OSError:return None
    mine=build_number(me[2]);my_birth=None
    for name in names:
        other=device_support_name(name)
        if other is None or other[:2]!=me[:2] or other[2]==me[2]:continue
        candidate=parent/name
        if not device_build_prepared(candidate):continue
        theirs=build_number(other[2])
        if mine and theirs and mine[0]==theirs[0]:
            if theirs[1]>mine[1]:return other[2]
            continue
        their_birth=_birth_seconds(candidate)
        if my_birth is None:my_birth=_birth_seconds(path)
        if their_birth is not None and my_birth is not None and their_birth>my_birth:return other[2]
    return None

def simulator_device(path):
    """Read a simulator device.plist: name/runtime (String)
    and state (Int) are required; returns None otherwise."""
    info=read_plist(Path(path)/'device.plist')
    if not isinstance(info,dict):return None
    name,runtime,state=info.get('name'),info.get('runtime'),info.get('state')
    if not isinstance(name,str) or not isinstance(runtime,str) or not isinstance(state,int) or isinstance(state,bool):return None
    return {'name':name,'runtime':runtime,'state':state}

def _uuid(text):
    import uuid
    try:return uuid.UUID(text) if re.fullmatch(r'[0-9A-Fa-f-]{36}',text or '') else None
    except ValueError:return None

def simulator_has_twin(path,device=None):
    """Another simulator with the same name and runtime (different UUID).

    True when another device folder in the same Devices directory (a different
    UUID; entries are skipped when neither name parses as a UUID) has the same
    device.plist name and runtime.
    """
    me=device or simulator_device(path)
    if me is None:return False
    parent=Path(path).parent;own=Path(path).name;mine=_uuid(own)
    try:names=os.listdir(parent)
    except OSError:return False
    for name in names:
        if name==own:continue
        theirs=_uuid(name)
        if theirs==mine:continue  # both unparsable, or the same device
        other=simulator_device(parent/name)
        if other and other['name']==me['name'] and other['runtime']==me['runtime']:return True
    return False

def archive_platform(path,props):
    application=props.get('ApplicationPath')
    if not isinstance(application,str) or '..' in application:return ''
    base=Path(str(path)+'/Products/'+application)
    for plist in (base/'Contents/Info.plist',base/'Info.plist'):
        info=read_plist(plist)
        platform=info.get('DTPlatformName') if isinstance(info,dict) else None
        if isinstance(platform,str) and platform:return platform.lower()
    return ''

def archive_uploads(info):
    """Successful non-validation distribution identities."""
    uploads=set()
    rows=info.get('Distributions',[])
    if not isinstance(rows,list):return uploads
    for row in rows:
        if not isinstance(row,dict):continue
        task=row.get('task','')
        if isinstance(task,str) and task.lower()=='validate':continue
        event=row.get('uploadEvent')
        if not isinstance(event,dict) or not isinstance(event.get('state'),str) or event['state'].lower()!='success':continue
        destination=row.get('uploadDestination')
        if not isinstance(destination,str):destination=row.get('destination','')
        if not isinstance(destination,str):destination=''
        if not isinstance(task,str):task=''
        uploads.add(destination.lower()+'|'+task.lower())
    return uploads

class AliasUncertain(Exception):
    """An nvm alias could not be resolved with certainty; hold, never allow."""


NVM_ALIAS_DEPTH=16
NVM_VERSION=re.compile(r'v?\d+(?:\.\d+){0,2}')


def nvm_dir_for(path):
    """`<nvm>` for a candidate `<nvm>/versions/node/<version>`, else None."""
    p=Path(path)
    if p.parent.name=='node' and p.parent.parent.name=='versions':return p.parent.parent.parent
    return None


class NvmAliases:
    """Bounded, cycle-aware nvm alias resolution confined to `<nvm>/alias`.

    nvm stores aliases as one-line text files (`alias/default`, `alias/lts/*`,
    `alias/lts/<codename>`); a value is a version (full or partial), a builtin
    (`node`, `stable`, `system`, `iojs`) or another alias name. `resolve`
    returns version specs a candidate is matched against with `version_match`.
    Anything it cannot establish (missing, unreadable, symlinked, oversized,
    cyclic, too deep or out-of-tree alias; unreadable installed list) raises
    AliasUncertain so callers hold the whole version family.
    """
    def __init__(self,nvm_dir):
        self.dir=Path(nvm_dir);self.alias=self.dir/'alias';self._installed=None
    def installed(self):
        if self._installed is None:
            try:names=os.listdir(self.dir/'versions'/'node')
            except OSError:raise AliasUncertain('installed nvm versions unreadable') from None
            self._installed=[n for n in names if NVM_VERSION.fullmatch(n)]
        return self._installed
    def read(self,name):
        """First line of alias file `name`, or None when no such alias exists."""
        parts=name.split('/')
        if (not name or name.startswith('/') or '\\' in name or '\0' in name
                or any(part in ('','.','..') for part in parts)):
            raise AliasUncertain(f'alias {name!r} would leave the alias folder')
        current=self.alias;chain=[current,*(self.alias.joinpath(*parts[:i+1]) for i in range(len(parts)))]
        for i,current in enumerate(chain):
            try:st=os.lstat(current)
            except FileNotFoundError:return None
            except OSError:raise AliasUncertain(f'alias {name} unreadable') from None
            if stat.S_ISLNK(st.st_mode):raise AliasUncertain(f'alias path {current} is a symlink')
            if i<len(chain)-1:
                if not stat.S_ISDIR(st.st_mode):return None
            elif not stat.S_ISREG(st.st_mode):raise AliasUncertain(f'alias {name} is not a regular file')
            elif st.st_size>4095:raise AliasUncertain(f'alias {name} is too large')
        try:
            fd=os.open(chain[-1],os.O_RDONLY|os.O_NOFOLLOW|getattr(os,'O_NONBLOCK',0))
            with os.fdopen(fd,'rb') as fh:data=fh.read(4096)
            text=data.decode('utf-8')
        except FileNotFoundError:return None
        except (OSError,UnicodeError):raise AliasUncertain(f'alias {name} unreadable') from None
        lines=text.strip().splitlines()
        return lines[0].strip() if lines else ''
    def resolve(self,value,_seen=()):
        value=value.strip()
        if not value:raise AliasUncertain('empty nvm alias')
        if any(c.isspace() for c in value):raise AliasUncertain(f'unrecognized nvm alias text {value!r}')
        low=value.casefold()
        if low in ('node','stable'):
            versions=[(version_number(n),n) for n in self.installed()]
            versions=[v for v in versions if v[0] is not None]
            return {max(versions)[1]} if versions else set()
        if low=='system' or low=='iojs' or low.startswith('iojs-'):return set()
        if NVM_VERSION.fullmatch(value):return {value}
        if low in _seen:raise AliasUncertain('nvm alias cycle: '+' -> '.join((*_seen,low)))
        if len(_seen)>=NVM_ALIAS_DEPTH:raise AliasUncertain('nvm alias chain too deep')
        text=self.read(value)
        if text is None:raise AliasUncertain(f'nvm alias {value} has no target')
        return self.resolve(text,(*_seen,low))
    def selects(self,name,value,_seen=()):
        """Whether `value` can select installed version folder `name`."""
        return any(version_match(name,spec) for spec in self.resolve(value,_seen))


PIN_KINDS={'.nvmrc':'node','.node-version':'node','.ruby-version':'ruby','build.gradle':'android','build.gradle.kts':'android'}
PIN_FILE_LIMIT=1_000_000
PIN_DISCOVERY_SECONDS=120
PIN_DISCOVERY_ENTRIES=5_000_000


class ProjectPins:
    """Versions pinned by project files, plus whether discovery was complete.

    `incomplete` maps a pin kind (or '*' for every kind) to the reason the
    discovery could not see every pin file in scope; such kinds hold.
    """
    def __init__(self):
        self.pins={'node':set(),'ruby':set(),'android':set()};self.node_aliases=set()
        self.files=[];self.incomplete={};self._nvm={}
    def mark(self,kind,reason):self.incomplete.setdefault(kind,reason)
    def read(self,path):
        p=Path(path);kind=PIN_KINDS.get(p.name)
        if kind is None:return
        try:
            # A symlinked pin file still pins; only regular targets are read.
            st=os.stat(p)
            if not stat.S_ISREG(st.st_mode):return
            if st.st_size>PIN_FILE_LIMIT:self.mark(kind,f'pin file too large: {p}');return
            fd=os.open(p,os.O_RDONLY|getattr(os,'O_NONBLOCK',0))
            with os.fdopen(fd,'rb') as fh:text=fh.read(PIN_FILE_LIMIT+1).decode('utf-8',errors='replace')
        except FileNotFoundError:return  # vanished, or a dangling symlink: nothing pins
        except OSError:self.mark(kind,f'pin file unreadable: {p}');return
        self.files.append(str(p))
        if kind=='node':
            for line in text.splitlines():
                for token in line.split('#',1)[0].split():
                    if re.fullmatch(r'v?\d+(?:\.[\dx*]+){0,2}',token):self.pins['node'].add(token)
                    else:self.node_aliases.add(token)
        elif kind=='ruby':self.pins['ruby'].update(text.split())
        else:
            self.pins['android'].update(re.findall(r'\b(?:compileSdk(?:Version)?|targetSdk(?:Version)?)\s*(?:=|\()?\s*["\']?(\d+)',text))
            self.pins['android'].update(re.findall(r'\b(?:buildToolsVersion|ndkVersion)\s*(?:=|\()?\s*["\']([0-9.]+)',text))
    def scan(self,paths):
        names=tuple(PIN_KINDS)
        for path in paths:
            if path.endswith(names):self.read(path)
        return self
    def from_nodes(self,scanner):
        """Pins from a complete walk's nodes; any gap in that walk is incomplete."""
        if scanner.limited or scanner.cancel.is_set():self.mark('*','scan stopped before every folder was read')
        for path,node in scanner.nodes.items():
            if node.own_errors:self.mark('*','unreadable entry '+path)
        return self.scan(scanner.nodes)
    def discover(self,roots,private,max_seconds=None,max_entries=None):
        """Live walk of `roots` for pin files, with Scanner.visit's exclusions.

        Same scope as a full scan: no symlinked folders, private/protected
        subtrees, mount boundaries or depth >=128. Never served from an index.
        """
        deadline=time.monotonic()+(PIN_DISCOVERY_SECONDS if max_seconds is None else max_seconds)
        limit=PIN_DISCOVERY_ENTRIES if max_entries is None else max_entries
        seen=0
        for root in roots:
            stack=[(root,0,None)]
            while stack:
                path,depth,device=stack.pop()
                if time.monotonic()>deadline or seen>limit:
                    self.mark('*','time or size limit reached');return self
                try:st=os.lstat(path)
                except FileNotFoundError:continue
                except OSError:self.mark('*','unreadable folder '+path);continue
                if not stat.S_ISDIR(st.st_mode):continue
                if private(path) or depth>=128 or (device is not None and st.st_dev!=device):continue
                try:
                    with os.scandir(path) as it:entries=[(e.name,e.path,e.is_dir(follow_symlinks=False)) for e in it]
                except FileNotFoundError:continue
                except OSError:self.mark('*','unreadable folder '+path);continue
                for name,child,is_dir in entries:
                    seen+=1
                    if is_dir:stack.append((child,depth+1,st.st_dev))
                    elif name in PIN_KINDS:self.read(child)
        return self
    def hold(self,path,kind):
        """Hold text when `path` is (or may be) pinned by a project, else None."""
        why=self.incomplete.get('*') or self.incomplete.get(kind)
        if why:return 'Project pin discovery incomplete: '+why
        name=Path(path).name.removeprefix('android-')
        if any(version_match(name,p) for p in self.pins.get(kind,())):return 'Version pinned by a project'
        if kind=='node' and self.node_aliases:
            nvm=nvm_dir_for(path)
            for alias in sorted(self.node_aliases):
                if nvm is None:return f'Project-pinned node alias cannot be resolved: {alias}'
                resolver=self._nvm.setdefault(str(nvm),NvmAliases(nvm))
                try:
                    if resolver.selects(name,alias):return 'Version pinned by a project (nvm alias '+alias+')'
                except AliasUncertain as e:return f'Project-pinned nvm alias cannot be resolved ({e}): {alias}'
        return None
    def keeps(self,path,kind):return self.hold(path,kind) is not None

class DeviceCatalog:
    def __init__(self,home,snapshot=None):
        self.home=Path(home);self.snapshot=snapshot;self.available=False;self.devices={};self.runtime_images=[];self.device_builds=set();self.errors=[]
    def build(self):
        data=self.snapshot
        if data is None:data=json_command(['/usr/bin/xcrun','simctl','list','--json'],timeout=15)
        if isinstance(data,dict):
            self.available=True
            for runtime,items in data.get('devices',{}).items():
                for item in items:
                    if isinstance(item,dict) and item.get('udid'):self.devices[item['udid']]={**item,'runtime':runtime}
            self.runtime_images=data.get('runtimes',[])
            self.device_builds.update(data.get('connectedBuilds',[]))
        else:self.errors.append('Simulator service unavailable')
        return self
    def connected(self,snapshot=None):
        if snapshot is not None:data=snapshot
        else:
            with tempfile.TemporaryDirectory(prefix='soji-devices-') as folder:
                out=Path(folder)/'devices.json'
                code,_,_=command(['/usr/bin/xcrun','devicectl','list','devices','--json-output',out],timeout=12)
                data=read_json(out) if code==0 else None
        if not isinstance(data,dict):self.errors.append('Connected-device build state unavailable');return False
        def walk(obj):
            if isinstance(obj,dict):
                for k,v in obj.items():
                    if k in ('osBuildUpdate','osBuild','buildVersion','build') and isinstance(v,str):self.device_builds.add(v)
                    else:walk(v)
            elif isinstance(obj,list):
                for v in obj:walk(v)
        walk(data)
        devices=data.get('result',{}).get('devices',data.get('devices',[]))
        if devices and not self.device_builds:
            self.errors.append('Device list contains no verifiable OS build');return False
        return True

class SpecializedRules:
    def __init__(self,scanner,apps,activity,tools,devices=None):
        self.scanner=scanner;self.apps=apps;self.activity=activity;self.tools=tools;self.home=Path(scanner.home)
        self._pins=None;self._nvm={}
        self._devices=devices or None
        self.connected_checked=False;self.connected_known=False
        self.siblings=collections.defaultdict(list)
        for path in scanner.nodes:
            match=scanner.catalog.match(path)
            if match:self.siblings[match[0]['id']].append(path)
        self.archive_cache={}
    @property
    def devices(self):
        # Built on first use: only simulator and device-support rules need
        # simctl, so other scans and clean checks skip that subprocess.
        if self._devices is None:self._devices=DeviceCatalog(str(self.home)).build()
        return self._devices
    @devices.setter
    def devices(self,value):self._devices=value
    @property
    def pins(self):
        """Project pins over the policy scope, discovered on first use.

        The scope is every scan root plus the home. A complete walk of it is
        reused; otherwise (target-scoped fresh checks, partial roots, or
        `pin_live`) the pin files are discovered anew on the live filesystem.
        """
        if getattr(self,'_pins',None) is None:
            s=self.scanner;home=os.path.realpath(str(self.home))
            roots=[os.path.realpath(r) for r in (getattr(s,'pin_roots',None) or s.roots)]
            if not getattr(s,'pin_live',False) and any(inside(home,r) for r in s.roots):
                self._pins=ProjectPins().from_nodes(s)
            else:
                from .index import outermost
                self._pins=ProjectPins().discover(outermost([home,*roots]),s.private)
        return self._pins
    @pins.setter
    def pins(self,value):self._pins=value
    def nvm_active(self,path,marker_path,marker):
        """Hold text for an nvm alias marker (e.g. alias/default), or None."""
        nvm=Path(marker_path).parent.parent
        resolver=self._nvm.setdefault(str(nvm),NvmAliases(nvm)) if hasattr(self,'_nvm') else NvmAliases(nvm)
        name=Path(marker_path).name
        try:
            text=resolver.read(name)
            if text is None:return None  # no such alias set: nothing is the default
            if resolver.selects(Path(path).name,text,(name.casefold(),)):return 'Active version: '+marker
        except AliasUncertain as e:return f'Active version cannot be determined ({e}): {marker}'
        return None
    def active_reason(self,path,markers):
        """Hold text when a marker names (or may name) `path` as active."""
        found=self._active(path,markers)
        return found[1] if found else None
    def active(self,path,markers):
        """The marker holding `path` as (possibly) active, or None."""
        found=self._active(path,markers)
        return found[0] if found else None
    def _active(self,path,markers):
        # Literal marker paths: keepVersionPointedToBy is never globbed.
        name=Path(path).name
        for marker in markers:
            expanded=marker.replace('~',str(self.home),1) if marker.startswith('~') else marker
            p=Path(expanded)
            nvm=nvm_dir_for(path)
            if nvm is not None and os.path.normpath(str(p.parent))==os.path.normpath(str(nvm/'alias')):
                reason=self.nvm_active(path,p,marker)
                if reason:return marker,reason
                continue
            try:
                mode=p.lstat().st_mode
                if stat.S_ISLNK(mode):
                    resolved=p.resolve(strict=True)
                    if inside(resolved,os.path.realpath(path)):return marker,'Active version: '+marker
                elif stat.S_ISREG(mode) and p.stat().st_size<=4095:
                    text=p.read_text(encoding='utf-8').strip()
                    if text and (text==name or name.startswith(text+'-') or name.endswith('-'+text) or text[0].isnumeric() and version_match(name,text)):return marker,'Active version: '+marker
            except (OSError,UnicodeError,RuntimeError):continue
        return None
    def archive(self,path):
        if path not in self.archive_cache:
            info=read_plist(Path(path)/'Info.plist')
            if not isinstance(info,dict):info={}
            props=info.get('ApplicationProperties',{})
            if not isinstance(props,dict):props={}
            bundle=props.get('CFBundleIdentifier')
            group=('id:'+bundle.lower()) if isinstance(bundle,str) else 'name:'+str(info.get('Name') or Path(path).stem).lower()
            group+='|'+archive_platform(path,props)
            created=info.get('CreationDate')
            if isinstance(created,dt.datetime):
                created=created.replace(tzinfo=dt.timezone.utc) if created.tzinfo is None else created
                created=created.timestamp()
            else:created=None
            self.archive_cache[path]=(group,archive_uploads(info),created)
        return self.archive_cache[path]
    def grouping(self,path,by):
        # groupKey receives the leaf name, not a plist or its parent path.
        name=Path(path).name
        if by=='app':return self.archive(path)[0]
        if by=='device':
            first=name.split(' ')[0]
            return first if ',' in first else ''
        if by in ('product','majorVersion','minorVersion'):
            prefix,version=split_version(name)
            product='-'.join(prefix).lower()
            if by=='product' or not version:return product
            return product+'@'+'.'.join(version.lstrip('v').split('.')[:1 if by=='majorVersion' else 2])
        return ''
    def retained(self,f):
        by=f.rule.get('keepNewestPer','folder');group=self.grouping(f.path,by)
        siblings=[p for p in self.siblings[f.hint_id] if self.grouping(p,by)==group and
                  (by=='app' or Path(p).parent==Path(f.path).parent) and
                  self.scanner.nodes[p].reason!='Symlink; not followed']
        def stamp(p):
            if by=='app':return self.archive(p)[2]
            # Newest change in the subtree.
            return self.scanner.nodes[p].newest
        target=stamp(f.path)
        rank=sum(stamp(p) is not None and target is not None and stamp(p)>target for p in siblings if p!=f.path)
        siblings.sort(key=lambda p:stamp(p) if stamp(p) is not None else float('-inf'),reverse=True)
        # Stricter than a timestamp-only rank: a
        # higher version label also counts as newer, so the highest version is
        # never removed because an older one was touched later. Bundle groups
        # (archives) have no version label. None = no comparable version.
        version_rank=None
        mine=version_number(f.path) if by!='app' else None
        if mine is not None:
            version_rank=sum(v is not None and v>mine for v in (version_number(p) for p in siblings if p!=f.path))
        return min(rank,version_rank if version_rank is not None else rank)<int(f.rule.get('keepNewest',0)),rank,siblings,version_rank
    def newest_uploaded(self,path,siblings):
        _,uploads,created=self.archive(path)
        if created is None:return True  # archiveRank conservatively retains unreadable dates
        newer=set()
        for other in siblings:
            _,other_uploads,other_date=self.archive(other)
            if other!=path and other_date is not None and other_date>created:newer.update(other_uploads)
        return bool(uploads-newer)
    def evaluate(self,f):
        hint=next((h for h in self.scanner.catalog.hints if h['id']==f.hint_id),None)
        if hint and hint.get('cleanCommand'):f.action={'kind':'official-command','hint':f.hint_id,'argv':hint['cleanCommand']}
        r=f.rule;f.mode_holds={};f.special_min_hours=0
        thresholds={mode:rule_threshold_days(r,mode) for mode in ('careful','balanced','aggressive')}
        f.rule_min_hours={mode:v['minIdleDays']*24 for mode,v in thresholds.items() if 'minIdleDays' in v}
        f.rule_project_min_hours={mode:v['minProjectIdleDays']*24 for mode,v in thresholds.items() if 'minProjectIdleDays' in v}
        f.rule_early_reason=None;f.rule_level=None
        unknown=set(r)-FIELDS
        if unknown:f.holds.append('Unknown rule fields: '+', '.join(sorted(unknown)))
        owners=self.apps.owner(f.path)
        f.evidence.append({'check':'owner','apps':owners,'basis':'installed bundle metadata / path attribution'})
        if r.get('onlyIfOwnerInstalled') and not owners:f.holds.append('Owning application is unknown')
        if r.get('notIfAppleOwned'):
            apple=any(a['bundle'].startswith('com.apple.') for a in owners) or any(p.startswith('com.apple.') or p.startswith('group.com.apple.') for p in Path(f.path).parts)
            if apple:f.holds.append('Apple-owned container excluded by rule')
        if r.get('onlyIfOwnerNotInstalled') and owners:f.holds.append('Owning application is installed')
        if r.get('notWhileOwnerRuns'):
            if any(self.apps.is_running(a) for a in owners):f.holds.append('Owning application is running')
            elif not owners and not r.get('notWhileRunning'):f.holds.append('Cannot confirm application ownership or running state')
        if r.get('minSizeBytes',0)>f.size:f.holds.append('Below hint minimum size')
        active=self.active_reason(f.path,r.get('keepVersionPointedToBy',[]))
        if active:f.holds.append(active)
        if r.get('keepProjectPinnedVersions'):
            pinned=self.pins.hold(f.path,r['keepProjectPinnedVersions'])
            if pinned:f.holds.append(pinned)
        if r.get('keepNewest'):
            retained,rank,siblings,version_rank=self.retained(f)
            counts={mode:retention_count(r['keepNewest'],mode) for mode in ('careful','balanced','aggressive')}
            f.evidence.append({'check':'retention','keepNewestPer':r.get('keepNewestPer'),'rank':rank,'versionRank':version_rank,'siblings':len(siblings),'keepNewest':r['keepNewest'],'counts':counts,'basis':'kept if among the newest by timestamp or by version label'})
            held=min(rank,version_rank) if version_rank is not None else rank
            for mode,count in counts.items():
                if held<count:
                    if mode=='aggressive' and r.get('newestGoesAtAggressiveAfterDays') is not None:
                        if (self.scanner.now-f.newest)/86400>=r['newestGoesAtAggressiveAfterDays']:continue
                    f.mode_holds[mode]='Retained newest version per '+KEEP_PER_TEXT[r.get('keepNewestPer','folder')]
            if r.get('keepNewestPer')=='app' and self.newest_uploaded(f.path,siblings):
                f.holds.append('Newest uploaded archive retained')
        f.evidence.append({'check':'ruleThresholds','days':{mode:rule_threshold_days(r,mode) for mode in ('careful','balanced','aggressive')},'basis':'rule age thresholds per mode'})
        if r.get('checkCodexRuntime'):
            current=codex_runtime_current(f.path,self.siblings.get(f.hint_id,[]))
            if current:f.holds.append('Codex runtime kept: '+current)
            f.evidence.append({'check':'codexRuntime','current':current or None,'basis':'superseded only when codex-primary-runtime is a readable link resolving to a different install with readable bundleVersion'})
        if r.get('checkWorkspaceExists'):
            missing=workspace_missing(f.path)
            if missing:
                # Early outcome: level Careful, earlier holds kept, rank/age
                # gates skipped. The normal recency/age policy then applies.
                f.rule_early_reason='workspaceMissing';f.rule_level='careful'
                f.rule_min_hours={};f.rule_project_min_hours={};f.mode_holds={}
            f.evidence.append({'check':'workspaceMissing','missing':missing,'basis':'literal WorkspacePath existence; absent/unreadable metadata is missing'})
        if r.get('checkDeviceBuilds'):
            if not self.connected_checked:self.connected_known=self.devices.connected();self.connected_checked=True
            build_match=re.search(r'\(([A-Za-z0-9]+)\)',Path(f.path).name)
            build=build_match.group(1) if build_match else None
            if not self.connected_known:f.holds.append('Connected-device build state unavailable')
            elif build and build in self.devices.device_builds:f.holds.append('A connected device uses this build')
            # Early outcome for a direct match: a prepared newer build of the
            # same device and version gives level Careful exactly like
            # workspaceMissing; earlier holds stay, retention and rule clocks go,
            # then normal recency applies.
            newer=None
            if f.matched_pattern and f.rule_early_reason is None:
                try:direct=stat.S_ISDIR(os.lstat(f.path).st_mode)
                except OSError:direct=False
                if direct:newer=newer_build(f.path)
            if newer:
                f.rule_early_reason='newerBuild';f.rule_level='careful'
                f.rule_min_hours={};f.rule_project_min_hours={};f.mode_holds={}
            f.evidence.append({'check':'deviceBuild','newerBuild':newer,'basis':'DeviceSupportFolder.newerBuild: same device and version, prepared sibling, BuildNumber train or creation time'})
        if r.get('checkSimulatorDevice'):
            device=self.devices.devices.get(Path(f.path).name)
            if not self.devices.available:f.holds.append('Simulator state unavailable')
            elif device and device.get('state')!='Shutdown':f.holds.append('Simulator is not shut down')
            elif device:
                runtime=next((x for x in self.devices.runtime_images if x.get('identifier')==device['runtime']),None)
                missing=(device.get('isAvailable') is False or (runtime is not None and not runtime.get('isAvailable',True))
                         or (runtime is None and bool(self.devices.runtime_images)))
                if missing:
                    # Runtime not installed: level Careful plus normal recency
                    # (>=7 d Careful, 1-7 d Balanced, 1 h-1 d Aggressive),
                    # expressed as explicit levels.
                    f.special_min_hours=0;f.rule_early_reason='runtimeMissing'
                    f.levels={'careful':168,'balanced':24,'aggressive':1,'reason':'Simulator runtime is not installed'}
                else:
                    bundles=Path(f.path)/'data/Containers/Bundle/Application'
                    try:has_apps=bundles.exists() and any(not p.name.startswith('.') for p in bundles.iterdir())
                    except OSError:has_apps=True
                    # No app bundles and a twin (same device.plist name and
                    # runtime, other UUID): spare simulator, kept on a 7-day
                    # Balanced judgement.
                    twin=not has_apps and simulator_has_twin(f.path)
                    f.evidence.append({'check':'simulatorTwin','apps':has_apps,'twin':twin,'basis':'SimulatorDevice.hasTwin: same name and runtime, different UUID'})
                    if twin:f.levels={'balanced':168,'aggressive':168,'reason':'Spare shut-down simulator: a twin with the same name and runtime exists, and this one has no apps'}
                f.action={'kind':'simulator-device','udid':device['udid']}
            else:
                # Orphan folders have no valid simctl identity: do not fabricate one.
                f.evidence.append({'check':'simulatorDevice','status':'absent from simctl; filesystem orphan'})
        if self.activity.errors and (r.get('minProjectIdleDays') or f.group in ('Agent worktrees','Agent and editor history')):f.holds.append('Activity source verification incomplete')
        activity=self.activity.last(f.path)
        if activity:
            f.last_activity=activity.at
            f.evidence.append({'check':'activity','source':activity.source,'at':activity.at})
            if self.scanner.now-activity.at<max(300,getattr(self.scanner,'recent_activity_hours',0)*3600):f.holds.append('Coding agent or editor used this project recently')
        use=self.tools.use(f.path)
        if use:f.holds.append('Used by installed tool: '+use['source'])
        if f.group=='Agent worktrees':
            state=next((e['state'] for e in f.evidence if e.get('check')=='git'),{})
            if state.get('verified') and state.get('mainWorktree') and not state.get('reason'):f.action={'kind':'git-worktree','repository':state['mainWorktree'],'path':f.path}
        if r.get('sameIdleAtEveryLevel') and f.group=='Agent worktrees' and not f.holds:
            f.special_min_hours=max(1,r.get('minIdleDays',3)*24);f.levels={'careful':f.special_min_hours,'balanced':f.special_min_hours,'aggressive':f.special_min_hours,'reason':'Clean, merged and pushed worktree; idle rule'}
        return f
