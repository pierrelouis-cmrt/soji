"""Permanent-path rollback must never replace an object recreated at the original path.

Disposable tempdir fixtures only: fake home, separate state, injected journal
failure. No real cleanup, Trash or home path is touched.
"""
import errno
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from soji_cli import platform
from soji_cli.cleanup import Cleaner,digest,file_identity

Unavailable=getattr(platform,'ExclusiveRenameUnavailable',OSError)


class PermanentRollbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='soji-rollback-');self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name).resolve();self.state=self.home/'state'
        self.cleaner=Cleaner(self.state,context=False,trash_directory=self.home/'trash')
        (self.home/'cache').mkdir()

    def plan(self,path):
        item={'path':str(path),'identity':file_identity(path),'size':7,'files':1,'newest':0,'group':'Caches','method':'permanent','action':{},'finding':{}}
        p={'format':'soji-clean-plan/1','id':'fixture','createdAt':time.time(),'home':str(self.home),'roots':[str(self.home)],'items':[item]}
        p['digest']=digest(p);return p

    def apply_failing_at_removing(self,target,recreate):
        """Journal fails once, at the phase=removing checkpoint; meanwhile an app recreates target."""
        plan=self.plan(target);real=self.cleaner.append;fired=[]
        def append(e):
            if e.get('phase')=='removing' and not fired:
                fired.append(1)
                if recreate:recreate()
                raise OSError('injected journal write failure')
            real(e)
        with patch.object(self.cleaner,'append',side_effect=append),\
             patch.object(self.cleaner,'fresh',return_value=plan['items'][0]['identity']),\
             patch('soji_cli.cleanup.remove_at',side_effect=AssertionError('removal must not start')):
            result=self.cleaner.apply(plan,permanent=True)
        return result['entries'][0]

    def staged(self,entry):return Path(entry['stagedPath'])

    def assert_kept(self,entry,kind):
        self.assertEqual(entry['status'],'failed');self.assertEqual(entry['rollback'],kind)
        self.assertNotEqual(entry['rollback'],'restored');self.assertNotIn('partialDeletionPossible',entry)
        self.assertIn('rollback '+kind,entry['error']);self.assertIn(entry['stagedPath'],entry['error'])
        journaled=next(e for e in self.cleaner.entries() if e['id']==entry['id'])
        self.assertEqual(journaled['rollback'],kind);self.assertEqual(journaled['stagedPath'],entry['stagedPath'])
        before=sorted(os.listdir(self.home/'cache'))
        for apply in (False,True):
            recovered=next(r for r in self.cleaner.recover(apply=apply) if r['id']==entry['id'])
            self.assertEqual(recovered['rollbackKept'][0]['stagedPath'],entry['stagedPath'])
        self.assertEqual(sorted(os.listdir(self.home/'cache')),before)

    def test_file_conflict_keeps_both(self):
        target=self.home/'cache'/'blob';target.write_text('old disposable cache')
        e=self.apply_failing_at_removing(target,lambda:target.write_text('NEW UNIQUE USER DATA'))
        self.assertEqual(target.read_text(),'NEW UNIQUE USER DATA')
        self.assertEqual(self.staged(e).read_text(),'old disposable cache')
        self.assert_kept(e,'conflict')

    def test_nonempty_directory_conflict_keeps_both(self):
        target=self.home/'cache'/'dir';target.mkdir();(target/'old').write_text('old cache')
        def recreate():target.mkdir();(target/'new').write_text('NEW UNIQUE USER DATA')
        e=self.apply_failing_at_removing(target,recreate)
        self.assertEqual(os.listdir(target),['new']);self.assertEqual((target/'new').read_text(),'NEW UNIQUE USER DATA')
        self.assertEqual((self.staged(e)/'old').read_text(),'old cache')
        self.assert_kept(e,'conflict')

    def test_empty_directory_conflict_keeps_both(self):
        # A plain rename(2) silently replaces an empty directory.
        target=self.home/'cache'/'dir';target.mkdir();(target/'old').write_text('old cache')
        e=self.apply_failing_at_removing(target,target.mkdir)
        self.assertTrue(target.is_dir());self.assertEqual(os.listdir(target),[])
        self.assertEqual((self.staged(e)/'old').read_text(),'old cache')
        self.assert_kept(e,'conflict')

    def test_rollback_without_conflict_restores(self):
        target=self.home/'cache'/'dir';target.mkdir();(target/'old').write_text('old cache')
        ident=file_identity(target)
        e=self.apply_failing_at_removing(target,None)
        self.assertEqual(e['status'],'failed');self.assertEqual(e.get('rollback','restored'),'restored')
        self.assertEqual((target/'old').read_text(),'old cache')
        self.assertEqual(file_identity(target)['inode'],ident['inode'])
        self.assertEqual([n for n in os.listdir(self.home/'cache') if n.startswith('.soji-removing-')],[])

    def test_rollback_rename_error_keeps_staged_and_reports(self):
        target=self.home/'cache'/'blob';target.write_text('old disposable cache')
        with patch('soji_cli.platform.rename_exclusive',create=True,side_effect=OSError(errno.EIO,'Input/output error')):
            e=self.apply_failing_at_removing(target,None)
        self.assertFalse(os.path.lexists(target))
        self.assertEqual(self.staged(e).read_text(),'old disposable cache')
        self.assert_kept(e,'failed')

    def test_no_exclusive_primitive_means_no_fallback(self):
        target=self.home/'cache'/'blob';target.write_text('old disposable cache')
        real_rename,armed=os.rename,[]
        def rename(*a,**k):
            if armed:raise AssertionError('replacing rename fallback used')
            return real_rename(*a,**k)
        with patch('soji_cli.platform.rename_exclusive',create=True,side_effect=Unavailable(errno.ENOTSUP,'unsupported')),\
             patch('os.rename',side_effect=rename),\
             patch('os.replace',side_effect=AssertionError('replacing rename fallback used')):
            e=self.apply_failing_at_removing(target,lambda:armed.append(1))
        self.assertFalse(os.path.lexists(target))
        self.assertEqual(self.staged(e).read_text(),'old disposable cache')
        self.assert_kept(e,'unavailable')


class ExclusiveRenameTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='soji-renamex-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY)
        self.addCleanup(os.close,self.fd)

    def rename(self,a,b):platform.rename_exclusive(self.fd,a,self.fd,b)

    def test_refuses_every_existing_destination(self):
        for make in (lambda p:p.write_text('new'),lambda p:p.mkdir(),lambda p:(p.mkdir(),(p/'x').write_text('new'))):
            with self.subTest(make=make):
                src=self.root/'src';dst=self.root/'dst';src.mkdir();(src/'old').write_text('old');make(dst)
                with self.assertRaises(OSError) as ctx:self.rename('src','dst')
                self.assertIn(ctx.exception.errno,(errno.EEXIST,errno.ENOTEMPTY))
                self.assertEqual((src/'old').read_text(),'old');self.assertTrue(os.path.lexists(dst))
                for p in (src,dst):
                    if p.is_dir():
                        for c in p.iterdir():c.unlink()
                        p.rmdir()
                    else:p.unlink()

    def test_renames_file_and_directory_when_free(self):
        (self.root/'f').write_text('f');(self.root/'d').mkdir()
        self.rename('f','f2');self.rename('d','d2')
        self.assertEqual((self.root/'f2').read_text(),'f');self.assertTrue((self.root/'d2').is_dir())
        self.assertFalse(os.path.lexists(self.root/'f'));self.assertFalse(os.path.lexists(self.root/'d'))


if __name__=='__main__':unittest.main()
