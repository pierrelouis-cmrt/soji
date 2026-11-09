"""Shared safety boundaries for planning, execution and presentation."""
from pathlib import Path

class SafetyRefusal(ValueError):
    """A refusal whose policy code and original clock survive journal retries."""
    def __init__(self,message,code='active-use',at=None):
        super().__init__(message);self.code=code;self.at=at


HIGH_RISK_GROUPS=frozenset(('Toolchains and SDKs','Project dependencies','Editor extensions',
                           'Build output','Agent and editor history','Agent worktrees'))
STAGED_PREFIX='.soji-removing-'


def staged_ancestor(path):
    p=Path(path)
    return next((str(a) for a in (p,*p.parents) if a.name.startswith(STAGED_PREFIX)),None)


WORKTREE_DISABLED='Agent worktree cleanup disabled: unique ignored data and concurrent writes cannot be preserved'


def agent_worktree_boundary(path, home, catalog=None):
    """Recognized agent roots and descendants, including actionless old plans."""
    from .engine import Catalog
    catalog = catalog or Catalog(home)
    for parent in (Path(path), *Path(path).parents):
        if str(parent) == home:break
        match = catalog.match(str(parent))
        if match and match[0]['group'] == 'Agent worktrees':return str(parent)
    return None
