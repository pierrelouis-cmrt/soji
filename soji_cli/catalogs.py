"""Part-based session/Trash catalogs and native document/runtime inspection."""
from __future__ import annotations
import dataclasses
import os
import time
from pathlib import Path
from .levels import SESSION_FLOOR_HOURS
from .platform import native
from .policy import ACTIVE_USE
from .util import json_command,command


def child_paths(scanner,folder):
    """Measured direct children of `folder`, even when `folder` itself was not walked."""
    node=scanner.nodes.get(folder)
    if node is not None:return node.children
    return [p for p in scanner.nodes if os.path.dirname(p)==folder]


def expand_catalogs(scanner,findings=None):
    """Split session and Trash catalog rows into their part rows."""
    result=[]
    live_codex=scanner.writer_ids
    if live_codex is None:live_codex=codex_writer_ids(scanner.home)
    codex_running=any(Path(p).name.casefold()=='codex' for p in scanner.processes if isinstance(p,str))
    for finding in (scanner.findings if findings is None else findings):
        if finding.hint_id in ('claude-sessions','codex-sessions'):
            prefix=finding.path.rstrip('/')+'/'
            parts=[n for p,n in scanner.nodes.items() if p.startswith(prefix) and not n.directory and (p.endswith('.jsonl') or finding.hint_id=='codex-sessions' and p.endswith('.jsonl.zst')) and '/memory/' not in p and '/memories/' not in p]
            units={}
            if finding.hint_id=='claude-sessions':
                units=claude_session_units(scanner,finding.path)
                covered=[m.path for members in units.values() for m in members[1:]]
                parts=[n for n in parts if not any(n.path==c or n.path.startswith(c+'/') for c in covered)]
            if not parts:result.append(finding);continue
            for n in parts:
                f=scanner.classify(n);f.group='Agent and editor history';f.label=Path(n.path).name
                if n.path in units:compound_session(scanner,f,units[n.path])
                f.hint_id=finding.hint_id;f.tier='userData';f.list_only=False;f.managed=True;f.comes_back='gone'
                f.recommendation='trash';f.source='catalog'
                if finding.hint_id=='claude-sessions':
                    sidecar=not f.members and ('/subagents/' in n.path or '/tool-results/' in n.path)
                    f.levels={'careful':72 if sidecar else 168,'balanced':24 if sidecar else 48,'aggressive':3,'reason':'Claude session/sidecar idle policy'}
                else:
                    f.levels={'careful':168,'balanced':48,'aggressive':3,'reason':'Codex executable idle branches: 7 days / 2 days / 3 hours'}
                for member in (f.members or [{'path':n.path}]):
                    activity=scanner.activity.last(member['path']) if scanner.activity else None
                    if activity and activity.at>(f.last_activity or 0):f.last_activity=activity.at
                if finding.hint_id=='codex-sessions' and any(key in Path(n.path).name for key in live_codex):
                    f.last_activity=scanner.now
                    f.evidence.append({'check':'codexWriterLock','active':True})
                    f.hold('Codex session has a writer lock',ACTIVE_USE)
                if finding.hint_id=='codex-sessions' and codex_running:
                    freshness=codex_process_freshness(scanner.recent_activity_hours)
                    if scanner.now-f.newest<freshness:
                        f.hold('Codex is running and this session changed recently',ACTIVE_USE)
                        f.evidence.append({'check':'codexProcessFreshness','active':True,'seconds':freshness})
                # Associate cwd via bounded metadata parser; running/open-file guard
                # on the exact transcript remains authoritative.
                from .activity import ActivityIndex
                probe=ActivityIndex(scanner.home,scanner.now);probe.jsonl_metadata(n.path,'session')
                if probe.records:
                    cwd=probe.records[0].path
                    exists=Path(cwd).exists()
                    if not exists and finding.hint_id=='claude-sessions':
                        # Activity records hold cwd and time only: they cannot
                        # prove the project was deleted rather than moved or
                        # renamed, so the normal session policy stays.
                        f.evidence.append({'check':'sessionProjectMoved','gone':None,
                                           'basis':'no recorded repository identity; a missing folder may be a moved or renamed project'})
                    f.evidence.append({'check':'sessionProject','path':cwd,'exists':exists})
                # Hard floor whatever the judgement: a session changed within a
                # day is never taken at Careful or Balanced.
                f.levels={**f.levels,'careful':max(SESSION_FLOOR_HOURS,f.levels.get('careful',SESSION_FLOOR_HOURS)),
                          'balanced':max(SESSION_FLOOR_HOURS,f.levels.get('balanced',SESSION_FLOOR_HOURS))}
                f.catalog_min_hours={m:f.levels[m] for m in ('careful','balanced','aggressive')}
                result.append(f)
        elif finding.group=='Trash':
            children=child_paths(scanner,finding.path)
            if not children:result.append(finding);continue
            for path in children:
                f=scanner.classify(scanner.nodes[path]);f.group='Trash';f.label=Path(path).name;f.hint_id='trash-item';f.tier='userData'
                f.managed=scanner.tick_trash;f.list_only=not f.managed
                f.levels={'careful':720,'balanced':168,'aggressive':24,'reason':'Old-Trash policy'}
                f.action={'kind':'empty-trash'};f.recommendation='remove';result.append(f)
        else:result.append(finding)
    return result


CLAUDE_SIDECARS=('subagents','tool-results')


