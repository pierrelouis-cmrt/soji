"""Disposable fake-home regressions; all external inventories are mocked."""
import dataclasses
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from corpus import hermetic
from test_nov8_regressions import write, age_tree
from soji_cli import engine, tui
from soji_cli.ai import AIAnalyzer
from soji_cli.cleanup import Cleaner, create_plan, file_identity, policy_record, recoverability, HIGH_RISK_GROUPS
from soji_cli.engine import Finding, Scanner, MODES


class JournalSafety(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='soji-journal-fixture-');self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve();self.home=self.base/'home';self.home.mkdir()
        self.cleaner=Cleaner(self.base/'state',trash_directory=self.base/'trash')
        self.target=self.home/'.npm/_npx'
        write(self.target/'abc/blob',age=40);age_tree(self.home,40)
        self.fixture=hermetic(str(self.home));self.fixture.__enter__();self.addCleanup(self.fixture.__exit__,None,None,None)

    def scan(self,roots=None):
        s=Scanner([str(p) for p in (roots or [self.home])],home=str(self.home),min_bytes=1)
        s.run();self.assertFalse(s.error);return s

    def plan(self):return create_plan(self.scan(),'balanced',paths={str(self.target)})

    def move(self):
        result=self.cleaner.apply(self.plan());self.assertEqual(result['completed'],1,result)
        return result['entries'][0]

    def refusal(self,path,**kw):
        self.cleaner.append(dict(id='refusal',path=str(path),status='failed',at=time.time()-60,**kw))

    def test_agent_audit_preserves_reason_and_provenance(self):
        target=self.home/'.cache/unknown-cache';write(target/'blob',age=40);age_tree(self.home,40)
        scan=self.scan();judgment={'path':str(target),'title':'Cache','group':'App caches','regenerable':True,'recommendation':'remove','confidence':.97,'reason':'Verified generated payload','comesBack':'rebuilds'}
        AIAnalyzer(self.base/'state').apply(scan,[judgment])
        plan=create_plan(scan,'balanced',paths={str(target)})
        self.assertEqual(len(plan['items']),1)
        result=self.cleaner.apply(plan);self.assertEqual(result['completed'],1,result)
        p=result['entries'][0]['policy']
        self.assertEqual(p['source'],'fresh');self.assertEqual(p['findingSource'],'agent')
        self.assertEqual(p['reason'],judgment['reason']);self.assertEqual(p['agentJudgment'],judgment)
        self.assertEqual(p['recommendation'],'remove');self.assertEqual(p['confidence'],.97)
        self.assertEqual(result['entries'][0]['planPolicy']['source'],'plan')
        # The serialized planned policy also carries provenance.
        self.assertEqual(policy_record(plan['items'][0]['finding'],'balanced',source='plan')['agentJudgment'],judgment)

    def test_legacy_journal_not_enriched(self):
        self.cleaner.append({'id':'old','path':'fixture','status':'failed'})
        self.assertNotIn('policy',self.cleaner.report()[0])
        self.assertNotIn('findingSource',policy_record({},'balanced'))

    def test_trash_replacement_and_missing_identity(self):
        e=self.move();self.assertEqual(recoverability(e),'recoverable while in Trash')
        source=Path(e['trashedTo']);source.rename(source.with_name('kept-original'))
        source.write_text('different object')
        self.assertIn('not recoverable',recoverability(e));self.assertFalse(self.cleaner.report()[0]['recoverable'])
        with self.assertRaisesRegex(ValueError,'Trashed item changed'):self.cleaner.undo(e['id'])
        self.assertIn('status unknown',recoverability({**e,'trashedIdentity':None}))
        source.unlink();self.assertEqual(recoverability(e),'unrecoverable (Trash emptied)')

    def test_trash_permission_error_is_unknown_and_restore_refuses(self):
        e=self.move()
        with patch('soji_cli.cleanup.file_identity',side_effect=PermissionError('mock TCC denial')):
            self.assertEqual(recoverability(e),'Trash unreadable; status unknown')
            with self.assertRaisesRegex(ValueError,'Trash unreadable; status unknown'):self.cleaner.restore(e)
        self.assertTrue(Path(e['trashedTo']).exists())

    def test_compound_partial_recovery_derived_from_members(self):
        e=self.move();m={**e,'status':'restored'}
        self.cleaner.append({**e,'id':'compound','status':'partial','members':[e,m]})
        row=next(e for e in self.cleaner.report() if e['id']=='compound')
        self.assertTrue(row['recoverable']);self.assertIn('restored',row['recovery'])
        self.assertEqual([m['recovery'] for m in row['members']],['recoverable while in Trash','restored'])

    def test_refusal_overlap_both_directions_and_sibling_control(self):
        self.refusal(self.target/'abc',error='Fresh guards refuse: File open or process working in this folder')
        self.assertIsNotNone(self.cleaner.live_use_refusal(str(self.target)))
        self.assertIsNotNone(self.cleaner.live_use_refusal(str(self.target/'abc/deeper')))
        self.assertIsNone(self.cleaner.live_use_refusal(str(self.target/'abcd')))
        self.assertIsNone(self.cleaner.live_use_refusal(str(self.target)+'-other'))
        result=self.cleaner.apply(self.plan());self.assertEqual(result['completed'],0)
        self.assertTrue(self.target.exists())

    def test_structured_refusal_survives_wording_and_expiry(self):
        self.refusal(self.target,refusalCode='contents-changed',error='translated wording')
        self.assertIsNotNone(self.cleaner.live_use_refusal(str(self.target)))
        with patch('soji_cli.cleanup.time.time',return_value=time.time()+86401):
            self.assertIsNone(self.cleaner.live_use_refusal(str(self.target)))

    def test_changed_contents_are_recorded_and_block_retry(self):
        plan=self.plan();write(self.target/'abc/new',age=1)
        result=self.cleaner.apply(plan);entry=result['entries'][0]
        self.assertEqual(entry['status'],'failed');self.assertEqual(entry['refusalCode'],'contents-changed')
        age_tree(self.home,40)
        retry=self.cleaner.apply(self.plan());self.assertEqual(retry['completed'],0)
        self.assertIn('In use',retry['entries'][0]['error'])

    def test_changed_identity_is_recorded(self):
        plan=self.plan();self.target.rename(self.target.with_name('old-kept'));write(self.target/'new',age=40)
        result=self.cleaner.apply(plan);self.assertEqual(result['entries'][0]['refusalCode'],'identity-changed')
        self.assertTrue(self.target.exists())

    def test_truncated_history_blocks_without_parsing_fragments(self):
        self.cleaner.journal.write_text('{"id":"truncated-refusal","path":')
        result=self.cleaner.apply(self.plan());self.assertEqual(result['completed'],0)
        self.assertEqual(result['entries'][0]['refusalCode'],'history-unknown')
        self.assertTrue(self.target.exists())

    def test_retry_does_not_restart_original_24h_clock(self):
        at=time.time()-86390
        self.cleaner.append({'id':'old','path':str(self.target),'status':'failed','at':at,'refusalCode':'active-use','error':'owner busy'})
        result=self.cleaner.apply(self.plan())
        self.assertEqual(result['completed'],0)
        self.assertEqual(result['entries'][0]['refusalAt'],at)
        with patch('soji_cli.cleanup.time.time',return_value=time.time()+20):
            self.assertIsNone(self.cleaner.live_use_refusal(str(self.target)))

    def test_new_refusal_invalidates_batch_cache(self):
        self.cleaner._batch={}
        self.assertIsNone(self.cleaner.live_use_refusal(str(self.target)))
        e={'id':'new','path':str(self.target),'status':'failed','at':time.time(),'refusalCode':'active-use','error':'busy'}
        self.cleaner._journal_best_effort(e)
        self.assertIsNotNone(self.cleaner.live_use_refusal(str(self.target)))
        self.cleaner._batch=None

    def test_old_changed_refusal_fallback(self):
        self.refusal(self.target,error='Contents changed since analysis')
        self.assertIsNotNone(self.cleaner.live_use_refusal(str(self.target)))

    def test_native_apps_failure_holds_owner_rules_and_warns(self):
        import plistlib
        app=self.home/'Applications/Obsidian.app/Contents/Info.plist'
        app.parent.mkdir(parents=True);app.write_bytes(plistlib.dumps({'CFBundleIdentifier':'md.obsidian','CFBundleName':'Obsidian'}))
        path=self.home/'Library/Application Support/obsidian/Partitions/vault/Code Cache'
        write(path/'js/blob',age=40);age_tree(self.home,40)
        for inventory in ({'error':'unavailable'},None,[None],[{'bundleID':None}]):
            with patch('soji_cli.apps.native',return_value=inventory):
                scan=self.scan();row=next(f for f in scan.findings if f.path==str(path))
            self.assertTrue(any('running status unknown' in h for h in row.holds),row.holds)
            self.assertTrue(any('Running-app inventory unavailable' in h for h in scan.context_warnings))
            for mode in MODES:self.assertFalse(row.decide(mode,scan.now)[0])
        # Successful empty inventory can permit a stale owner cache.
        scan=self.scan();row=next(f for f in scan.findings if f.path==str(path))
        self.assertTrue(row.decide('balanced',scan.now)[0],row.holds)
        with patch('soji_cli.apps.native',return_value=[{'bundleID':'md.obsidian','path':'/mock-other/Obsidian.app'}]):
            scan=self.scan();row=next(f for f in scan.findings if f.path==str(path))
        self.assertIn('Owning application is running',row.holds)

    def test_staged_descendant_parent_catalog_and_fresh(self):
        root=self.home/'.cache/.soji-removing-kept';target=root/'cache/blob'
        write(target,age=40);age_tree(self.home,40)
        scan=self.scan([root/'cache'])
        for f in scan.findings:
            for mode in MODES:self.assertFalse(f.decide(mode,scan.now)[0])
        # Even a catalog/synthetic row bypassing classify must refuse.
        f=Finding(str(target),1,1,1,0,'App caches','synthetic',tier='regenerable',comes_back='rebuilds',list_only=False)
        for mode in MODES:self.assertFalse(f.decide(mode,time.time())[0])
        item={'path':str(target),'identity':file_identity(target)}
        with self.assertRaisesRegex(ValueError,'staged object'):self.cleaner.fresh(item,{'roots':[str(self.home)]})
        scan=self.scan();self.assertIsNotNone(scan.staged_inside(str(self.home/'.cache')))
        self.assertIsNotNone(scan.staged_inside(str(root/'cache')))
        self.assertIsNone(scan.staged_inside(str(self.target)))

    def test_catalog_rows_containing_staged_objects_held(self):
        from soji_cli import catalogs
        staged=self.target/'.soji-removing-kept'
        write(staged/'blob',age=40);age_tree(self.home,40)
        def synthetic(scan):
            # Deliberately bypass classify, as native/session catalog rows can.
            return [Finding(str(self.target),1,1,1,0,'App caches','catalog',tier='regenerable',comes_back='rebuilds',list_only=False)]
        with patch.object(catalogs,'expand_catalogs',side_effect=synthetic):scan=self.scan()
        row=scan.findings[0]
        self.assertTrue(any('staged object' in h for h in row.holds))
        for mode in MODES:self.assertFalse(row.decide(mode,scan.now)[0])

    def test_fresh_native_early_return_cannot_bypass_staged_guard(self):
        staged=self.target/'.soji-removing-kept';write(staged/'blob',age=40)
        item={'path':str(self.target),'identity':file_identity(self.target),'action':{'kind':'uninstall'}}
        plan={'roots':[str(self.home)],'home':str(self.home)}
        with patch('soji_cli.uninstall.verify_uninstall') as verify:
            with self.assertRaisesRegex(ValueError,'staged object'):self.cleaner.fresh(item,plan)
            verify.assert_not_called()

    def test_healthy_cache_positive_and_unreadable_history(self):
        plan=self.plan();self.assertEqual(len(plan['items']),1)
        self.cleaner.journal.touch()
        original=Path.open
        def denied(path,*args,**kw):
            if path==self.cleaner.journal:raise PermissionError('mock denied')
            return original(path,*args,**kw)
        with patch.object(Path,'open',denied):result=self.cleaner.apply(plan)
        self.assertEqual(result['completed'],0);self.assertTrue(self.target.exists())
        self.assertEqual(result['entries'][0]['refusalCode'],'history-unknown')

    def test_shared_risk_groups(self):
        self.assertEqual(set(tui.RISK_GROUPS),set(HIGH_RISK_GROUPS))
        for group in ('Editor extensions','Build output','Agent worktrees','Agent and editor history'):
            f=Finding(str(self.target),1,1,1,0,group,'fixture',tier='regenerable',comes_back='rebuilds',list_only=False,identity=file_identity(self.target))
            scan=self.scan();scan.findings=[f]
            self.assertIn(group,' '.join(create_plan(scan,'aggressive')['warnings']))
            self.assertIn(group,' '.join(tui.cleanup_warnings('aggressive',[f])))
    def test_failed_undo_can_retry_without_redoing_successes(self):
        entries=[{'id':'a','path':'a','status':'done'},{'id':'b','path':'b','status':'done'}]
        class Retry:
            def __init__(self):self.calls=[]
            def undo(self,key):
                self.calls.append(key)
                if key=='b' and self.calls.count('b')==1:raise ValueError('blocked')
                return {'status':'restored'}
        cleaner=Retry()
        self.assertEqual(tui.undo_entries(entries,None,cleaner)[0],1)
        self.assertEqual(tui.undo_entries(entries,None,cleaner),(1,[]))
        self.assertEqual(cleaner.calls,['a','b','b'])
