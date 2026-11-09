import os,sys,tempfile,subprocess,time,json
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace as NS
sys.path.insert(0,'/Users/pierrelouis/Documents/Github/soji')
from soji_cli.engine import Scanner
from soji_cli.cleanup import Cleaner,create_plan
from soji_cli.gitstate import GitInspector
from soji_cli.apps import AppCatalog,InstalledTools
from soji_cli.activity import ActivityIndex

def empty_context(s): s.processes=[];s.open_paths=[];s.context_warnings=[]
with tempfile.TemporaryDirectory(prefix='soji-independent-audit-') as tmp:
 home=Path(tmp).resolve()/'home';home.mkdir();state=Path(tmp)/'state'
 def file(rel,text='fixture'):
  p=home/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p
 def age_tree(p,days):
  for root,dirs,files in os.walk(p,topdown=False):
   for name in files+dirs:os.utime(Path(root)/name,(time.time()-days*86400,)*2)
   os.utime(root,(time.time()-days*86400,)*2)
 # Avoid birth time recency for this fixture only, by representing historical
 # node timestamps after the real filesystem walk. Identity checks remain real.
 original_visit=Scanner.visit
 def historical_visit(s,*a,**kw):
  n=original_visit(s,*a,**kw);n.newest=n.own_newest=os.lstat(n.path).st_mtime;return n
 scopes=[patch.object(Scanner,'collect_context',empty_context),patch.object(Scanner,'visit',historical_visit),patch.object(AppCatalog,'build',lambda s:s),patch.object(InstalledTools,'build',lambda s:s),patch.object(ActivityIndex,'build',lambda s:s),patch('soji_cli.platform.native',return_value=[])]
 for scope in scopes:scope.start()
 try:
  for version,days in [('v18.20.0',180),('v22.0.0',120),('v24.0.0',90)]:
   file('.nvm/versions/node/'+version+'/bin/node');age_tree(home/'.nvm/versions/node'/version,days)
  marker=file('.nvm/alias/default','lts/*')
  file('.nvm/alias/lts/hydrogen','v18.20.0')
  file('.nvm/alias/lts/*','lts/hydrogen')
  s=Scanner([str(home)],home=str(home),min_bytes=0);s.run()
  old=next(f for f in s.decisions('aggressive') if f.path==str(home/'.nvm/versions/node/v18.20.0'))
  print('DEFAULT_ALIAS',json.dumps({'selected':old.selected,'holds':old.holds,'decision':old.decision,'scanError':s.error}))
  # A new project pin appears after a plan was reviewed.
  marker.write_text('24');s=Scanner([str(home)],home=str(home),min_bytes=0);s.run()
  plan=create_plan(s,'aggressive',paths={str(home/'.nvm/versions/node/v18.20.0')})
  file('project/.nvmrc','18.20.0')
  current=Scanner([str(home)],home=str(home),min_bytes=0);current.run()
  now=next(f for f in current.decisions('aggressive') if f.path==str(home/'.nvm/versions/node/v18.20.0'))
  fresh=Cleaner(state)
  try:fresh.fresh(plan['items'][0],plan);fresh_result='ACCEPTED'
  except Exception as e:fresh_result=str(e)
  print('NEW_PIN',json.dumps({'fullScanSelected':now.selected,'fullScanHolds':now.holds,'freshPlanCheck':fresh_result}))
 finally:
  for scope in reversed(scopes):scope.stop()
 # Real Git operations, local disposable repository and local bare remote only.
 repo=home/'repo';repo.mkdir()
 def git(*a):return subprocess.run(['/usr/bin/git','-c','core.hooksPath=/dev/null','-C',str(repo),*a],check=True,capture_output=True,text=True)
 git('init','-b','main');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture');git('config','commit.gpgsign','false')
 (repo/'.gitignore').write_text('local-data/\n');(repo/'source').write_text('fixture');git('add','.');git('commit','-m','fixture')
 remote=Path(tmp)/'remote.git';subprocess.run(['/usr/bin/git','init','--bare',str(remote)],check=True,capture_output=True)
 git('remote','add','origin',str(remote));git('push','-u','origin','main');work=home/'.codex/worktrees/audit';work.parent.mkdir(parents=True);git('worktree','add','--detach',str(work))
 personal=work/'local-data/irreplaceable.txt';personal.parent.mkdir();personal.write_text('Only copy of personal work')
 age_tree(work,30)
 for scope in scopes:scope.start()
 try:
  full=Scanner([str(home)],home=str(home),min_bytes=0);full.run()
  print('WORKTREE_SCANNER',json.dumps({'error':full.error,'modes':{m:[{'path':f.path,'selected':f.selected,'holds':f.holds,'action':f.action} for f in full.decisions(m) if f.path==str(work)] for m in ('careful','balanced','aggressive')}}))
 finally:
  for scope in reversed(scopes):scope.stop()
 inspected=GitInspector().inspect(str(work),worktree=True)
 Cleaner(state).tool_action({'kind':'git-worktree','repository':str(repo),'path':str(work)})
 print('IGNORED_WORKTREE',json.dumps({'guardResult':inspected,'uniqueFileSurvives':personal.exists(),'worktreeSurvives':work.exists()}))
