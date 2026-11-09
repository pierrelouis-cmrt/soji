import sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,'/Users/pierrelouis/Documents/Github/soji')
from soji_cli.cleanup import Cleaner,file_identity
with tempfile.TemporaryDirectory(prefix='soji-rollback-audit-') as tmp:
 root=Path(tmp).resolve();target=root/'cache.bin';target.write_text('old disposable cache');cleaner=Cleaner(root/'state');entry={'id':'rollback-fixture','path':str(target),'identity':file_identity(target),'status':'prepared'}
 original_append=cleaner.append
 def fail_during_stage(e):
  if e.get('phase')=='removing':
   target.write_text('NEW UNIQUE USER DATA')
   raise OSError('injected journal write failure')
  original_append(e)
 with patch.object(cleaner,'append',side_effect=fail_during_stage):
  result=cleaner.move(entry,entry['id'],entry,{'home':str(root)},True)
 print({'operationSucceeded':result,'error':entry.get('error'),'originalPathContents':target.read_text(),'newUniqueDataSurvives':target.read_text()=='NEW UNIQUE USER DATA','stagedCopyExists':(root/('.soji-removing-'+entry['id'])).exists()})
