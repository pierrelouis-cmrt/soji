"""Disposable fixtures and mocked tool boundaries; never invokes cleanup services."""
import dataclasses
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from soji_cli.cleanup import Cleaner,digest,file_identity,validate_plan,remove_at
from soji_cli.commands import CommandPolicy,may_remove_permanently
from soji_cli.engine import Finding
from soji_cli.nativeplans import verify_native,runtimes_plan
from soji_cli.routines import auto_clean_plan,idle_enough
from soji_cli.uninstall import attributed_paths

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='soji-recovery-');self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name).resolve();self.state=self.home/'state';self.trash=self.home/'trash'
        self.cleaner=Cleaner(self.state,context=False,trash_directory=self.trash)
    def file(self,name='cache/data'):
        p=self.home/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture');return p
    def plan(self,path,method='trash'):
        item={'path':str(path),'identity':file_identity(path),'size':7,'files':1,'newest':0,'group':'Caches','method':method,'action':{},'finding':{}}
        p={'format':'soji-clean-plan/1','id':'fixture','createdAt':time.time(),'home':str(self.home),'roots':[str(self.home)],'items':[item]};p['digest']=digest(p);return p
    def apply(self,p,**kwargs):
        with patch.object(self.cleaner,'fresh',return_value=p['items'][0]['identity']):return self.cleaner.apply(p,**kwargs)
    def test_trash_move_is_reversible(self):
        target=self.file();result=self.apply(self.plan(target));entry=result['entries'][0]
        self.assertEqual(result['completed'],1);self.assertFalse(target.exists())
        self.cleaner.undo(entry['id']);self.assertEqual(target.read_text(),'fixture')
    def test_permanent_requires_explicit_flag(self):
        target=self.file();result=self.apply(self.plan(target,'permanent'))
        self.assertEqual(result['failed'],1);self.assertTrue(target.exists())
    def test_partial_permanent_failure_keeps_staged_remains(self):
        target=self.file();plan=self.plan(target.parent,'permanent')
        def partial(fd,name,expected):
            child=os.open(name,os.O_RDONLY|os.O_DIRECTORY,dir_fd=fd)
            try:os.unlink('data',dir_fd=child)
            finally:os.close(child)
            raise OSError('injected after first deletion')
        with patch('soji_cli.cleanup.remove_at',side_effect=partial):result=self.apply(plan,permanent=True)
        e=result['entries'][0];self.assertTrue(e['partialDeletionPossible']);self.assertFalse(target.parent.exists())
        self.assertTrue(Path(e['stagedPath']).exists());self.assertTrue(self.cleaner.recover()[0]['partialDeletionPossible'])
    def test_move_followed_by_metadata_failure_stays_recoverable(self):
        target=self.file();plan=self.plan(target)
        with patch('soji_cli.cleanup.file_identity',side_effect=OSError('metadata interrupted')):result=self.apply(plan)
        self.assertEqual(result['failed'],1);self.assertEqual(result['entries'][0]['status'],'prepared')
        self.assertTrue(self.cleaner.recover(apply=True)[0]['applied'])
        self.cleaner.undo(result['entries'][0]['id']);self.assertTrue(target.exists())
    def test_undo_refuses_replaced_parent(self):
        target=self.file();entry=self.apply(self.plan(target))['entries'][0]
        target.parent.rename(self.home/'old-cache');target.parent.mkdir()
        with self.assertRaisesRegex(ValueError,'parent changed'):self.cleaner.undo(entry['id'])
        self.assertTrue(Path(entry['trashedTo']).exists())
    def test_descriptor_checks_parent_after_fresh_check(self):
        target=self.file();p=self.plan(target);p['items'][0]['identity']['parentInode']+=1;p.pop('digest');p['digest']=digest(p)
        result=self.apply(p);self.assertEqual(result['failed'],1);self.assertTrue(target.exists())
    def test_recovery_refuses_wrong_identity(self):
        target=self.file();e={'id':'crash','path':str(target),'identity':file_identity(target),'status':'prepared','method':'trash','trashedTo':str(self.file('other'))}
        target.unlink();self.cleaner.append(e);self.assertIn('refused',self.cleaner.recover(apply=True)[0])
    def test_symlink_recursive_removal_preserves_external_target(self):
        external=self.file('outside/keep');folder=self.home/'remove';folder.mkdir();(folder/'link').symlink_to(external)
        fd=os.open(self.home,os.O_RDONLY|os.O_DIRECTORY)
        try:remove_at(fd,'remove')
        finally:os.close(fd)
        self.assertTrue(external.exists());self.assertFalse(folder.exists())
    def test_recursive_removal_refuses_other_device(self):
        target=self.file();fd=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:
            with self.assertRaisesRegex(ValueError,'mount boundary'):remove_at(fd,target.name,device=target.stat().st_dev+1)
        finally:os.close(fd)
        self.assertTrue(target.exists())
    def test_tool_action_requires_both_explicit_flags(self):
        target=self.file();plan=self.plan(target,'permanent');plan['items'][0]['action']={'kind':'simulator-runtime','identifier':'fixture'}
        plan.pop('digest');plan['digest']=digest(plan)
        with patch.object(self.cleaner,'tool_action',side_effect=AssertionError('must not invoke tool')):
            for flags in ({},{'permanent':True},{'execute_tools':True}):
                self.assertEqual(self.apply(plan,**flags)['failed'],1)
        self.assertTrue(target.exists())
    def test_duplicate_filesystem_actions_refused_but_version_units_allowed(self):
        p=self.plan(self.file());other=dict(p['items'][0],action={'kind':'empty-trash'});p['items'].append(other);p.pop('digest');p['digest']=digest(p)
        with self.assertRaisesRegex(ValueError,'Duplicate plan paths'):validate_plan(p)
        for index,item in enumerate(p['items']):item['action']={'kind':'document-version','document':item['path'],'version':str(index)}
        p.pop('digest');p['digest']=digest(p);validate_plan(p)
    def test_uninstall_revalidates_app_identity_for_leftovers(self):
        from soji_cli.apps import AppCatalog
        from soji_cli.uninstall import verify_uninstall
        app_path=self.home/'Applications/Fixture.app';app_path.mkdir(parents=True)
        leftover=self.file('Library/Caches/org.fixture.App/data').parent
        app={'path':str(app_path),'bundle':'org.fixture.App','name':'Fixture','version':'1'}
        item={'path':str(leftover),'action':{'app':app,'appIdentity':file_identity(app_path)}}
        def build(cat):cat.apps=[dict(app)];cat.running=[];cat.running_available=True;return cat
        # Hermetic: the fake app is unsigned and no codesign/pkgutil process runs.
        with patch.object(AppCatalog,'build',build),patch('soji_cli.apps.command',return_value=(1,'','not signed')):
            verify_uninstall(item,str(self.home))
            app_path.rename(app_path.with_suffix('.old'));app_path.mkdir()
            with self.assertRaisesRegex(ValueError,'identity changed'):verify_uninstall(item,str(self.home))
    def test_attribution_rejects_path_components(self):
        for name in ('..','../../Caches',''):
            with self.assertRaises(ValueError):attributed_paths({'bundle':'org.fixture.App','name':name},str(self.home))
    def test_attribution_does_not_follow_library_symlink(self):
        outside=self.home/'outside';(outside/'Caches/org.fixture.App').mkdir(parents=True);(self.home/'Library').symlink_to(outside)
        self.assertEqual(attributed_paths({'bundle':'org.fixture.App','name':'App'},str(self.home)),[])

