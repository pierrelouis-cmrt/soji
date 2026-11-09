"""Local Git checks: dirty, locked, merged, pushed, stash and worktree identity."""
from pathlib import Path
import os
import re
import stat
import time
from .util import command

# Ignored entries `git worktree remove` would delete that are positively known to
# be regenerable tool output. Anything else ignored (databases, notebooks,
# exports, `.env`, build/dist/target/.venv folders that may hold release
# artifacts or hand-installed packages) holds the worktree. Names match only the
# reported entry itself, never an ancestor, so `local-data/` is not excused by a
# `node_modules` inside it. A folder is excused only when it is itself ignored
# (`ls-files --directory` also collapses an unignored folder whose files all
# match other patterns), it is a real folder, and a bounded walk that never
# follows symlinks finds no nested Git repository and only the expected files.
GENERIC_DIRS=frozenset({'node_modules'})
DISPOSABLE_IGNORED_DIRS=GENERIC_DIRS|{'__pycache__','.pytest_cache','.mypy_cache','.ruff_cache'}
DISPOSABLE_IGNORED_FILES=frozenset({'.DS_Store'})
DISPOSABLE_IGNORED_SUFFIXES=('.pyc','.pyo')
INVENTORY_LIMIT=15_000_000
WALK_ENTRIES=500_000
WALK_SECONDS=20

def disposable_ignored(entry):
    """Whether one ignored entry's name is a regenerable kind (walk still required for folders)."""
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
    if any(not e or e.startswith('/') or '\n' in e or e in ('.','..') or '/../' in '/'+e or e.endswith('/..') for e in entries):return None
    return entries

def _allowed(kind,rel,is_dir):
    """Whether a path inside a cache folder of `kind` has the expected shape."""
    parts=rel.split('/')
    if kind in GENERIC_DIRS:return True
    if kind=='__pycache__':return not is_dir and len(parts)==1 and parts[0].endswith(('.pyc','.pyo'))
    top=parts[0]
    if kind=='.pytest_cache':
        if len(parts)==1:return (is_dir and top=='v') or (not is_dir and top in ('README.md','.gitignore','CACHEDIR.TAG'))
        return parts==['v','cache'] if is_dir else len(parts)==3 and parts[:2]==['v','cache'] and parts[2] in ('nodeids','lastfailed','stepwise')
    if kind=='.mypy_cache':
        version=re.fullmatch(r'\d+\.\d+',top)
        if len(parts)==1:return bool(version) if is_dir else top in ('.gitignore','CACHEDIR.TAG','missing_stubs')
        return bool(version) and (is_dir or parts[-1].endswith('.json') or parts[-1] in ('cache.db','cache.db-wal','cache.db-shm'))
    if kind=='.ruff_cache':
        version=re.fullmatch(r'\d+(\.\d+)*',top)
        if len(parts)==1:return bool(version) if is_dir else top in ('.gitignore','CACHEDIR.TAG')
        return bool(version) and len(parts)==2 and not is_dir
    return False

def walk_disposable(folder,kind,budget):
    """('ok'|'keep'|'unknown', detail) for one ignored cache folder; never follows symlinks."""
    try:
        st=os.lstat(folder)
        if not stat.S_ISDIR(st.st_mode):return 'keep','not a real folder'
        stack=[(folder,'')]
        while stack:
            if time.monotonic()>budget['deadline']:return 'unknown','too large to verify'
            current,prefix=stack.pop()
            with os.scandir(current) as it:
                for entry in it:
                    budget['entries']-=1
                    if budget['entries']<0 or time.monotonic()>budget['deadline']:return 'unknown','too large to verify'
                    rel=prefix+entry.name
                    if entry.name.lower()=='.git':return 'keep','nested Git repository'
                    mode=entry.stat(follow_symlinks=False).st_mode
                    is_dir=stat.S_ISDIR(mode)
                    if not (is_dir or stat.S_ISREG(mode) or stat.S_ISLNK(mode)):return 'keep','unexpected file type'
                    if entry.is_symlink() and kind not in GENERIC_DIRS:return 'keep','unexpected symlink'
                    if not _allowed(kind,rel,is_dir):return 'keep','unexpected content'
                    if is_dir:stack.append((entry.path,rel+'/'))
        return 'ok',''
    except OSError as e:return 'unknown',f'unreadable ({e.strerror or e})'

