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
    live_codex=getattr(scanner,'_codex_writer_ids',None)
    if live_codex is None:live_codex=codex_writer_ids(scanner.home)
    codex_running=any(Path(p).name.casefold()=='codex' for p in getattr(scanner,'processes',()) if isinstance(p,str))
    for finding in scanner.findings:
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
                    exists=Path(cwd).exists()
                    if not exists and finding.hint_id=='claude-sessions':
                        gone,signals=session_project_gone(scanner,cwd)
                        if gone:
                            f.levels={'careful':f.levels['balanced'],'balanced':f.levels['aggressive'],'aggressive':3,'reason':'Session project is gone; one level earlier'}
                        f.evidence.append({'check':'sessionProjectMoved','gone':gone,'signals':signals,
                                           'basis':'registered worktrees and cwd history; unavailable historical identity/completeness stays uncertain'})
                    f.evidence.append({'check':'sessionProject','path':cwd,'exists':exists})
                # Hard floor whatever the downgrade or judgement: a session
                # changed within a day is never taken at Careful or Balanced.
                f.levels={**f.levels,'careful':max(SESSION_FLOOR_HOURS,f.levels.get('careful',SESSION_FLOOR_HOURS)),
                          'balanced':max(SESSION_FLOOR_HOURS,f.levels.get('balanced',SESSION_FLOOR_HOURS))}
                result.append(f)
        elif finding.group=='Trash' and finding.path in scanner.nodes:
            children=scanner.nodes[finding.path].children
            if not children:result.append(finding);continue
            for path in children:
                f=scanner.classify(scanner.nodes[path]);f.group='Trash';f.label=Path(path).name;f.hint_id='trash-item';f.tier='userData'
                f.managed=bool(getattr(scanner,'tick_trash',False));f.list_only=not f.managed
                f.levels={'careful':720,'balanced':168,'aggressive':24,'reason':'Old-Trash policy'}
                f.action={'kind':'empty-trash'};f.recommendation='remove';result.append(f)
        else:result.append(finding)
    return result


CLAUDE_SIDECARS=('subagents','tool-results')
SESSION_FLOOR_HOURS=24


def _git_dir(repo):
    g=Path(repo)/'.git'
    try:
        if g.is_dir():return g
        if g.is_file():
            text=g.read_text(encoding='utf-8',errors='replace').strip()
            if text.startswith('gitdir:'):
                target=Path(text[7:].strip())
                return target if target.is_absolute() else (Path(repo)/target)
    except OSError:pass
    return None


def _remote_names(git_dir):
    """Repository names (last URL segment, without .git) of every remote."""
    names=set()
    for config in (git_dir/'config',git_dir.parent.parent/'config' if git_dir.parent.name=='worktrees' else None):
        if config is None:continue
        try:text=config.read_text(encoding='utf-8',errors='replace')
        except OSError:continue
        for line in text.splitlines():
            key,_,value=line.strip().partition('=')
            if key.strip()=='url' and value.strip():
                names.add(value.strip().rstrip('/').rsplit('/',1)[-1].rsplit(':',1)[-1].removesuffix('.git').casefold())
    return names


def _registered_worktrees(git_dir):
    """Worktree paths a repository lists (`git worktree list`, read from disk)."""
    result=set()
    try:entries=list((git_dir/'worktrees').iterdir())[:500]
    except OSError:return result
    for entry in entries:
        try:target=(entry/'gitdir').read_text(encoding='utf-8',errors='replace').strip()
        except OSError:continue
        if target:result.add(os.path.dirname(target) if target.endswith('/.git') else target)
    return result


