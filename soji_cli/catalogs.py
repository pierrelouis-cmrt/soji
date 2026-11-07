"""Part-based session/Trash catalogs and native document/runtime inspection."""
from __future__ import annotations
import dataclasses
import os
import time
from pathlib import Path
from .engine import Finding
from .platform import native
from .util import json_command,read_plist,command


def expand_catalogs(scanner):
    result=[]
    live_codex=codex_writer_ids(scanner.home)
    codex_running=any(Path(p).name.casefold()=='codex' for p in getattr(scanner,'processes',()) if isinstance(p,str))
    for finding in scanner.findings:
        if finding.hint_id in ('claude-sessions','codex-sessions'):
            prefix=finding.path.rstrip('/')+'/'
            parts=[n for p,n in scanner.nodes.items() if p.startswith(prefix) and not n.directory and (p.endswith('.jsonl') or finding.hint_id=='codex-sessions' and p.endswith('.jsonl.zst')) and '/memory/' not in p and '/memories/' not in p]
            if not parts:result.append(finding);continue
            for n in parts:
                f=scanner.classify(n);f.group='Agent and editor history';f.label=Path(n.path).name
                f.hint_id=finding.hint_id;f.tier='userData';f.list_only=False;f.managed=True;f.comes_back='gone'
                f.recommendation='trash';f.source='catalog'
                if finding.hint_id=='claude-sessions':
                    sidecar='/subagents/' in n.path or '/tool-results/' in n.path
                    f.levels={'careful':72 if sidecar else 168,'balanced':24 if sidecar else 48,'aggressive':3,'reason':'Recovered Claude session/sidecar idle policy'}
                else:
                    f.levels={'careful':168,'balanced':48,'aggressive':3,'reason':'Codex executable idle branches: 7 days / 2 days / 3 hours'}
                activity=scanner.activity.last(n.path) if scanner.activity else None
                if activity:f.last_activity=activity.at
                if finding.hint_id=='codex-sessions' and any(key in Path(n.path).name for key in live_codex):
                    f.last_activity=scanner.now
                    f.evidence.append({'check':'codexWriterLock','active':True})
                    f.holds.append('Codex session has a writer lock')
                if finding.hint_id=='codex-sessions' and codex_running:
                    freshness=codex_process_freshness(getattr(scanner,'recent_activity_hours',0))
                    if scanner.now-f.newest<freshness:
                        f.holds.append('Codex is running and this session changed recently')
                        f.evidence.append({'check':'codexProcessFreshness','active':True,'seconds':freshness})
                # Associate cwd via bounded metadata parser; running/open-file guard
                # on the exact transcript remains authoritative.
                from .activity import ActivityIndex
                probe=ActivityIndex(scanner.home,scanner.now);probe.jsonl_metadata(n.path,'session')
                if probe.records:
                    cwd=probe.records[0].path
                    if not Path(cwd).exists() and finding.hint_id=='claude-sessions':
                        f.levels={'careful':f.levels['balanced'],'balanced':f.levels['aggressive'],'aggressive':3,'reason':'Session project is gone; one level earlier'}
                    f.evidence.append({'check':'sessionProject','path':cwd,'exists':Path(cwd).exists()})
                result.append(f)
        elif finding.group=='Trash' and finding.path in scanner.nodes:
            children=scanner.nodes[finding.path].children
            if not children:result.append(finding);continue
            for path in children:
                f=scanner.classify(scanner.nodes[path]);f.group='Trash';f.label=Path(path).name;f.hint_id='trash-item';f.tier='userData'
                f.managed=bool(getattr(scanner,'tick_trash',False));f.list_only=not f.managed
                f.levels={'careful':720,'balanced':168,'aggressive':24,'reason':'Recovered old-Trash policy'}
                f.action={'kind':'empty-trash'};f.recommendation='remove';result.append(f)
        else:result.append(finding)
    return result


def codex_idle_ordinal(idle_seconds):
    """Raw FindingPart level byte from codexRows (0x1006a3de4..3e10).

    0: Careful, 1: Balanced, 2: Aggressive, 3: below selectable age.
    Boundary comparisons are inclusive. Negative/future idle stays at 3.
    """
    days=idle_seconds/86400
    return 0 if days>=7 else 1 if days>=2 else 2 if days>=0.125 else 3


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
