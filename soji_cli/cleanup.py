"""Reviewed plans, fresh guard checks, identity-bound moves, journal and undo.
The analysis process never deletes. Only explicit `clean PLAN --apply` mutates
candidate data. No backend or license circumvention is involved.
"""
from __future__ import annotations
import dataclasses
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import time
import uuid
from .util import atomic_json,inside,command


TRASH_NOTICE='Undo works only while the items are still in the Trash. Once the Trash is emptied (by you, or by macOS after 30 days), they cannot be restored.'
# Fresh-guard refusals that mean "something is using this right now". The
# checks are momentary snapshots (an app opens and closes cache files), so a
# path refused for live use stays refused for LIVE_USE_HOLD seconds instead of
# being retried until a snapshot happens to pass.
LIVE_USE_REASONS=('File open or process working in this folder','Owning application is running','Running: ',
                  'A running program is installed here','Codex session has a writer lock',
                  'Coding agent or editor used this project recently','Codex is running and this session changed recently')
LIVE_USE_HOLD=86400
HIGH_RISK_GROUPS=('Toolchains and SDKs','Project dependencies','Editor extensions')


def soji_version():
    from . import __version__
    return __version__


def policy_record(f,mode,now=None,source='fresh'):
    """Audit record of the rule, threshold and reason a row was judged by."""
    get=(lambda k,d=None:f.get(k,d)) if isinstance(f,dict) else (lambda k,d=None:getattr(f,k,d))
    levels=get('levels')
    if isinstance(levels,dict):
        threshold={'basis':'levels','hours':levels.get(mode),'levels':{k:v for k,v in levels.items() if k in ('careful','balanced','aggressive')}}
        reason=levels.get('reason')
    else:
        threshold={'basis':'rule','minIdleHours':(get('rule_min_hours') or {}).get(mode),
                   'minProjectIdleHours':(get('rule_project_min_hours') or {}).get(mode),
                   'ruleLevel':get('rule_level'),'projectIdleHours':get('project_idle_hours')}
        reason=get('rule_early_reason') or get('smart_rule') or f"{get('label')} rule ({get('hint_id')}): age and guard checks only"
    decision=get('decision')
    if not isinstance(f,dict) and now is not None:decision=f.decide(mode,now)[1]
    return {'source':source,'rule':get('hint_id'),'label':get('label'),'group':get('group'),'mode':mode,
            'threshold':threshold,'reason':reason,'decision':decision,'matchedPattern':get('matched_pattern')}


# Rollback outcomes where a staged .soji-removing-* object was left in place.
ROLLBACK_KEPT=('conflict','refused','unavailable','failed')


def recoverability(entry):
    """Whether a journal entry (or member) can still be undone."""
    status=entry.get('status');method=entry.get('method')
    if entry.get('rollback') in ROLLBACK_KEPT:return 'staged copy kept for manual review: '+str(entry.get('stagedPath'))
    if entry.get('rollback')=='restored-other-identity':return 'not removed (rollback restored a different object to the original path)'
    if status=='restored':return 'restored'
    if status not in ('done','partial'):return None
    if method=='permanent' or entry.get('stagedName'):return 'unrecoverable (removed permanently)'
    if method!='trash':return 'not a Trash move'
    target=entry.get('trashedTo')
    if not target:return 'unrecoverable (no Trash location recorded)'
    return 'recoverable while in Trash' if os.path.lexists(target) else 'unrecoverable (Trash emptied)'


def file_identity(path):
    p=Path(path);s=os.lstat(p);parent=os.stat(p.parent,follow_symlinks=False)
    return {'device':s.st_dev,'inode':s.st_ino,'type':stat.S_IFMT(s.st_mode),'parentDevice':parent.st_dev,'parentInode':parent.st_ino,'mtimeNs':s.st_mtime_ns,'ctimeNs':s.st_ctime_ns}


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def create_plan(scanner,mode,paths=None,method='trash'):
    selected=[f for f in scanner.decisions(mode) if f.selected and (paths is None or f.path in paths)]
    items=[]
    for f in selected:
        if not f.identity:continue
        items.append({'path':f.path,'identity':f.identity,'size':f.size,'newest':f.newest,'files':f.files,'hint':f.hint_id,'group':f.group,'action':({} if method=='trash' and f.action.get('kind')=='official-command' else f.action),'method':method,'finding':dataclasses.asdict(f),
                      **({'members':[{'path':m['path'],'role':m['role'],'identity':m['identity'],'size':m['size'],'files':m['files'],'newest':m['newest']} for m in f.members]} if f.members else {})})
    risky=sorted({f.group for f in selected if f.group in HIGH_RISK_GROUPS})
    no_vcs=[f.path for f in selected if f.group=='Project dependencies' and not any(e.get('check')=='git' and (e.get('state') or {}).get('repository') for e in f.evidence)]
    extra=[]
    if risky:extra.append('High-risk groups selected: '+', '.join(risky)+'. Software may need reinstalling or rebuilding.')
    if no_vcs:extra.append(f'{len(no_vcs)} dependency folder(s) outside a VCS checkout: review them before applying.')
    value={'format':'soji-clean-plan/1','id':uuid.uuid4().hex,'createdAt':time.time(),'mode':mode,'roots':scanner.roots,'home':scanner.home,'protected':scanner.protected,'items':items,'method':method,'version':soji_version(),'warnings':['Review paths before applying. Trash is reversible while its item exists; permanent cleanup is not.',TRASH_NOTICE,*extra]}
    value['digest']=digest(value);return value