def claude_session_units(scanner,project):
    """Map each main transcript `<project>/<id>.jsonl` to its member nodes.

    Members are the transcript plus the existing `<id>/subagents` and
    `<id>/tool-results` folders. Never the
    common `<id>` parent, never memory/memories.
    """
    units={}
    for child in child_paths(scanner,project):
        main=scanner.nodes.get(child)
        if not main or main.directory or not child.endswith('.jsonl'):continue
        members=[main];base=child[:-len('.jsonl')]
        for name in CLAUDE_SIDECARS:
            side=scanner.nodes.get(base+'/'+name)
            if side is not None and Path(side.path).name.casefold() not in ('memory','memories'):members.append(side)
        units[child]=members
    return units


def compound_session(scanner,f,members):
    """Turn a transcript row into one unit: sums, newest member, merged holds."""
    records=[]
    for i,n in enumerate(members):
        part=f if i==0 else scanner.classify(n)
        if part is not f:f.merge_holds(part)
        records.append({'path':n.path,'role':'transcript' if i==0 else Path(n.path).name,'size':n.size,'apparent':n.apparent,'files':n.files,'newest':n.newest,'identity':part.identity})
    # Distinct, non-nested paths: each byte is counted once.
    f.size=sum(r['size'] for r in records);f.apparent=sum(r['apparent'] for r in records)
    f.files=sum(r['files'] for r in records);f.newest=max(r['newest'] for r in records)
    f.members=records;f.label=Path(f.path).name+(f' + {len(records)-1} sidecar folder'+('s' if len(records)>2 else '') if len(records)>1 else '')
    f.evidence.append({'check':'sessionMembers','paths':[r['path'] for r in records]})


def codex_process_freshness(recent_activity_hours):
    """Live Codex process excludes rollouts younger than this many seconds."""
    return max(300,recent_activity_hours*3600)


def codex_writer_ids(home,max_entries=100000):
    """Return writer lock filename stems, without reading lock or session bodies.

    SessionCatalog codexRows strips the filename extension and rejects identifiers
    shorter than eight characters. Existing lock names conservatively retain the
    associated rollout; this is not proof that its process is still alive.
    """
    root=Path(os.environ.get('CODEX_HOME') or Path(home)/'.codex')/'thread-writer-locks'
    result=set()
    try:
        with os.scandir(root) as entries:
            for i,entry in enumerate(entries):
                if i>=max_entries:break
                key=Path(entry.name).stem
                if len(key)>=8:result.add(key)
    except OSError:pass
    return result


def document_versions(path):
    data=native('versions',path)
    if not isinstance(data,list):
        return {**(data if isinstance(data,dict) else {}),'available':False,'error':data.get('error','Document versions unavailable') if isinstance(data,dict) else 'Document versions unavailable'}
    ordered=sorted(data,key=lambda v:v.get('modified',0),reverse=True)
    for i,version in enumerate(ordered):
        version['retained']=i==0 or bool(version.get('conflict')) or bool(version.get('current'))
    return {'available':True,'document':path,'versions':ordered,'policy':'Keep current document, newest older version, and all conflicts'}


def runtime_catalog():
    images=json_command(['/usr/bin/xcrun','simctl','runtime','list','--json'],timeout=15)
    devices=json_command(['/usr/bin/xcrun','simctl','list','devices','--json'],timeout=15)
    # Read process executable names only, never arguments/environment. Native
    # Snapshot.busy additionally filters xcodebuild argv against runtime IDs and
    # simctl runtime add/delete. Holding any such process is conservative until
    # the native snapshot supplies its exact predicate.
    code,out,error=command(['/bin/ps','-axo','pid=,comm='],timeout=5)
    processes=[];processes_available=code==0 and bool(out.strip())
    if processes_available:
        for line in out.splitlines():
            fields=line.strip().split(None,1)
            if len(fields)!=2 or not fields[0].isdigit():
                processes_available=False;break
            name=Path(fields[1]).name
            if name.casefold() in ('xcodebuild','simctl'):
                processes.append({'pid':int(fields[0]),'name':name})
    services_available=images is not None and devices is not None
    # Existing plan/verify callers already gate on available. Do not let a busy
    # or unavailable process snapshot accidentally authorize runtime removal.
    return {'images':images,'devices':devices,
            'servicesAvailable':services_available,'processesAvailable':processes_available,
            'busyProcesses':processes,'busy':bool(processes) if processes_available else None,
            'processPolicy':'Conservatively hold all xcodebuild and simctl processes',
            'observedAt':time.time(),
            'error':('Runtime process snapshot unavailable' if not processes_available else
                     'Simulator runtime tools are busy' if processes else
                     'Runtime/device service unavailable' if not services_available else None),
            'available':services_available and processes_available and not processes}


def measure_catalog_target(scan,path,root,hint):
    from .util import inside as within
    """Measure a catalog unit and discover its current session sidecars."""
    from .models import Node
    for parent in Path(path).parents:
        if str(parent)==root:break
        if scan.private(str(parent)):raise ValueError('Protected session ancestor')
    targets=[path]
    if hint=='claude-sessions':
        relative=Path(path).relative_to(root)
        base=str(Path(root)/relative.parts[0])
        transcript=base if base.endswith('.jsonl') else base+'.jsonl'
        stem=transcript[:-len('.jsonl')]
        targets=([p for p in [transcript,stem+'/subagents',stem+'/tool-results'] if os.path.lexists(p)]
                 if os.path.lexists(transcript) else [path])
        if not any(within(path,p) for p in targets):targets.append(path)
    for target in targets:scan.visit(target)
    scan.nodes[root]=Node(root,directory=True,children=targets,
                          size=sum(scan.nodes[p].size for p in targets),
                          newest=max((scan.nodes[p].newest for p in targets),default=0))
    scan.roots=[root]
