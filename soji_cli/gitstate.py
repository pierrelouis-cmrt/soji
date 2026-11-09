"""Local Git checks: dirty, locked, merged, pushed, stash and worktree identity."""
from pathlib import Path
import os
from .util import command

# Ignored entries `git worktree remove` would delete that are positively known to
# be regenerable tool output. Anything else ignored (databases, notebooks,
# exports, `.env`, build/dist folders that may hold release artifacts) holds the
# worktree. Directory names match only the reported entry itself, never an
# ancestor, so `local-data/` is not excused by a `node_modules` inside it.
DISPOSABLE_IGNORED_DIRS=frozenset({'node_modules','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache'})
DISPOSABLE_IGNORED_FILES=frozenset({'.DS_Store'})
DISPOSABLE_IGNORED_SUFFIXES=('.pyc','.pyo')
INVENTORY_LIMIT=15_000_000

def disposable_ignored(entry):
    """Whether one `git ls-files --directory` ignored entry is regenerable."""
    if entry.endswith('/'):
        name=entry.rstrip('/').rsplit('/',1)[-1]
        return name in DISPOSABLE_IGNORED_DIRS
    name=entry.rsplit('/',1)[-1]
    return name in DISPOSABLE_IGNORED_FILES or name.endswith(DISPOSABLE_IGNORED_SUFFIXES)

def ignored_inventory(out):
    """Parse NUL-separated `ls-files -z` output; None when it cannot be trusted."""
    if len(out)>=INVENTORY_LIMIT:return None  # possibly truncated by command()
    if not out:return []
    if not out.endswith('\0'):return None
    entries=out[:-1].split('\0')
    if any(not e or e.startswith('/') or '\n' in e or e in ('.','..') or '/../' in '/'+e for e in entries):return None
    return entries

class GitInspector:
    def __init__(self):self.cache={}
    def inspect(self,path,worktree=False):
        key=(path,worktree)
        if key in self.cache:return self.cache[key]
        env=dict(os.environ,GIT_OPTIONAL_LOCKS='0',GIT_TERMINAL_PROMPT='0',GIT_NO_LAZY_FETCH='1')
        def git(*args,timeout=4,cwd=path):return command(['/usr/bin/git','-c','core.fsmonitor=false','-c','core.hooksPath=/dev/null','-C',cwd,*args],timeout=timeout,env=env)
        code,root,_=git('rev-parse','--show-toplevel')
        if code:return {'repository':False,'verified':not worktree,'reason':'Not a Git working tree' if worktree else ''}
        root=root.strip();result={'repository':True,'root':root,'verified':True,'dirty':False,'locked':False,'unmerged':None,'unpushed':None,'reason':''}
        code,out,_=git('status','--porcelain','--untracked-files=normal')
        if code:result.update(verified=False,reason='Git status unavailable')
        else:result['dirty']=bool(out.strip())
        code,gd,_=git('rev-parse','--git-dir')
        if code:
            result.update(verified=False,reason='Git directory unavailable')
        gd=Path(gd.strip());gd=gd if gd.is_absolute() else Path(path)/gd
        result['locked']=(gd/'locked').exists() or (gd/'index.lock').exists()
        if result['dirty']:result['reason']='Uncommitted or untracked work'
        elif result['locked']:result['reason']='Locked Git worktree'
        if worktree:
            # Query the shared main worktree: a detached agent worktree must not
            # count its own branch as evidence that its commits exist elsewhere.
            code,listing,_=git('worktree','list','--porcelain')
            main=next((l[9:] for l in listing.splitlines() if l.startswith('worktree ')),None)
            default=None
            code,branch,_=git('symbolic-ref','--short','refs/remotes/origin/HEAD')
            if not code and branch.strip():default=branch.strip()
            else:
                for branch in ('main','master','trunk','develop'):
                    if git('show-ref','--verify','--quiet','refs/heads/'+branch)[0]==0:
                        default=branch;break
            result['defaultBranch']=default
            if default is None:result.update(verified=False,reason=result['reason'] or 'Default branch cannot be confirmed')
            else:
                merged=git('merge-base','--is-ancestor','HEAD',default)[0]
                if merged not in (0,1):result.update(verified=False,reason=result['reason'] or 'Merge state cannot be confirmed')
                else:
                    result['unmerged']=merged==1
                    if result['unmerged']:result['reason']=result['reason'] or 'Worktree has unmerged commits'
            code,remaining,_=git('rev-list','--count','HEAD','--not','--remotes')
            if code:result.update(verified=False,reason=result['reason'] or 'Push state cannot be confirmed')
            else:
                result['unpushed']=int(remaining.strip() or 0)>0
                if result['unpushed']:result['reason']=result['reason'] or 'Worktree has unpushed commits'
            # A worktree with a stash may hold otherwise unique changes.
            if git('rev-parse','--verify','refs/stash')[0]==0:result['reason']=result['reason'] or 'Repository has stashed work'
            result['mainWorktree']=main
            # `git worktree remove` deletes ignored files without asking, and
            # Git cleanliness says nothing about them. Inventory them from the
            # worktree root; any entry not positively disposable, or any doubt
            # about the inventory, holds the worktree.
            result['contentsVerified']=False;result['ignored']=None
            if os.path.realpath(root)!=os.path.realpath(path):
                result.update(verified=False,reason=result['reason'] or 'Path is not the worktree root')
            else:
                code,out,_=git('ls-files','-z','--others','--ignored','--exclude-standard','--directory','--no-empty-directory',timeout=20,cwd=root)
                entries=None if code else ignored_inventory(out)
                if entries is None:
                    result.update(verified=False,reason=result['reason'] or 'Ignored files in worktree cannot be inventoried')
                else:
                    keep=[e for e in entries if not disposable_ignored(e)]
                    result['ignored']=entries[:50];result['ignoredCount']=len(entries)
                    if keep:
                        sample=', '.join(keep[:3])+(f' (+{len(keep)-3} more)' if len(keep)>3 else '')
                        result['reason']=result['reason'] or 'Worktree has ignored files that are not known to be disposable: '+sample
                    elif result['verified'] and not result['reason']:result['contentsVerified']=True
        self.cache[key]=result;return result
