"""Executable interpretations of every shipped SmartRule field.
Field contracts/catalog values are recovered. Grouping and ambiguous thresholds
are reconstructed; evidence entries make those interpretations inspectable.
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
from .util import read_plist,read_json,json_command,command,inside

FIELDS={'untouchedDays','keepNewest','keepBy','keepActive','appNotRunning','appNotInstalled','processes','projectUntouchedDays','minBytes','notApple','keepPinned','newestAfterDays','simulatorDevice','early','workspaceMissing','deviceBuild','knownApp'}

def version_key(name):
    return tuple((0,int(t)) if t.isdigit() else (1,t.casefold()) for t in re.findall(r'\d+|[^\d]+',str(name)))

def version_match(version,pin):
    """ProjectPins.matches, 0x100694d48; literal major/minor prefixes only."""
    def bare(value):
        value=value.lower()
        for prefix in ('ruby-','node-','v'):
            value=value.removeprefix(prefix)
        return value
    version,pin=bare(version),bare(pin)
    return bool(pin) and (version==pin or version.startswith(pin+'.'))

def retention_count(count,mode):
    """CleanupLevel.keepNewest, 0x1004b14b0 (not a base age policy)."""
    return count+1 if mode=='careful' else max(1,count-1) if mode=='aggressive' else count

def rule_threshold_days(rule,mode):
    """Independent SmartRules age gates, not CleanupLevel.forIdle.

    Consumers must evaluate both clocks. None means the rule has no such gate.
    Early outcomes (workspace missing, superseded device build, simulator) need
    to be resolved before applying these gates; see research/rules-recovery.md.
    """
    scale={'careful':(2,4),'balanced':(1,1),'aggressive':(.5,.25)}[mode]
    result={}
    for key,factor in zip(('untouchedDays','projectUntouchedDays'),scale):
        value=rule.get(key)
        if value is not None:
            days=value*factor
            result[key]=max(1,days) if mode=='aggressive' else days
    return result

def workspace_missing(path):
    """DerivedDataProject.workspaceMissing, 0x1006b24d8.

    Unreadable/malformed/missing metadata and empty WorkspacePath all return
    true. The original passes the literal string to fileExistsAtPath.
    """
    info=read_plist(Path(path)/'info.plist')
    workspace=info.get('WorkspacePath') if isinstance(info,dict) else None
    return not isinstance(workspace,str) or not workspace or not os.path.exists(workspace)

def device_build_prepared(path):
    """DeviceSupportFolder.isPrepared, 0x1004c4518: marker plus visible entry."""
    try:names=os.listdir(path)
    except OSError:return False
    return any(n.startswith('.processed_dyld_shared_cache') for n in names) and any(not n.startswith('.') for n in names)

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
    """Successful non-validation distribution identities, 0x1004be4dc."""
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

class ProjectPins:
    def __init__(self):self.pins={'node':set(),'ruby':set(),'android':set()};self.files=[]
    def scan(self,paths):
        for path in paths:
            p=Path(path)
            if p.name not in ('.nvmrc','.node-version','.ruby-version','build.gradle','build.gradle.kts'):continue
            try:
                if p.is_symlink() or p.stat().st_size>1_000_000:continue
                text=p.read_text(errors='replace');self.files.append(str(p))
                if p.name in ('.nvmrc','.node-version'):self.pins['node'].update(t for t in text.split() if re.fullmatch(r'v?\d+(?:\.[\dx*]+){0,2}',t))
                elif p.name=='.ruby-version':self.pins['ruby'].update(text.split())
                else:
                    self.pins['android'].update(re.findall(r'\b(?:compileSdk(?:Version)?|targetSdk(?:Version)?)\s*(?:=|\()?\s*["\']?(\d+)',text))
                    self.pins['android'].update(re.findall(r'\b(?:buildToolsVersion|ndkVersion)\s*(?:=|\()?\s*["\']([0-9.]+)',text))
            except OSError:continue
        return self
    def keeps(self,path,kind):
        name=Path(path).name.removeprefix('android-')
        return any(version_match(name,p) for p in self.pins.get(kind,()))

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
        self.pins=ProjectPins().scan(scanner.nodes)
        self.devices=devices or DeviceCatalog(scanner.home).build()
        self.connected_checked=False;self.connected_known=False
        self.siblings=collections.defaultdict(list)
        for path in scanner.nodes:
            match=scanner.catalog.match(path)
            if match:self.siblings[match[0]['id']].append(path)
        self.archive_cache={}
    def active(self,path,markers):
        # Literal marker paths: the executable does not glob keepActive.
        name=Path(path).name
        for marker in markers:
            expanded=marker.replace('~',str(self.home),1) if marker.startswith('~') else marker
            p=Path(expanded)
            try:
                mode=p.lstat().st_mode
                if stat.S_ISLNK(mode):
                    resolved=p.resolve(strict=True)
                    if inside(resolved,os.path.realpath(path)):return marker
                elif stat.S_ISREG(mode) and p.stat().st_size<=4095:
                    text=p.read_text(encoding='utf-8').strip()
                    if text and (text==name or name.startswith(text+'-') or name.endswith('-'+text) or text[0].isnumeric() and version_match(name,text)):return marker
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
        if by=='bundle':return self.archive(path)[0]
        if by=='device':
            first=name.split(' ')[0]
            return first if ',' in first else ''
        if by in ('product','major'):
            tokens=[t for t in re.split('[-_ ]+',name) if t]
            prefix=[];version=''
            for token in tokens:
                if token[0].isnumeric() or len(token)>1 and token[0]=='v' and token[1].isnumeric():
                    version=token;break
                prefix.append(token)
            product='-'.join(prefix).lower()
            return product+'@'+version.lstrip('v').split('.')[0] if by=='major' and version else product
        return ''
    def retained(self,f):
        by=f.rule.get('keepBy','all');group=self.grouping(f.path,by)
        siblings=[p for p in self.siblings[f.hint_id] if self.grouping(p,by)==group and
                  (by=='bundle' or Path(p).parent==Path(f.path).parent) and
                  self.scanner.nodes[p].reason!='Symlink; not followed']
        def stamp(p):
            if by=='bundle':return self.archive(p)[2]
            # Original uses IndexEntry newestChange, falling back to lstat mtime.
            return self.scanner.nodes[p].newest
        target=stamp(f.path)
        rank=sum(stamp(p) is not None and target is not None and stamp(p)>target for p in siblings if p!=f.path)
        siblings.sort(key=lambda p:stamp(p) if stamp(p) is not None else float('-inf'),reverse=True)
        return rank<int(f.rule.get('keepNewest',0)),rank,siblings
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
        f.rule_min_hours={mode:v['untouchedDays']*24 for mode,v in thresholds.items() if 'untouchedDays' in v}
        f.rule_project_min_hours={mode:v['projectUntouchedDays']*24 for mode,v in thresholds.items() if 'projectUntouchedDays' in v}
        f.rule_early_reason=None;f.rule_level=None
        unknown=set(r)-FIELDS
        if unknown:f.holds.append('Unknown rule fields: '+', '.join(sorted(unknown)))
        owners=self.apps.owner(f.path)
        f.evidence.append({'check':'owner','apps':owners,'basis':'installed bundle metadata / path attribution'})
        if r.get('knownApp') and not owners:f.holds.append('Owning application is unknown')
        if r.get('notApple'):
            apple=any(a['bundle'].startswith('com.apple.') for a in owners) or any(p.startswith('com.apple.') or p.startswith('group.com.apple.') for p in Path(f.path).parts)
            if apple:f.holds.append('Apple-owned container excluded by rule')
        if r.get('appNotInstalled') and owners:f.holds.append('Owning application is installed')
        if r.get('appNotRunning'):
            if any(self.apps.is_running(a) for a in owners):f.holds.append('Owning application is running')
            elif not owners and not r.get('processes'):f.holds.append('Cannot confirm application ownership or running state')
        if r.get('minBytes',0)>f.size:f.holds.append('Below hint minimum size')
        active=self.active(f.path,r.get('keepActive',[]))
        if active:f.holds.append('Active version: '+active)
        if r.get('keepPinned') and self.pins.keeps(f.path,r['keepPinned']):f.holds.append('Version pinned by a project')
        if r.get('keepNewest'):
            retained,rank,siblings=self.retained(f)
            counts={mode:retention_count(r['keepNewest'],mode) for mode in ('careful','balanced','aggressive')}
            f.evidence.append({'check':'retention','keepBy':r.get('keepBy'),'rank':rank,'siblings':len(siblings),'keepNewest':r['keepNewest'],'counts':counts,'basis':'strictly newer timestamps, not version labels'})
            for mode,count in counts.items():
                if rank<count:
                    if mode=='aggressive' and r.get('newestAfterDays') is not None:
                        if (self.scanner.now-f.newest)/86400>=r['newestAfterDays']:continue
                    f.mode_holds[mode]='Retained newest version in '+r.get('keepBy','all')+' group'
            if r.get('keepBy')=='bundle' and self.newest_uploaded(f.path,siblings):
                f.holds.append('Newest uploaded archive retained')
        f.evidence.append({'check':'ruleThresholds','days':{mode:rule_threshold_days(r,mode) for mode in ('careful','balanced','aggressive')},'basis':'SmartRules.evaluate 0x1006ac904 onward; requires engine integration'})
        if r.get('workspaceMissing'):
            missing=workspace_missing(f.path)
            if missing:
                # SmartRules early Outcome (0x1006ac248-0x1006ac2b4): level=Careful,
                # earlier-collected holds kept, rank/age loop skipped. Generic
                # holds, recency floor and age/activity policy still apply later.
                f.rule_early_reason='workspaceMissing';f.rule_level='careful'
                f.rule_min_hours={};f.rule_project_min_hours={};f.mode_holds={}
            f.evidence.append({'check':'workspaceMissing','missing':missing,'basis':'literal WorkspacePath existence; absent/unreadable metadata is missing'})
        if r.get('deviceBuild'):
            if not self.connected_checked:self.connected_known=self.devices.connected();self.connected_checked=True
            build_match=re.search(r'\(([A-Za-z0-9]+)\)',Path(f.path).name)
            build=build_match.group(1) if build_match else None
            if not self.connected_known:f.holds.append('Connected-device build state unavailable')
            elif build and build in self.devices.device_builds:f.holds.append('A connected device uses this build')
            # newerBuild requires a prepared sibling and a parsed build train;
            # a natural-sort name comparison cannot prove this early outcome.
            f.evidence.append({'check':'deviceBuild','status':'supersession early outcome requires prepared sibling; not implemented'})
        if r.get('simulatorDevice'):
            device=self.devices.devices.get(Path(f.path).name)
            if not self.devices.available:f.holds.append('Simulator state unavailable')
            elif device and device.get('state')!='Shutdown':f.holds.append('Simulator is not shut down')
            elif device:
                runtime=next((x for x in self.devices.runtime_images if x.get('identifier')==device['runtime']),None)
                if device.get('isAvailable') is False or runtime and not runtime.get('isAvailable',True):
                    f.special_min_hours=0;f.levels={'careful':0,'balanced':0,'aggressive':0,'reason':'Simulator runtime is unavailable'}
                else:
                    peers=[d for d in self.devices.devices.values() if d.get('runtime')==device['runtime']]
                    bundles=Path(f.path)/'data/Containers/Bundle/Application'
                    try:has_apps=bundles.exists() and any(not p.name.startswith('.') for p in bundles.iterdir())
                    except OSError:has_apps=True
                    if len(peers)>1 and not has_apps:f.levels={'balanced':168,'aggressive':168,'reason':'Spare shut-down simulator without installed app bundles'}
                f.action={'kind':'simulator-device','udid':device['udid']}
            else:
                # Orphan folders have no valid simctl identity: do not fabricate one.
                f.evidence.append({'check':'simulatorDevice','status':'absent from simctl; filesystem orphan'})
        if self.activity.errors and (r.get('projectUntouchedDays') or f.group in ('Agent worktrees','Agent and editor history')):f.holds.append('Activity source verification incomplete')
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
        if r.get('early') and f.group=='Agent worktrees' and not f.holds:
            f.special_min_hours=max(1,r.get('untouchedDays',3)*24);f.levels={'careful':f.special_min_hours,'balanced':f.special_min_hours,'aggressive':f.special_min_hours,'reason':'Clean, merged and pushed worktree; recovered idle rule'}
        return f