def validate_plan(plan):
    if not isinstance(plan,dict) or plan.get('format')!='soji-clean-plan/1':raise ValueError('Unsupported plan')
    copy=dict(plan);expected=copy.pop('digest',None)
    if expected!=digest(copy):raise ValueError('Plan contents changed; generate a new plan')
    if time.time()-plan['createdAt']>3600:raise ValueError('Plan expired; rescan and create a fresh plan')
    keys=[(x['path'],json.dumps(x.get('action',{}),sort_keys=True)) for x in plan['items']]
    if len(keys)!=len(set(keys)):raise ValueError('Duplicate cleanup actions')
    by_path={}
    for item in plan['items']:by_path.setdefault(item['path'],[]).append(item)
    for path,items in by_path.items():
        if len(items)>1 and not all(i.get('action',{}).get('kind')=='document-version' and i['action'].get('document')==path for i in items):
            raise ValueError('Duplicate plan paths')
    paths=set(by_path)
    for item in plan['items']:
        if 'members' not in item:continue
        session_members(item)
        for m in item['members']:
            if m['path']!=item['path']:
                if m['path'] in paths:raise ValueError('Duplicate plan paths')
                paths.add(m['path'])
    # Check ancestors rather than every pair (millions of pairs for session batches).
    normalized={os.path.abspath(p).replace('//','/') for p in paths}
    if len(normalized)!=len(paths):raise ValueError('Overlapping cleanup targets')
    for path in normalized:
        parent=os.path.dirname(path)
        while parent!=path:
            if parent in normalized:raise ValueError('Overlapping cleanup targets')
            path,parent=parent,os.path.dirname(parent)
    return plan


SESSION_SIDECARS=('subagents','tool-results')


def session_members(item):
    """Structural check: transcript plus only its own sidecar folders."""
    members=item.get('members')
    if not isinstance(members,list) or not members:raise ValueError('Compound session has no members')
    path=item['path']
    if item.get('hint')!='claude-sessions' or not path.endswith('.jsonl'):raise ValueError('Compound members are only supported for Claude sessions')
    allowed={path}|{path[:-len('.jsonl')]+'/'+name for name in SESSION_SIDECARS}
    seen=[m.get('path') for m in members]
    if seen[0]!=path or len(seen)!=len(set(seen)) or not set(seen)<=allowed:raise ValueError('Compound session members are not the transcript and its sidecars')
    if any(Path(p).name.casefold() in ('memory','memories') or '/memory/' in p or '/memories/' in p for p in seen):raise ValueError('Memory folders are never session members')
    return members


def parent_fd(path):
    """Open each parent component without following symlinks."""
    p=Path(os.path.abspath(path));fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in p.parent.parts[1:]:
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
        return fd
    except BaseException:os.close(fd);raise


def remove_at(fd,name,expected=None,device=None):
    """Descriptor-relative recursive removal; symlinks are unlinked, never followed."""
    s=os.stat(name,dir_fd=fd,follow_symlinks=False)
    if expected and (s.st_dev,s.st_ino)!=expected:raise ValueError('Removal identity changed')
    if device is None:device=s.st_dev
    if s.st_dev!=device:raise ValueError('Removal crosses a mount boundary')
    if stat.S_ISDIR(s.st_mode):
        child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
        try:
            actual=os.fstat(child)
            if (actual.st_dev,actual.st_ino)!=(s.st_dev,s.st_ino):raise ValueError('Directory changed while opening')
            for entry in os.listdir(child):remove_at(child,entry,device=device)
        finally:os.close(child)
        after=os.stat(name,dir_fd=fd,follow_symlinks=False)
        if (after.st_dev,after.st_ino)!=(s.st_dev,s.st_ino):raise ValueError('Directory name changed before removal')
        os.rmdir(name,dir_fd=fd)
    else:os.unlink(name,dir_fd=fd)

