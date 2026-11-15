"""Apply per-item judgments (agent verdicts or cached ones) to scan findings.

A judgment can supply idle levels, a recommendation and a category for an
unmatched row. It never lifts a hold, never selects personal or review-only
data, and never overrides a specialized integrity rule.
"""
from __future__ import annotations
import os
from pathlib import Path


def apply_judgments(scanner,findings):
    from .models import SESSION_HINTS
    bypath={f.path:f for f in scanner.findings}
    for data in findings:
        path=os.path.realpath(data['path'])
        if not any(path==r or path.startswith(r.rstrip('/')+'/') for r in scanner.roots):continue
        f=bypath.get(path)
        node=scanner.nodes.get(path)
        catalog_unit=f is not None and f.managed and f.hint_id in SESSION_HINTS
        if node is not None and not catalog_unit and (f is None or f.size!=node.size or f.files!=node.files):
            if f is not None:scanner.findings=[old for old in scanner.findings if old is not f]
            f=scanner.classify(node);scanner.findings.append(f);bypath[path]=f
        if f is None:continue
        levels=data.get('levels')
        if isinstance(levels,dict):
            numeric={k:v for k,v in levels.items() if k in ('careful','balanced','aggressive')}
            # A more permissive mode must not become stricter accidentally.
            for stricter,looser in [('careful','balanced'),('balanced','aggressive')]:
                if stricter in numeric:numeric[looser]=min(numeric.get(looser,numeric[stricter]),numeric[stricter])
            f.levels={**numeric,'reason':levels.get('reason','Agent judgment')}
        if not f.hint_id:
            f.group=data.get('group',f.group);f.label=data.get('title',f.label)
        if not f.hint_id and data.get('regenerable') and data.get('recommendation')=='remove':
            parts={p.casefold() for p in Path(path).parts}
            cache=bool(parts & {'caches','cache','tmp','.cache'})
            marker=Path(path)/'CACHEDIR.TAG'
            try:
                if marker.is_file() and not marker.is_symlink():
                    with marker.open('rb') as m:cache |= m.read(43).startswith(b'Signature: 8a477f597d28d172789f06886806bc55')
            except OSError:pass
            if cache:f.tier='regenerable';f.list_only=False;f.comes_back=data.get('comesBack','rebuilds')
            else:f.holds.append('Unknown agent-nominated data lacks deterministic cache evidence')
        f.source='both' if f.hint_id else 'agent';f.recommendation=data.get('recommendation','review');f.confidence=data.get('confidence')
        f.evidence.append({'check':'agent','judgment':data})
        # AI may nominate unknown folders but cannot override any local hold,
        # personal-data tier, reviewOnly policy, or specialized integrity rule.
        # cleanCommand is evidence only; the plan uses bound native actions.
    # Prevent double-counting/cleaning a newly split child and its old parent.
    nominated={os.path.realpath(d['path']) for d in findings}
    scanner.findings=[f for f in scanner.findings if not any(p!=f.path and p.startswith(f.path.rstrip('/')+'/') for p in nominated) and not (f.path not in nominated and any(f.path.startswith(p.rstrip('/')+'/') for p in nominated))]