class PolicyTests(unittest.TestCase):
    def test_permanent_gate_truth_table(self):
        base={'tier':'regenerable','recommendation':'remove','comes_back':'rebuilds','holds':[]}
        self.assertTrue(may_remove_permanently(base))
        self.assertTrue(may_remove_permanently(dict(base,comes_back='downloads')))
        for field,value in [('tier','costly'),('recommendation','trash'),('comes_back','gone'),('holds',['busy'])]:
            self.assertFalse(may_remove_permanently(dict(base,**{field:value})))
    def test_command_cannot_borrow_unrelated_hint(self):
        home=str(Path.home());action={'hint':'npm-cache','argv':['npm','cache','clean','--force']}
        with patch('soji_cli.commands.shutil.which',return_value='/fake/npm'),patch('soji_cli.commands.command',return_value=(0,home+'/unrelated','')):
            with self.assertRaisesRegex(ValueError,'hint does not match'):CommandPolicy().bound(action,home+'/unrelated/_cacache',home)
    def test_document_catalog_failure_refuses(self):
        item={'path':'/fixture/doc','action':{'kind':'document-version','document':'/fixture/doc','version':'old','versionModified':1}}
        for failure in (None,[],{'error':'service unavailable'}):
            with patch('soji_cli.nativeplans.document_versions',return_value=failure):
                with self.assertRaisesRegex(ValueError,'catalog unavailable'):verify_native(item)
    def test_document_changed_or_retained_version_refuses(self):
        item={'path':'/fixture/doc','action':{'kind':'document-version','document':'/fixture/doc','version':'old','versionModified':1}}
        for version in ({'url':'old','modified':2,'retained':False},{'url':'old','modified':1,'retained':True}):
            with patch('soji_cli.nativeplans.document_versions',return_value={'versions':[version]}):
                with self.assertRaisesRegex(ValueError,'no longer removable'):verify_native(item)
    def test_document_action_cannot_remove_other_document(self):
        item={'path':'/fixture/doc','action':{'kind':'document-version','document':'/fixture/other','version':'old','versionModified':1}}
        with patch('soji_cli.nativeplans.document_versions',return_value={'versions':[]}):
            with self.assertRaisesRegex(ValueError,'does not match'):verify_native(item)
    def test_explicit_empty_runtime_snapshot_never_falls_back_to_live(self):
        with patch('soji_cli.nativeplans.runtime_catalog',side_effect=AssertionError('live query')):
            with self.assertRaisesRegex(ValueError,'unavailable'):runtimes_plan('/fixture',{})
    def test_idle_boundary_and_missing_date(self):
        self.assertFalse(idle_enough(None,1,7200));self.assertFalse(idle_enough(3601,1,7200));self.assertTrue(idle_enough(3600,1,7200))
    def test_auto_plan_has_minimum_and_fresh_permit(self):
        f=Finding('/fixture/cache',100,100,1,1,'Caches','Cache',tier='regenerable',comes_back='rebuilds',selected=True,identity={'inode':1},recommendation='remove')
        class Scanner:
            home='/fixture';roots=['/fixture'];protected=[]
            def decisions(self,mode):return [f]
        with patch('soji_cli.routines.shutil.disk_usage',return_value=type('Usage',(),{'free':1,'total':100})()):
            result=auto_clean_plan(Scanner(),{'enabled':True,'minGainBytes':0,'minItemBytes':50})
        p=result['plan'];self.assertEqual(len(p['items']),1);self.assertEqual(p['routinePermit']['minItemBytes'],50);validate_plan(p)