def session_project_gone(scanner,cwd):
    """(gone, signals) for a session cwd that no longer exists.

    A missing folder is often a renamed or moved project (or a worktree that
    git still lists). Gone is returned only when no such signal exists and the
    evidence is complete; any doubt keeps the normal session policy. The
    current activity schema cannot prove completeness or historic identity,
    so all missing projects currently remain uncertain.
    """
    cache=scanner.__dict__.setdefault('_session_gone_cache',{})
    if cwd in cache:return cache[cwd]
    signals=[]
    cwd=os.path.realpath(cwd);parent=os.path.dirname(cwd);name=os.path.basename(cwd).casefold()
    activity=getattr(scanner,'activity',None)
    history_complete=activity is not None and not activity.errors
    if not history_complete:signals.append('activity history incomplete')
    if not os.path.isdir(parent):signals.append('parent folder missing or unmounted: '+parent)
    # Candidate repositories: folders agents/editors worked in, plus siblings.
    candidates=set()
    records=activity.records if activity else ()
    if len(records)>20000:
        history_complete=False;signals.append('activity candidate budget reached')
    for record in records[:20000]:
        if os.path.isdir(record.path):candidates.add(record.path)
    sibling_complete=True
    try:
        with os.scandir(parent) as it:
            for i,entry in enumerate(it):
                if i>=500:
                    sibling_complete=False;break
                if entry.is_dir(follow_symlinks=False):candidates.add(entry.path)
    except OSError:sibling_complete=False
    if not sibling_complete:signals.append('sibling project search incomplete')
    candidates.discard(cwd)
    repos={};candidate_complete=len(candidates)<=5000
    for folder in sorted(candidates)[:5000]:
        git_dir=_git_dir(folder)
        if git_dir is not None:repos[folder]=git_dir
    if not candidate_complete:signals.append('repository candidate budget reached')
    # ActivityIndex stores cwd/time only. Neither a surviving parent Git
    # repository nor an error-free list of observed cwd paths proves the old
    # repository identity or that the history covers all possible moves.
    # Retain normal policy until that positive evidence can be represented.
    signals.append('missing project has no recorded repository identity; history completeness unproven')
    for folder,git_dir in repos.items():
        listed=_registered_worktrees(git_dir)
        if any(w==cwd or w.startswith(cwd+'/') for w in listed):
            signals.append(f'worktree still registered in {folder}')
    parts=cwd.split('/')
    if 'worktrees' in parts:
        # A worktree is gone only when its main repository is known.
        i=len(parts)-1-parts[::-1].index('worktrees')
        owner='/'.join(parts[:i])
        names={p.casefold() for p in parts[i+1:] if p}
        main=None
        if owner.endswith('/.claude') or owner.endswith('/.codex') or owner.endswith('/.cursor'):
            main=os.path.dirname(owner) if os.path.dirname(owner) in repos or _git_dir(os.path.dirname(owner)) else None
        if main is None:
            main=next((f for f,g in repos.items() if os.path.basename(f).casefold() in names or names&_remote_names(g)),None)
        if main is None:signals.append('worktree whose main repository cannot be found (renamed project?)')
    else:
        # Successor: a sibling project whose recorded use starts where this
        # one's ends (a rename shows up exactly like that).
        last=activity.last(cwd) if activity else None
        if last is not None:
            for folder in candidates:
                if os.path.dirname(folder)!=parent:continue
                records=[r.at for r in activity.records if r.path==folder or r.path.startswith(folder+'/')]
                try:changed=os.lstat(folder).st_ctime
                except OSError:changed=0
                if (records and min(records)>=last.at-86400) or (not records and folder in repos and changed>=last.at-86400):
                    signals.append(f'possible rename: {folder} became active when this project stopped')
    result=(False,signals)
    cache[cwd]=result
    return result


def claude_session_units(scanner,project):
    """Map each main transcript `<project>/<id>.jsonl` to its member nodes.

    Members are the transcript plus the existing `<id>/subagents` and
    `<id>/tool-results` folders. Never the
    common `<id>` parent, never memory/memories.
    """
    units={}
    node=scanner.nodes.get(project)
    for child in (node.children if node else ()):
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
        for hold in part.holds:
            if hold not in f.holds:f.holds.append(hold)
        records.append({'path':n.path,'role':'transcript' if i==0 else Path(n.path).name,'size':n.size,'apparent':n.apparent,'files':n.files,'newest':n.newest,'identity':part.identity})
    # Distinct, non-nested paths: each byte is counted once.
    f.size=sum(r['size'] for r in records);f.apparent=sum(r['apparent'] for r in records)
    f.files=sum(r['files'] for r in records);f.newest=max(r['newest'] for r in records)
    f.members=records;f.label=Path(f.path).name+(f' + {len(records)-1} sidecar folder'+('s' if len(records)>2 else '') if len(records)>1 else '')
    f.evidence.append({'check':'sessionMembers','paths':[r['path'] for r in records]})


def codex_idle_ordinal(idle_seconds):
    """Level ordinal for a Codex rollout from its idle time.

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
