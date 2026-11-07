"""Reviewed plans, fresh guard checks, identity-bound moves, journal and undo.
The analysis process never deletes. Only explicit `clean PLAN --apply` mutates
candidate data. No backend or license circumvention is involved.
"""
from __future__ import annotations
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import stat
import time
import uuid
from .util import atomic_json,inside,command


def file_identity(path):
    p=Path(path);s=os.lstat(p);parent=os.stat(p.parent,follow_symlinks=False)
    return {'device':s.st_dev,'inode':s.st_ino,'type':stat.S_IFMT(s.st_mode),'parentDevice':parent.st_dev,'parentInode':parent.st_ino,'mtimeNs':s.st_mtime_ns,'ctimeNs':s.st_ctime_ns}


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def create_plan(scanner,mode,paths=None,method='trash'):
    selected=[f for f in scanner.decisions(mode) if f.selected and (paths is None or f.path in paths)]
    items=[]
    for f in selected:
        if not f.identity:continue
        items.append({'path':f.path,'identity':f.identity,'size':f.size,'newest':f.newest,'files':f.files,'hint':f.hint_id,'group':f.group,'action':({} if method=='trash' and f.action.get('kind')=='official-command' else f.action),'method':method,'finding':dataclasses.asdict(f)})
    value={'format':'soji-clean-plan/1','id':uuid.uuid4().hex,'createdAt':time.time(),'mode':mode,'roots':scanner.roots,'home':scanner.home,'protected':scanner.protected,'items':items,'method':method,'warnings':['Review paths before applying. Trash is reversible while its item exists; permanent cleanup is not.']}
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
    paths=list(by_path)
    if any(a!=b and inside(a,b) for a in paths for b in paths):raise ValueError('Overlapping cleanup targets')
    return plan


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

