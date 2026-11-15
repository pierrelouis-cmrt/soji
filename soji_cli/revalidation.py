"""Target-scoped fresh Python measurements owned by the scanner boundary."""
import dataclasses
import os
from pathlib import Path
import time
from .util import inside
from .safety import SafetyRefusal

@dataclasses.dataclass
class RevalidationContext:
    enabled: bool = True
    cache: dict = dataclasses.field(default_factory=dict)

    def collect_context(self,scan):
        """Share live snapshots for at most one second, only within one apply call.

        Target contents and identities are never cached. Inventory snapshots have
        a separate five-second lifetime; new batches always start from scratch.
        """
        batch=self.cache
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
        scan.writer_ids=locks


@dataclasses.dataclass(frozen=True)
class TargetSpec:
    item: dict
    plan: dict

@dataclasses.dataclass(frozen=True)
class TargetRefusal:
    code: str | None
    text: str
    observed_at: float
    error: Exception

@dataclasses.dataclass
class RevalidatedTarget:
    scanner: object
    finding: object
    measurement: object
    members: tuple
    policy: object
    refusals: tuple = ()

    def require(self):
        if self.refusals:raise self.refusals[0].error
        return self

def revalidate_target(spec, context):
    try:return _revalidate(spec.item,spec.plan,context)
    except (ValueError,OSError) as error:
        observed=getattr(error,'at',None) or time.time()
        refusal=TargetRefusal(getattr(error,'code',None),str(error),observed,error)
        return RevalidatedTarget(None,None,None,(),None,(refusal,))

def _revalidate(item, plan, context):
    from .catalogs import measure_catalog_target
    from .engine import Scanner
    path=item['path']
    members=item.get('members')
    batch=context.cache
    scan=Scanner([path],home=plan['home'],protected=plan.get('protected',[]),min_bytes=0,context=context.enabled,max_seconds=120,max_files=1000000,inherit_hint=item.get('hint') or None,catalog=batch.get('catalog'),pin_roots=plan['roots'],live_pins=True,walk_backend='python')
    # Policy dependencies (project pins) span the plan's whole scope, not
    # this target-scoped walk: rediscover them live on every check, so a
    # pin created after the plan holds the item. Incomplete discovery holds.

    if batch is not None:
        batch['catalog']=scan.catalog
        # Marker listings are mutable filesystem facts, not catalog rules.
        scan.catalog.forget_filesystem_facts()
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
        context=pool.submit(context.collect_context,scan)
        if item.get('hint') in ('claude-sessions','codex-sessions','trash-item') and measure_root!=path:
            measure_catalog_target(scan,path,measure_root,item['hint'])
        else:scan.visit(measure_root)
        context.result()
    n=scan.nodes.get(path)
    if n is None:raise ValueError('Fresh target could not be measured')
    if scan.limited:raise ValueError('Fresh verification incomplete, protected, or contains secrets')
    for m in members or [{'path':path,'size':item['size'],'newest':item['newest'],'files':item['files']}]:
        mn=scan.nodes.get(m['path'])
        if mn is None:raise ValueError('Fresh target could not be measured')
        if mn.errors or mn.skipped or mn.secret:raise ValueError('Fresh verification incomplete, protected, or contains secrets')
        if mn.size!=m['size'] or mn.newest!=m['newest'] or mn.files!=m['files']:raise SafetyRefusal('Contents changed since analysis'+(': '+m['path'] if members else ''),'contents-changed')
    if item.get('hint') in ('claude-sessions','codex-sessions','trash-item') and measure_root!=path:
        # Re-derive the catalog row (FindingPart policy, compound members)
        # from its catalog root, not from a bare file.
        scan.roots=[measure_root]
    if batch is not None and time.monotonic()-batch.get('inventory_at',float('-inf'))<5:
        inventories=batch['inventories']
    else:inventories=None
    inventory_started=time.monotonic()
    scan._build_findings(inventories)
    if batch is not None and inventories is None:
        batch.update(inventory_at=inventory_started,inventories=(scan.activity,scan.apps,scan.tools))
    f=next((f for f in scan.findings if f.path==path),None)
    if members is not None:
        now_members=[(m['path'],m['identity']) for m in (f.members if f else [])]
        if now_members!=[(m['path'],m['identity']) for m in members]:raise SafetyRefusal('Session members changed since analysis','members-changed')
    elif f is not None and f.members:raise ValueError('Target became a compound session; generate a new plan')
    if f is None:
        if item.get('hint') in ('claude-sessions','codex-sessions','trash-item'):raise ValueError('Session or Trash catalog membership changed since analysis')
        f=scan.classify(n)
    permit=plan.get('routinePermit')
    if permit:
        from .routine_policy import item_allowed
        if not item_allowed(f,permit,time.time()):raise ValueError('Routine conditions no longer hold')
    original=item['finding']
    if original.get('source') in ('agent','both'):
        judgment=next((e.get('judgment') for e in reversed(original.get('evidence',[])) if e.get('check')=='agent'),None)
        if not isinstance(judgment,dict):raise ValueError('Agent judgment cannot be revalidated')
        from .judgments import apply_judgments
        if not any(candidate is f for candidate in scan.findings):scan.findings.append(f)
        apply_judgments(scan,[judgment])
        f=next(candidate for candidate in scan.findings if candidate.path==path)
    outcome=f.policy(plan['mode'],time.time())
    selected,reason=outcome.pair()
    if not selected:
        code=outcome.code
        if code:raise SafetyRefusal('Fresh guards refuse: '+reason,code)
        raise ValueError('Fresh guards refuse: '+reason)
    if f.action.get('kind')=='official-command' and item.get('method')!='trash':
        from .commands import may_remove_permanently
        if not may_remove_permanently(f):raise ValueError('Fresh finding does not permit an official command')
    expected_action={} if item.get('method')=='trash' and f.action.get('kind')=='official-command' else f.action
    if (item.get('action') or {}) != expected_action:raise ValueError('Cleanup action changed or is not derived from current facts')
    from .policy import Measurement
    return RevalidatedTarget(scan,f,Measurement.of(f),tuple(f.members),outcome)