def tracked_flags(out,root):
    """Reason when `ls-files -v -z` shows edits Git status cannot see; None when clean; False when unparseable."""
    if len(out)>=INVENTORY_LIMIT or (out and not out.endswith('\0')):return False
    for item in out[:-1].split('\0') if out else []:
        if len(item)<3 or item[1]!=' ' or ignored_inventory(item[2:]+'\0') is None:return False
        tag,name=item[0],item[2:]
        if tag.islower():return 'Worktree has assume-unchanged files whose edits Git cannot see: '+name
        if tag=='S':
            try:os.lstat(os.path.join(root,name))
            except FileNotFoundError:continue
            except OSError:return False
            return 'Worktree has skip-worktree files present on disk: '+name
        elif tag!='H':return f'Worktree index entry is not plainly tracked ({tag}): '+name
    return None

def git_env():
    """Process environment without inherited GIT_* variables (GIT_DIR, GIT_WORK_TREE,
    GIT_INDEX_FILE, GIT_CONFIG_* ...), which could point Git at another repository,
    index or configuration. Global/system config is disabled explicitly."""
    env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_OPTIONAL_LOCKS='0',GIT_TERMINAL_PROMPT='0',GIT_NO_LAZY_FETCH='1',GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1')
    return env

class GitInspector:
    def __init__(self):self.cache={}
    def inspect(self,path,worktree=False):
        key=(path,worktree)
        if key in self.cache:return self.cache[key]
        env=git_env()
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
            # `git worktree remove` deletes ignored files and hidden edits without
            # asking, and Git cleanliness says nothing about them. Inventory them
            # from the worktree root; anything not positively disposable, or any
            # doubt about the inventory, holds the worktree.
            result['contentsVerified']=False;result['ignored']=None
            hold,unknown=self._contents(git,root,path,result)
            if unknown:result.update(verified=False,reason=result['reason'] or unknown)
            elif hold:result['reason']=result['reason'] or hold
            elif result['verified'] and not result['reason']:result['contentsVerified']=True
        self.cache[key]=result;return result
    def _contents(self,git,root,path,result):
        """(hold reason, unverified reason) for content `git worktree remove` would delete."""
        if os.path.realpath(root)!=os.path.realpath(path):return None,'Path is not the worktree root'
        code,out,_=git('config','--type=bool','--get','core.ignoreStat',cwd=root)
        if code not in (0,1):return None,'Worktree configuration cannot be read'
        if code==0 and out.strip() not in ('true','false'):return None,'Worktree configuration cannot be read'
        if code==0 and out.strip()=='true':return 'Worktree uses core.ignoreStat; local edits may be invisible',None
        code,out,_=git('ls-files','-v','-z',timeout=20,cwd=root)
        flags=False if code else tracked_flags(out,root)
        if flags is False:return None,'Tracked files in worktree cannot be inventoried'
        if flags:return flags,None
        code,out,_=git('ls-files','-z','--others','--ignored','--exclude-standard','--directory','--no-empty-directory',timeout=20,cwd=root)
        entries=None if code else ignored_inventory(out)
        if entries is None:return None,'Ignored files in worktree cannot be inventoried'
        result['ignored']=entries[:50];result['ignoredCount']=len(entries)
        keep=[e for e in entries if not disposable_ignored(e)]
        folders=[e for e in entries if e.endswith('/') and disposable_ignored(e)]
        # A cache-named folder counts only when that folder itself is ignored.
        ignored=set()
        for folder in folders:
            code,_,_=git('check-ignore','--no-index','-q','--',folder,timeout=20,cwd=root)
            if code not in (0,1):return None,'Ignore rules for worktree folders cannot be checked'
            if code==0:ignored.add(folder)
        keep+=[e+' (not itself ignored)' for e in folders if e not in ignored]
        budget={'entries':WALK_ENTRIES,'deadline':time.monotonic()+WALK_SECONDS}
        for e in folders:
            if e not in ignored:continue
            status,detail=walk_disposable(os.path.join(root,e.rstrip('/')),e.rstrip('/').rsplit('/',1)[-1],budget)
            if status=='unknown':return None,f'Ignored folder {e} cannot be verified: {detail}'
            if status=='keep':keep.append(f'{e} ({detail})')
        if keep:
            sample=', '.join(keep[:3])+(f' (+{len(keep)-3} more)' if len(keep)>3 else '')
            return 'Worktree has ignored files that are not known to be disposable: '+sample,None
        return None,None