class Cleaner:
    def __init__(self,state,*,context=True,trash_directory=None):
        self.state=Path(state).expanduser().resolve();self.state.mkdir(parents=True,exist_ok=True)
        self.journal=self.state/'journal.jsonl';self.context=context;self.trash_directory=trash_directory
    def append(self,entry):
        fd=os.open(self.journal,os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(fd,'a') as f:f.write(json.dumps(entry)+'\n');f.flush();os.fsync(f.fileno())
        except BaseException:raise
    def fresh(self,item,plan):
        from .engine import Scanner
        path=item['path']
        if not any(inside(path,r) for r in plan['roots']):raise ValueError('Outside scan roots')
        if path in plan['roots']:raise ValueError('Refusing a scan root itself')
        uninstall_action=(item.get('action') or {}).get('kind')=='uninstall'
        native_action=(item.get('action') or {}).get('kind') in ('document-version','simulator-runtime')
        if not inside(path,plan['home']) and not native_action and not uninstall_action:raise ValueError('System/outside-home filesystem cleanup is not enabled')
        if inside(path,str(self.state)):raise ValueError('Cannot clean own state')
        if any(inside(path,p) or inside(p,path) for p in plan.get('protected',[])):raise ValueError('Protected path overlap')
        identity=file_identity(path)
        if identity!=item['identity']:raise ValueError('File or parent identity changed since analysis')
        if uninstall_action:
            from .uninstall import verify_uninstall
            verify_uninstall(item,plan['home']);return identity
        if native_action:
            from .nativeplans import verify_native
            verify_native(item)
            return identity
        scan=Scanner([path],home=plan['home'],protected=plan.get('protected',[]),min_bytes=0,context=self.context,max_seconds=120,max_files=1000000,inherit_hint=item.get('hint') or None)
        measure_root=path
        if item.get('finding',{}).get('rule',{}).get('projectUntouchedDays'):
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
        scan.started=time.monotonic();scan.collect_context();scan.visit(measure_root);n=scan.nodes.get(path)
        if n is None:raise ValueError('Fresh target could not be measured')
        if scan.limited or n.errors or n.skipped or n.secret:raise ValueError('Fresh verification incomplete, protected, or contains secrets')
        if n.size!=item['size'] or n.newest!=item['newest'] or n.files!=item['files']:raise ValueError('Contents changed since analysis')
        scan._build_findings()
        f=next((f for f in scan.findings if f.path==path),None)
        if f is None:f=scan.classify(n)
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
        return identity
    def apply(self,plan,*,permanent=False,execute_tools=False):
        validate_plan(plan)
        entries=[]
        for item in plan['items']:
            entry={'id':uuid.uuid4().hex,'plan':plan['id'],'path':item['path'],'group':item['group'],'sizeBytes':item['size'],'at':time.time(),'identity':item['identity'],'method':item.get('method','trash'),'status':'prepared'}
            staged=None;fd=None;removal_started=False;moved=False
            try:
                self.fresh(item,plan)
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
                    fd=parent_fd(item['path']);name=Path(item['path']).name
                    original=os.stat(name,dir_fd=fd,follow_symlinks=False)
                    parent=os.fstat(fd);expected=item['identity']
                    current={'device':original.st_dev,'inode':original.st_ino,'type':stat.S_IFMT(original.st_mode),'parentDevice':parent.st_dev,'parentInode':parent.st_ino,'mtimeNs':original.st_mtime_ns,'ctimeNs':original.st_ctime_ns}
                    if current!=expected:raise ValueError('Target or parent changed before operation')
                    if want_permanent:
                        staged='.soji-removing-'+entry['id'];entry['stagedName']=staged;self.append(entry)
                        os.rename(name,staged,src_dir_fd=fd,dst_dir_fd=fd)
                        staged_stat=os.stat(staged,dir_fd=fd,follow_symlinks=False)
                        if staged_stat.st_ino!=original.st_ino:raise ValueError('Staged identity mismatch')
                        entry.update(phase='removing',stagedPath=str(Path(item['path']).parent/staged))
                        self.append(entry);removal_started=True
                        remove_at(fd,staged,(original.st_dev,original.st_ino));staged=None;entry['method']='permanent';entry['status']='done'
                    else:
                        trash=Path(self.trash_directory or Path(plan['home'])/'.Trash')
                        trash.mkdir(mode=0o700,parents=True,exist_ok=True)
                        if trash.is_symlink():raise ValueError('Trash cannot be a symlink')
                        tfd=os.open(trash,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                        try:
                            if os.fstat(tfd).st_dev!=original.st_dev:raise ValueError('Cross-volume Trash move needs native-volume support; no copy/delete fallback')
                            dest=name+'.soji-'+entry['id'];entry['trashedTo']=str(trash/dest);self.append(entry)
                            os.rename(name,dest,src_dir_fd=fd,dst_dir_fd=tfd);moved=True
                            entry['trashedIdentity']=file_identity(trash/dest);entry['method']='trash';entry['status']='done'
                        finally:os.close(tfd)
                self.append(entry)
            except Exception as e:
                if staged and fd is not None and not removal_started:
                    try:os.rename(staged,Path(item['path']).name,src_dir_fd=fd,dst_dir_fd=fd)
                    except OSError:pass
                entry['status']='prepared' if moved else 'failed';entry['error']=str(e)
                if removal_started:entry['partialDeletionPossible']=True
                self.append(entry)
            finally:
                if fd is not None:os.close(fd)
            entries.append(entry)
        return {'entries':entries,'completed':sum(e['status']=='done' for e in entries),'failed':sum(e['status']!='done' for e in entries)}
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
    def recover(self,apply=False):
        results=[]
        for e in self.entries():
            if e.get('partialDeletionPossible'):
                results.append({'id':e['id'],'partialDeletionPossible':True,'stagedPath':e.get('stagedPath'),'status':'Permanent removal interrupted; remaining staged data is not an intact undo copy'})
                continue
            if e.get('status')!='prepared':continue
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
        if not e or e.get('status')!='done' or e.get('method')!='trash':raise ValueError('Only completed Trash moves can be restored')
        source=e['trashedTo'];dest=e['path']
        if os.path.lexists(dest):raise ValueError('Original destination exists; refusing overwrite')
        if file_identity(source)!=e.get('trashedIdentity'):raise ValueError('Trashed item changed')
        sfd=parent_fd(source);dfd=parent_fd(dest)
        try:
            parent=os.fstat(dfd);expected=e['identity']
            if (parent.st_dev,parent.st_ino)!=(expected.get('parentDevice'),expected.get('parentInode')):
                raise ValueError('Original parent changed; refusing restore')
            if file_identity(source)!=e.get('trashedIdentity'):raise ValueError('Trashed item changed before restore')
            # Reserve the destination atomically; macOS renameatx_np offers
            # RENAME_EXCL, used rather than a check-then-overwrite rename.
            import ctypes
            libc=ctypes.CDLL(None,use_errno=True)
            if hasattr(libc,'renameatx_np'):
                if libc.renameatx_np(sfd,os.fsencode(Path(source).name),dfd,os.fsencode(Path(dest).name),4)!=0:raise OSError(ctypes.get_errno(),'Exclusive restore failed')
            else:raise ValueError('Exclusive directory restore requires macOS renameatx_np')
        finally:os.close(sfd);os.close(dfd)
        e.update(status='restored',restoredAt=time.time());self.append(e);return e
