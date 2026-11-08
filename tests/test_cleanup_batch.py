"""Batch speed and safety regressions, exclusively in disposable homes."""
import collections
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from corpus import hermetic
from soji_cli.cleanup import Cleaner, create_plan, digest, validate_plan
from soji_cli.engine import Scanner
from soji_cli.activity import ActivityIndex


class BatchCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name).resolve();self.home=base/'home';self.state=base/'state'
        self.root=self.home/'.codex/sessions';self.root.mkdir(parents=True)
        self.ctx=hermetic(str(self.home));self.ctx.__enter__();self.addCleanup(self.ctx.__exit__,None,None,None)
        for i in range(12):
            p=self.root/f'2020/01/01/rollout-{i}.jsonl';p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text('{}\n');os.utime(p,(time.time()-30*86400,)*2)
        self.cleaner=Cleaner(self.state,trash_directory=base/'trash')

    def plan(self):
        scan=Scanner([str(self.home)],home=str(self.home),min_bytes=0);scan.run()
        plan=create_plan(scan,'careful')
        self.assertEqual(len(plan['items']),12)
        return plan

    def test_each_session_measured_once_and_inventories_shared(self):
        plan=self.plan();visits=[];original=Scanner.visit;build=ActivityIndex.build
        def visit(scan,path,*args,**kwargs):
            visits.append(path);return original(scan,path,*args,**kwargs)
        events=[]
        # A fixed clock isolates operation counts from machine speed.
        with patch('soji_cli.cleanup.time.monotonic',return_value=100),patch.object(Scanner,'visit',visit),patch.object(ActivityIndex,'build',autospec=True,side_effect=build) as inventory,patch.object(Scanner,'collect_context',autospec=True) as context:
            result=self.cleaner.apply(plan,progress=events.append)
        self.assertEqual(result['completed'],12,result)
        self.assertEqual(collections.Counter(visits),collections.Counter(i['path'] for i in plan['items']))
        self.assertEqual(inventory.call_count,1);self.assertEqual(context.call_count,1)
        self.assertIsNone(self.cleaner._batch)
        self.assertEqual(events[-1],{'phase':'done','completed':12,'total':12,'path':''})
        self.assertEqual([e['completed'] for e in events if e['phase']=='clean' and e['completed']>0][-1],12)

    def test_later_target_changed_during_batch_is_refused(self):
        plan=self.plan();victim=Path(plan['items'][1]['path']);changed=False
        def progress(event):
            nonlocal changed
            if event['completed']==1 and not changed:
                victim.write_text('changed after first move');changed=True
        result=self.cleaner.apply(plan,progress=progress)
        self.assertEqual(result['completed'],11);self.assertEqual(result['failed'],1)
        self.assertTrue(victim.exists());self.assertIn('changed',result['entries'][1]['error'])

    def test_snapshots_refresh_and_caches_do_not_cross_batches(self):
        plan=self.plan();clock=[100.0];build=ActivityIndex.build
        def progress(event):
            if event['phase']=='clean':clock[0]+=6
        with patch('soji_cli.cleanup.time.monotonic',side_effect=lambda:clock[0]),patch.object(ActivityIndex,'build',autospec=True,side_effect=build) as inventory,patch.object(Scanner,'collect_context',autospec=True) as context:
            self.cleaner.apply(plan,progress=progress)
        self.assertEqual(inventory.call_count,12);self.assertEqual(context.call_count,12)
        self.assertIsNone(self.cleaner._batch)

    def test_live_open_file_refresh_refuses_later_target(self):
        plan=self.plan();victim=plan['items'][1]['path'];clock=[100.0]
        def collect(scan):
            scan.open_paths=[victim] if clock[0]>100 else []
        def progress(event):
            if event['completed']==1:clock[0]=102
        with patch('soji_cli.cleanup.time.monotonic',side_effect=lambda:clock[0]),patch.object(Scanner,'collect_context',collect):
            result=self.cleaner.apply(plan,progress=progress)
        self.assertEqual(result['failed'],1);self.assertTrue(Path(victim).exists())
        self.assertIn('File open',result['entries'][1]['error'])

    def test_writer_lock_is_still_checked(self):
        plan=self.plan();item=plan['items'][0]
        with patch('soji_cli.catalogs.codex_writer_ids',return_value={Path(item['path']).stem}):
            result=self.cleaner.apply(plan)
        self.assertEqual(result['failed'],1);self.assertTrue(Path(item['path']).exists())
        self.assertIn('writer lock',result['entries'][0]['error'])

    def test_progress_callback_failure_cannot_change_outcome(self):
        def broken(event):raise RuntimeError('display unavailable')
        result=self.cleaner.apply(self.plan(),progress=broken)
        self.assertEqual(result['completed'],12)

    def test_overlap_detection_includes_interleaved_sibling_names(self):
        plan=self.plan();first=plan['items'][0]
        plan['items']=[dict(first,path=str(self.root/'a')),dict(first,path=str(self.root/'a-b')),dict(first,path=str(self.root/'a/child'))]
        plan.pop('digest');plan['digest']=digest(plan)
        with self.assertRaisesRegex(ValueError,'Overlapping'):validate_plan(plan)

    def test_membership_cannot_fall_back_to_plain_file(self):
        plan=self.plan()
        with patch('soji_cli.catalogs.expand_catalogs',return_value=[]):
            result=self.cleaner.apply(plan)
        self.assertEqual(result['failed'],12)
        self.assertTrue(all(Path(i['path']).exists() for i in plan['items']))


if __name__=='__main__':unittest.main()