if __name__=='__main__':unittest.main()


class SystemTrashFallback(unittest.TestCase):
    """~/.Trash cannot be opened under macOS privacy protection: use the system API."""
    def setUp(self):
        import tempfile
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name).resolve()
        self.home=self.base/'home';(self.home/'.Trash').mkdir(parents=True)
        self.target=self.home/'cache';self.target.mkdir();(self.target/'blob').write_bytes(b'x'*4096)
    def tearDown(self):self.temp.cleanup()
    def run_move(self,native_result):
        from soji_cli.cleanup import Cleaner,file_identity
        cleaner=Cleaner(self.base/'state')
        rec={'path':str(self.target),'identity':file_identity(self.target),'status':'prepared'}
        entry=dict(rec,id='e1')
        real_open=os.open
        def deny(path,*a,**k):
            if str(path).endswith('.Trash'):raise PermissionError(1,'Operation not permitted',str(path))
            return real_open(path,*a,**k)
        def fake_native(op,path):
            dest=self.home/'.Trash'/'cache';os.rename(path,dest)
            return native_result(dest)
        with patch('os.open',side_effect=deny),patch('soji_cli.platform.native',side_effect=fake_native):
            ok=cleaner.move(rec,'t',entry,{'home':str(self.home)},False)
        return ok,rec
    def test_fallback_moves_and_records_identity(self):
        ok,rec=self.run_move(lambda dest:{'trashedTo':str(dest)})
        self.assertTrue(ok);self.assertEqual(rec['status'],'done');self.assertEqual(rec['trashApi'],'FileManager.trashItem')
        self.assertEqual(rec['trashedIdentity']['inode'],rec['identity']['inode'])
        self.assertTrue((self.home/'.Trash/cache/blob').exists())
    def test_helper_error_is_failure_and_nothing_claimed(self):
        ok,rec=self.run_move(lambda dest:(os.rename(dest,self.target),{'error':'denied'})[1])
        self.assertFalse(ok);self.assertEqual(rec['status'],'failed');self.assertIn('System Trash failed',rec['error'])
