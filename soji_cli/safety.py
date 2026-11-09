"""Shared safety boundaries for planning, execution and presentation."""
from pathlib import Path

HIGH_RISK_GROUPS=frozenset(('Toolchains and SDKs','Project dependencies','Editor extensions',
                           'Build output','Agent and editor history','Agent worktrees'))
STAGED_PREFIX='.soji-removing-'


def staged_ancestor(path):
    p=Path(path)
    return next((str(a) for a in (p,*p.parents) if a.name.startswith(STAGED_PREFIX)),None)