def compound_status(entry):
    """Summarize member outcomes without ever claiming partial success as done."""
    members=entry['members'];done=[m for m in members if m['status'] in ('done','restored')]
    uncertain=[m for m in members if m['status']=='prepared']
    if any(m.get('partialDeletionPossible') for m in members):entry['partialDeletionPossible']=True
    if len(done)==len(members):
        entry['status']='done';entry['method']=members[0].get('method',entry.get('method'));entry.pop('error',None)
    elif uncertain:
        entry['status']='prepared';entry['error']=f'Session member outcome uncertain: {len(done)} of {len(members)} members cleaned'
    elif done or entry.get('partialDeletionPossible'):
        entry['status']='partial';entry['partial']=True
        failed=next((m for m in members if m['status']=='failed'),None)
        entry['error']=f'Partial session cleanup: {len(done)} of {len(members)} members cleaned'+(f'; {failed["path"]}: {failed.get("error")}' if failed else '')
    else:
        entry['status']='failed';failed=next((m for m in members if m.get('error')),{})
        entry['error']=failed.get('error','No session member was cleaned')
    return entry


class Cleaner:
    def __init__(self,state,*,context=True,trash_directory=None):
        self.state=Path(state).expanduser().resolve();self.state.mkdir(parents=True,exist_ok=True)
        self.journal=self.state/'journal.jsonl';self.context=context;self.trash_directory=trash_directory
        self._batch=None

    def collect_context(self,scan):
        """Share live snapshots for at most one second, only within one apply call.

        Target contents and identities are never cached. Inventory snapshots have
        a separate five-second lifetime; new batches always start from scratch.
        """
        batch=self._batch
        now=time.monotonic()
        if batch is None or now-batch.get('context_at',float('-inf'))>=1:
            scan.collect_context()
            from .catalogs import codex_writer_ids
            locks=codex_writer_ids(scan.home)
            if batch is not None:
                batch.update(context_at=now,processes=scan.processes,open_paths=scan.open_paths,
                             warnings=scan.context_warnings,locks=locks)
        else:
            scan.processes=batch['processes'];scan.open_paths=batch['open_paths']
            scan.context_warnings=list(batch['warnings']);locks=batch['locks']
        scan._codex_writer_ids=locks

    def measure_catalog_target(self,scan,path,root,hint):
        """Reconstruct the catalog from just this target's current filesystem unit.

        A synthetic container feeds the same catalog policy as a full scan. For
        Claude, discover both sidecars anew, including a newly created transcript
        that would subsume a formerly standalone subagent row.
        """
        from .engine import Node
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
            if not any(inside(path,p) for p in targets):targets.append(path)
        for target in targets:scan.visit(target)
        scan.nodes[root]=Node(root,directory=True,children=targets,
                              size=sum(scan.nodes[p].size for p in targets),
                              newest=max((scan.nodes[p].newest for p in targets),default=0))
        scan.roots=[root]
    def append(self,entry):
        fd=os.open(self.journal,os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(fd,'a') as f:f.write(json.dumps(entry)+'\n');f.flush();os.fsync(f.fileno())
        except BaseException:raise
    def live_use_refusal(self,path):
        """Recent journal refusal of `path` for live use, or None."""
        batch=self._batch
        refusals=batch.get('refusals') if batch is not None else None
        if refusals is None:
            refusals={}
            now=time.time()
            for e in self.entries():
                error=e.get('error') or ''
                if e.get('status')=='failed' and now-e.get('at',0)<LIVE_USE_HOLD and any(r in error for r in LIVE_USE_REASONS):
                    if e.get('at',0)>refusals.get(e['path'],(0,''))[0]:refusals[e['path']]=(e['at'],error)
            if batch is not None:batch['refusals']=refusals
        return refusals.get(path)
    def fresh(self,item,plan):
        from .engine import Scanner
        path=item['path'];self._fresh_finding=None
        refused=self.live_use_refusal(path)
        if refused:
            hours=(time.time()-refused[0])/3600
            raise ValueError(f'In use {hours:.1f} h ago ({refused[1].removeprefix("Fresh guards refuse: ")}); skipped for 24 h rather than retried until a momentary check passes')
        if not any(inside(path,r) for r in plan['roots']):raise ValueError('Outside scan roots')
        if path in plan['roots']:raise ValueError('Refusing a scan root itself')
        uninstall_action=(item.get('action') or {}).get('kind')=='uninstall'
        native_action=(item.get('action') or {}).get('kind') in ('document-version','simulator-runtime')
        if not inside(path,plan['home']) and not native_action and not uninstall_action:raise ValueError('System/outside-home filesystem cleanup is not enabled')
        if inside(path,str(self.state)):raise ValueError('Cannot clean own state')
        if any(inside(path,p) or inside(p,path) for p in plan.get('protected',[])):raise ValueError('Protected path overlap')
        identity=file_identity(path)
        if identity!=item['identity']:raise ValueError('File or parent identity changed since analysis')
        members=session_members(item) if 'members' in item else None
        for m in members or ():
            if any(inside(m['path'],p) or inside(p,m['path']) for p in plan.get('protected',[])):raise ValueError('Protected path overlap')
            try:current=file_identity(m['path'])
            except OSError:raise ValueError('Session member missing since analysis: '+m['path'])
            if current!=m['identity']:raise ValueError('Session member identity changed since analysis: '+m['path'])
        if uninstall_action:
            from .uninstall import verify_uninstall
            verify_uninstall(item,plan['home']);return identity
        if native_action:
            from .nativeplans import verify_native
            verify_native(item)
            return identity
        batch=self._batch
        scan=Scanner([path],home=plan['home'],protected=plan.get('protected',[]),min_bytes=0,context=self.context,max_seconds=120,max_files=1000000,inherit_hint=item.get('hint') or None,catalog=batch.get('catalog') if batch else None)
        if batch is not None:
            batch['catalog']=scan.catalog
            # Marker listings are mutable filesystem facts, not catalog rules.
            scan.catalog.markers_cache.clear();scan.catalog.match_cache.clear()
        measure_root=path
        if item.get('finding',{}).get('rule',{}).get('minProjectIdleDays'):
            measure_root=scan.project_for(path) or path
        elif item.get('finding',{}).get('rule',{}).get('keepNewest'):
            # Retention ranks against siblings: measure the whole version family,
            # i.e. climb one level per trailing wildcard segment of the pattern.
            pattern=item.get('finding',{}).get('matched_pattern') or ''
            depth=0
            for segment in reversed(pattern.split('/')):
                if not any(c in segment for c in '*?['):break
                depth+=1
            family=Path(path)
            for _ in range(depth):family=family.parent
            if depth and inside(path,str(family)) and inside(str(family),plan['home']):measure_root=str(family)
        if item.get('hint') in ('claude-sessions','codex-sessions','trash-item'):
            for parent in Path(path).parents:
                match=scan.catalog.match(str(parent))
                if match and (match[0]['id']==item.get('hint') or item.get('hint')=='trash-item' and match[0]['id']=='trash'):
                    measure_root=str(parent);break
            scan.tick_trash=item.get('hint')=='trash-item'
        scan.started=time.monotonic()
        # Fresh process/open-file snapshot, taken while the target is re-measured.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(1) as pool:
            context=pool.submit(self.collect_context,scan)
            if item.get('hint') in ('claude-sessions','codex-sessions','trash-item') and measure_root!=path:
                self.measure_catalog_target(scan,path,measure_root,item['hint'])
            else:scan.visit(measure_root)
            context.result()
        n=scan.nodes.get(path)
        if n is None:raise ValueError('Fresh target could not be measured')
        if scan.limited:raise ValueError('Fresh verification incomplete, protected, or contains secrets')
        for m in members or [{'path':path,'size':item['size'],'newest':item['newest'],'files':item['files']}]:
            mn=scan.nodes.get(m['path'])
            if mn is None:raise ValueError('Fresh target could not be measured')
            if mn.errors or mn.skipped or mn.secret:raise ValueError('Fresh verification incomplete, protected, or contains secrets')
            if mn.size!=m['size'] or mn.newest!=m['newest'] or mn.files!=m['files']:raise ValueError('Contents changed since analysis'+(': '+m['path'] if members else ''))
        if item.get('hint') in ('claude-sessions','codex-sessions','trash-item') and measure_root!=path:
            # Re-derive the catalog row (FindingPart policy, compound members)
            # from its catalog root, not from a bare file.
            scan.roots=[measure_root]
        if batch is not None and time.monotonic()-batch.get('inventory_at',float('-inf'))<5:
            scan._shared_inventories=batch['inventories']
        inventory_started=time.monotonic()
        scan._build_findings()
        if batch is not None and not hasattr(scan,'_shared_inventories'):
            batch.update(inventory_at=inventory_started,inventories=(scan.activity,scan.apps,scan.tools))
        f=next((f for f in scan.findings if f.path==path),None)
        if members is not None:
            now_members=[(m['path'],m['identity']) for m in (f.members if f else [])]
            if now_members!=[(m['path'],m['identity']) for m in members]:raise ValueError('Session members changed since analysis')
        elif f is not None and f.members:raise ValueError('Target became a compound session; generate a new plan')
        if f is None:
            if item.get('hint') in ('claude-sessions','codex-sessions','trash-item'):raise ValueError('Session or Trash catalog membership changed since analysis')
            f=scan.classify(n)
        permit=plan.get('routinePermit')
        if permit:
            if f.tier!='regenerable' or f.comes_back not in ('rebuilds','downloads'):raise ValueError('Routine cannot remove non-regenerable data')
            if permit.get('groups') and f.group not in permit['groups']:raise ValueError('Routine group changed')
            if f.size<permit.get('minItemBytes',0) or time.time()-max(f.newest,f.last_activity or 0,f.date_added or 0)<permit.get('minIdleHours',0)*3600:raise ValueError('Routine conditions no longer hold')
        # Restore verified agent thresholds, never old holds or filesystem facts.
        original=item['finding']
        if original.get('source') in ('agent','both'):
            judgment=next((e.get('judgment') for e in reversed(original.get('evidence',[])) if e.get('check')=='agent'),None)
            if not isinstance(judgment,dict):raise ValueError('Agent judgment cannot be revalidated')
            from .ai import AIAnalyzer
            if not any(candidate is f for candidate in scan.findings):scan.findings.append(f)
            AIAnalyzer(self.state).apply(scan,[judgment])
            f=next(candidate for candidate in scan.findings if candidate.path==path)
        # Part-based session/Trash catalogs already reconstruct their own policy.
        if not f.decide(plan['mode'],time.time())[0]:raise ValueError('Fresh guards refuse: '+f.decide(plan['mode'],time.time())[1])
        if f.action.get('kind')=='official-command' and item.get('method')!='trash':
            from .commands import may_remove_permanently
            if not may_remove_permanently(f):raise ValueError('Fresh finding does not permit an official command')
        expected_action={} if item.get('method')=='trash' and f.action.get('kind')=='official-command' else f.action
        if (item.get('action') or {}) != expected_action:raise ValueError('Cleanup action changed or is not derived from current facts')
        self._fresh_finding=f
        return identity
    def apply(self,plan,*,permanent=False,execute_tools=False,progress=None):
        # Caches never survive a batch, including on an interrupted/failed apply.
        self._batch={}
        try:return self._apply(plan,permanent=permanent,execute_tools=execute_tools,progress=progress)
        finally:self._batch=None

    def _apply(self,plan,*,permanent=False,execute_tools=False,progress=None):
        def report(phase,completed,path=''):
            if progress:
                # Display failures must not alter a filesystem operation's outcome.
                try:progress({'phase':phase,'completed':completed,'total':len(plan['items']),'path':path})
                except Exception:pass
        report('verify',0)
        validate_plan(plan)
        entries=[]
        for item in plan['items']:
            report('verify',len(entries),item['path'])
            entry={'id':uuid.uuid4().hex,'plan':plan['id'],'path':item['path'],'group':item['group'],'sizeBytes':item['size'],'at':time.time(),'identity':item['identity'],'method':item.get('method','trash'),'status':'prepared',
                   'mode':plan.get('mode'),'version':soji_version(),'planCreatedAt':plan.get('createdAt'),'planVersion':plan.get('version'),
                   'rule':item.get('hint'),'policy':policy_record(item.get('finding') or {},plan.get('mode'),source='plan')}
            try:
                self._fresh_finding=None
                self.fresh(item,plan)
                if self._fresh_finding is not None:entry['policy']=policy_record(self._fresh_finding,plan['mode'],time.time())
                report('clean',len(entries),item['path'])
                action=item.get('action') or {}
                if action.get('kind') in ('simulator-device','simulator-runtime','document-version','official-command','git-worktree'):
                    if not execute_tools or not permanent:raise ValueError('Native tool cleanup requires --execute-tools and --permanent')
                    self.append(entry)
                    if action['kind']=='official-command':
                        from .commands import CommandPolicy,may_remove_permanently
                        if not may_remove_permanently(item['finding']):raise ValueError('Official command requires regenerable remove recommendation without holds')
                        entry['toolResult']=CommandPolicy().execute(action,item['path'],plan['home'])
                    else:self.tool_action(action)
                    entry['status']='done';entry['method']=action['kind']
                else:
                    want_permanent=item.get('method')=='permanent' or action.get('kind')=='empty-trash'
                    if want_permanent and not permanent:raise ValueError('Permanent cleanup requires --permanent')
                    if item.get('members'):
                        # One journal entry; sidecars first so a failure leaves
                        # the transcript itself in place.
                        entry['members']=[{'path':m['path'],'role':m.get('role',''),'identity':m['identity'],'sizeBytes':m['size'],'status':'prepared'} for m in item['members']]
                        self.append(entry)
                        order=list(range(1,len(entry['members'])))+[0]
                        for k,i in enumerate(order):
                            rec=entry['members'][i]
                            if not self.move(rec,f"{entry['id']}-{i}",entry,plan,want_permanent):
                                for j in order[k+1:]:entry['members'][j].update(status='skipped',error='Not attempted after an earlier member failed')
                                break
                        compound_status(entry)
                    else:self.move(entry,entry['id'],entry,plan,want_permanent)
                # The filesystem outcome is final here; a journal failure must not relabel it.
                self._journal_best_effort(entry)
            except Exception as e:
                kept=[r for r in [entry,*entry.get('members',[])] if r.get('rollback') not in (None,'restored')]
                entry['status']='failed'
                # Never drop the note that a refused rollback left a staged object behind.
                entry['error']=str(e) if not kept else f"{kept[0]['error']}; then {e}"
                self._journal_best_effort(entry)
            entries.append(entry)
            report('clean',len(entries),item['path'])
        report('done',len(entries))
        return {'entries':entries,'notice':TRASH_NOTICE if any(e.get('method')=='trash' and e['status'] in ('done','partial') for e in entries) else None,
                'completed':sum(e['status']=='done' for e in entries),
                'partial':sum(e['status']=='partial' for e in entries),
                'failed':sum(e['status']!='done' for e in entries),
                'journalError':next((e['journalError'] for e in entries if e.get('journalError')),None)}
    def system_trash(self,rec,entry,fd,name,original):
        """FileManager.trashItem via the native helper, bound to the verified identity."""
        from .platform import native
        rec['trashApi']='FileManager.trashItem';self.append(entry)
        again=os.stat(name,dir_fd=fd,follow_symlinks=False)
        if (again.st_dev,again.st_ino)!=(original.st_dev,original.st_ino):raise ValueError('Target changed before operation')
        result=native('trash',rec['path'])
        if not isinstance(result,dict) or not result.get('trashedTo'):
            raise ValueError('System Trash failed: '+str(result.get('error') if isinstance(result,dict) else result))
        rec['trashedTo']=result['trashedTo'];self.append(entry)
        trashed=file_identity(rec['trashedTo'])
        if (trashed['device'],trashed['inode'])!=(original.st_dev,original.st_ino):
            raise ValueError('Trashed item identity differs; inspect '+rec['trashedTo'])
        rec['trashedIdentity']=trashed;rec['method']='trash';rec['status']='done'
        return True
    def move(self,rec,tag,entry,plan,want_permanent):
        """Identity-bound Trash move or staged removal of rec['path'].

        Outcome is recorded on rec (the entry itself or one of its members);
        entry is journaled at each checkpoint. Returns True when done.
        """
        staged=None;fd=None;removal_started=False;moved=False
        try:
            fd=parent_fd(rec['path']);name=Path(rec['path']).name
            original=os.stat(name,dir_fd=fd,follow_symlinks=False)
            parent=os.fstat(fd);expected=rec['identity']
            current={'device':original.st_dev,'inode':original.st_ino,'type':stat.S_IFMT(original.st_mode),'parentDevice':parent.st_dev,'parentInode':parent.st_ino,'mtimeNs':original.st_mtime_ns,'ctimeNs':original.st_ctime_ns}
            if current!=expected:raise ValueError('Target or parent changed before operation')
            if want_permanent:
                from .platform import rename_exclusive
                staging='.soji-removing-'+tag;rec['stagedName']=staging;self.append(entry)
                # Exclusive: never replaces an existing name; unavailable means nothing moved.
                try:rename_exclusive(fd,name,fd,staging)
                except BaseException:rec.pop('stagedName',None);raise
                staged=staging
                staged_stat=os.stat(staged,dir_fd=fd,follow_symlinks=False)
                if staged_stat.st_ino!=original.st_ino:raise ValueError('Staged identity mismatch')
                rec.update(phase='removing',stagedPath=str(Path(rec['path']).parent/staged))
                self.append(entry);removal_started=True
                remove_at(fd,staged,(original.st_dev,original.st_ino));staged=None;rec['method']='permanent';rec['status']='done'
            else:
                trash=Path(self.trash_directory or Path(plan['home'])/'.Trash')
                trash.mkdir(mode=0o700,parents=True,exist_ok=True)
                if trash.is_symlink():raise ValueError('Trash cannot be a symlink')
                try:tfd=os.open(trash,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                except PermissionError:
                    # macOS privacy protection denies opening ~/.Trash without Full
                    # Disk Access; the system Trash API is still permitted.
                    if self.trash_directory:raise
                    try:self.system_trash(rec,entry,fd,name,original)
                    except Exception:
                        moved=bool(rec.get('trashedTo'));raise
                    return True
                try:
                    if os.fstat(tfd).st_dev!=original.st_dev:raise ValueError('Cross-volume Trash move needs native-volume support; no copy/delete fallback')
                    dest=name+'.soji-'+tag;rec['trashedTo']=str(trash/dest);self.append(entry)
                    os.rename(name,dest,src_dir_fd=fd,dst_dir_fd=tfd);moved=True
                    rec['trashedIdentity']=file_identity(trash/dest);rec['method']='trash';rec['status']='done'
                finally:os.close(tfd)
            return True
        except Exception as e:
            rec['status']='prepared' if moved else 'failed';rec['error']=str(e)
            if staged and fd is not None and not removal_started:
                self.rollback_staged(fd,staged,rec,entry,original)
            if removal_started:rec['partialDeletionPossible']=True
            return False
        finally:
            if fd is not None:os.close(fd)
    def rollback_staged(self,fd,staged,rec,entry,original):
        """Put a staged, not-yet-removed object back without replacing anything.

        Only an atomic no-replace rename is used. If the original name was
        recreated meanwhile, or the rename cannot be done exclusively, both
        objects are kept, the staged path is recorded (best-effort: the
        journal may be what failed) and rec['error'] says so.
        """
        from .platform import rename_exclusive,ExclusiveRenameUnavailable
        name=Path(rec['path']).name;staged_path=str(Path(rec['path']).parent/staged)
        rec['stagedPath']=staged_path
        other=False
        try:
            try:now=os.stat(staged,dir_fd=fd,follow_symlinks=False)
            except FileNotFoundError:
                rec.pop('stagedPath',None);rec['rollback']='missing';rec['phase']='rollback-missing'
                rec['error']=f"{rec.get('error')}; rollback impossible: staged object {staged_path} no longer exists"
                self._journal_best_effort(entry);return
            # A different object (e.g. an app's atomic save) may have been staged;
            # the exclusive rename cannot replace anything, so put it back too.
            other=(now.st_dev,now.st_ino)!=(original.st_dev,original.st_ino)
            rename_exclusive(fd,staged,fd,name)
            rec.pop('stagedPath',None);rec.pop('phase',None)
            if other:
                rec['rollback']='restored-other-identity'
                rec['error']=f"{rec.get('error')}; rollback restored a different object than the reviewed one to {rec['path']}; nothing was removed"
                self._journal_best_effort(entry)
            else:rec['rollback']='restored'
            return
        except FileExistsError:
            rec['rollback']='conflict';reason='original path was recreated meanwhile; both kept'
        except ExclusiveRenameUnavailable as x:
            rec['rollback']='unavailable';reason=f'no atomic no-replace rename ({x.strerror}); not restored'
        except OSError as x:
            if x.errno==errno.ENOTEMPTY:rec['rollback']='conflict';reason='original path was recreated meanwhile; both kept'
            else:rec['rollback']='failed';reason=f'rollback failed ({x.strerror or x})'
        rec['phase']='rollback-'+rec['rollback']
        if other:reason+=' (the staged object is not the reviewed one; it may be new user data)'
        rec['error']=f"{rec.get('error')}; rollback {rec['rollback']}: {reason}; staged object left at {staged_path}"
        self._journal_best_effort(entry)
    def _journal_best_effort(self,entry):
        """Append, recording rather than raising a journal failure on the entry."""
        try:self.append(entry);return True
        except Exception as x:
            entry['journalError']=f'Journal could not be written: {x}';return False
    def tool_action(self,action):
        if action['kind']=='git-worktree':
            from .gitstate import GitInspector
            state=GitInspector().inspect(action['path'],worktree=True)
            if not state.get('verified') or state.get('reason') or state.get('mainWorktree')!=action['repository']:raise ValueError('Worktree is no longer clean, merged and pushed')
            argv=['/usr/bin/git','-c','core.fsmonitor=false','-c','core.hooksPath=/dev/null','-C',action['repository'],'worktree','remove','--',action['path']]
        elif action['kind']=='simulator-device':argv=['/usr/bin/xcrun','simctl','delete',action['udid']]
        elif action['kind']=='simulator-runtime':argv=['/usr/bin/xcrun','simctl','runtime','delete',action['identifier']]
        elif action['kind']=='document-version':
            from .platform import native
            result=native('remove-version',action['document'],action['version'])
            if isinstance(result,dict) and result.get('removed'):return
            raise ValueError(str(result))
        else:raise ValueError('Unknown action')
        code,_,err=command(argv,timeout=120)
        if code:raise OSError(err)
    def entries(self):
        result={}
        if not self.journal.exists():return []
        with self.journal.open() as f:
            for line in f:
                try:e=json.loads(line);result[e['id']]=e
                except (ValueError,KeyError):continue
        return list(result.values())
    def report(self):
        """Journal entries annotated with whether undo can still work."""
        out=[]
        for e in self.entries():
            e=dict(e)
            if e.get('members'):
                e['members']=[{**m,'recovery':recoverability(m)} for m in e['members']]
                states={m['recovery'] for m in e['members'] if m['recovery']}
                e['recovery']=('unrecoverable (Trash emptied)' if 'unrecoverable (Trash emptied)' in states
                               else next(iter(states)) if len(states)==1 else ', '.join(sorted(states)) or None)
            else:e['recovery']=recoverability(e)
            e['recoverable']=e['recovery']=='recoverable while in Trash'
            out.append(e)
        return out
    def recover(self,apply=False):
        results=[]
        for e in self.entries():
            kept=[r for r in [e,*e.get('members',[])] if r.get('rollback') in ROLLBACK_KEPT]
            if kept:
                # Report only: a staged object kept by a refused rollback is never
                # renamed back or removed here; a person must compare both copies.
                results.append({'id':e['id'],'rollbackKept':[{'path':r['path'],'stagedPath':r.get('stagedPath'),'rollback':r['rollback']} for r in kept],
                                'status':'Rollback did not restore the staged object; it was kept beside the original path for manual review'})
                continue
            if e.get('partialDeletionPossible'):
                results.append({'id':e['id'],'partialDeletionPossible':True,'stagedPath':e.get('stagedPath'),'status':'Permanent removal interrupted; remaining staged data is not an intact undo copy'})
                continue
            if e.get('status')!='prepared':continue
            if e.get('members'):
                result={'id':e['id'],'compound':True,'applied':apply,'members':[]}
                for m in e['members']:
                    if m['status']!='prepared':result['members'].append({'path':m['path'],'status':m['status']});continue
                    candidate=m.get('trashedTo')
                    if candidate and os.path.lexists(candidate) and not os.path.lexists(m['path']):
                        current=file_identity(candidate)
                        if not all(current.get(k)==m['identity'].get(k) for k in ('device','inode','type')):
                            result['members'].append({'path':m['path'],'refused':'Recovery identity mismatch'});continue
                        result['members'].append({'path':m['path'],'recoverableTrashMove':True})
                        if apply:m.update(status='done',recovered=True,trashedIdentity=current,method='trash')
                    else:result['members'].append({'path':m['path'],'status':'Operation outcome uncertain; inspect recorded path/stagedName before taking action'})
                if apply:compound_status(e);self.append(e)
                result['status']=e['status'];results.append(result);continue
            candidate=e.get('trashedTo')
            if candidate and os.path.lexists(candidate) and not os.path.lexists(e['path']):
                current=file_identity(candidate);expected=e.get('identity',{})
                matches=all(current.get(k)==expected.get(k) for k in ('device','inode','type'))
                if not matches:results.append({'id':e['id'],'refused':'Recovery identity mismatch'});continue
                result={'id':e['id'],'recoverableTrashMove':True,'applied':apply}
                if apply:
                    e.update(status='done',recovered=True,trashedIdentity=current);self.append(e)
                results.append(result)
            else:results.append({'id':e['id'],'status':'Operation outcome uncertain; inspect recorded path/stagedName before taking action'})
        return results
    def undo(self,entry_id):
        e=next((e for e in self.entries() if e['id']==entry_id),None)
        if e and e.get('members') and e.get('status') in ('done','partial'):
            todo=[m for m in e['members'] if m['status']=='done' and m.get('method')=='trash']
            if not todo:raise ValueError('Only completed Trash moves can be restored')
            # Transcript (index 0) first, then sidecars: reverse of cleanup order.
            for m in todo:
                try:self.restore(m)
                except Exception as exc:
                    m['restoreError']=str(exc);e['restoreError']=f'Restore incomplete at {m["path"]}: {exc}';self.append(e)
                    raise ValueError(e['restoreError']) from exc
                m.update(status='restored',restoredAt=time.time());self.append(e)
            if all(m['status'] in ('restored','failed','skipped') for m in e['members']):e['status']='restored'
            e['restoredAt']=time.time();self.append(e);return e
        if not e or e.get('status')!='done' or e.get('method')!='trash':raise ValueError('Only completed Trash moves can be restored')
        self.restore(e)
        e.update(status='restored',restoredAt=time.time());self.append(e);return e
    def restore(self,e):
        source=e['trashedTo'];dest=e['path']
        if not os.path.lexists(source):raise ValueError('Unrecoverable (Trash emptied): '+source+' no longer exists')
        # macOS stamps Trash items with xattrs (com.apple.macl), bumping ctime only.
        def same(current):
            want=dict(e.get('trashedIdentity') or {});current=dict(current)
            want.pop('ctimeNs',None);current.pop('ctimeNs',None)
            return bool(want) and current==want
        if os.path.lexists(dest):raise ValueError('Original destination exists; refusing overwrite')
        if not same(file_identity(source)):raise ValueError('Trashed item changed')
        # ~/.Trash itself may not be openable (macOS privacy protection); then
        # address the source by absolute path while keeping the destination fd.
        try:sfd=parent_fd(source);sname=Path(source).name
        except PermissionError:sfd=None;sname=source
        dfd=parent_fd(dest)
        try:
            parent=os.fstat(dfd);expected=e['identity']
            if (parent.st_dev,parent.st_ino)!=(expected.get('parentDevice'),expected.get('parentInode')):
                raise ValueError('Original parent changed; refusing restore')
            if not same(file_identity(source)):raise ValueError('Trashed item changed before restore')
            # Reserve the destination atomically; macOS renameatx_np offers
            # RENAME_EXCL, used rather than a check-then-overwrite rename.
            import ctypes
            libc=ctypes.CDLL(None,use_errno=True)
            if hasattr(libc,'renameatx_np'):
                AT_FDCWD=-2
                if libc.renameatx_np(AT_FDCWD if sfd is None else sfd,os.fsencode(sname),dfd,os.fsencode(Path(dest).name),4)!=0:raise OSError(ctypes.get_errno(),'Exclusive restore failed')
            else:raise ValueError('Exclusive directory restore requires macOS renameatx_np')
        finally:
            if sfd is not None:os.close(sfd)
            os.close(dfd)
