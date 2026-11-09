"""Independent exact-head proofs. Disposable JournalSafety homes/state/Trash only.

These assert the required safety behavior and intentionally fail on 82da248.
No production guard is mocked; app/native inventories use the hermetic fixture.
"""
import json
import plistlib
import time
import unittest
from unittest.mock import patch
from tests import test_journal_refusal_safety as journal_fixture
from soji_cli.uninstall import uninstall_plan


class ExecutionBoundaryProofs(unittest.TestCase):
    def fixture(self):
        f = journal_fixture.JournalSafety(); f.setUp(); self.addCleanup(f.doCleanups)
        return f

    def test_nonfinite_refusal_timestamp_blocks_mutation(self):
        for field in ('at', 'refusalAt'):
            with self.subTest(field=field):
                f = self.fixture(); plan = f.plan()
                record = dict(id='corrupt', path=str(f.target), status='failed',
                              at=time.time(), refusalCode='active-use', error='running')
                record[field] = float('nan')
                f.cleaner.journal.write_text(json.dumps(record) + '\n')
                result = f.cleaner.apply(plan)
                # The malformed history must block; retain the actual result
                # in the failure so the fixture move is independently visible.
                self.assertEqual(result['completed'], 0, result)
                self.assertTrue(f.target.exists())

    def test_running_uninstall_refusal_blocks_immediate_retry(self):
        f = self.fixture(); app = f.home/'Applications/Fixture.app'
        (app/'Contents').mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps(
            {'CFBundleIdentifier':'org.fixture.app','CFBundleName':'Fixture'}))
        with patch('soji_cli.apps.code_identity', return_value={'team':None,'groups':[]}), \
             patch('soji_cli.apps.user_receipts', return_value={}):
            plan = uninstall_plan(str(app), str(f.home))
            with patch('soji_cli.apps.native', return_value=[
                    {'bundleID':'org.fixture.app','path':str(app)}]):
                first = f.cleaner.apply(plan)
            self.assertEqual(first['completed'], 0, first)
            self.assertIn('App is running', first['entries'][0]['error'])
            self.assertTrue(app.exists())
            # Successful empty inventory on retry is a momentary snapshot;
            # it must not erase the live-use refusal recorded just above.
            retry = f.cleaner.apply(plan)
        self.assertEqual(retry['completed'], 0, retry)
        self.assertTrue(app.exists())

    def test_invalid_root_and_member_clocks_fail_closed(self):
        values=(float('nan'),float('inf'),float('-inf'),True,False,None,'123')
        for member in (False,True):
            for field in ('at','refusalAt'):
                for value in values:
                    with self.subTest(member=member,field=field,value=repr(value)):
                        f=self.fixture();plan=f.plan()
                        record=dict(id='corrupt',path=str(f.target),status='failed',
                                    at=time.time(),refusalCode='active-use',error='running')
                        target=record
                        if member:
                            record['status']='done'
                            target=dict(path=str(f.target),status='failed',at=time.time(),refusalCode='active-use')
                            record['members']=[target]
                        target[field]=value
                        f.cleaner.journal.write_text(json.dumps(record)+'\n')
                        result=f.cleaner.apply(plan)
                        self.assertEqual(result['completed'],0,result)
                        self.assertEqual(result['entries'][0]['refusalCode'],'history-unknown')
                        self.assertTrue(f.target.exists())

    def test_overflowing_json_number_is_unknown_history(self):
        f=self.fixture();plan=f.plan()
        record=dict(id='overflow',path=str(f.target),status='failed',at=0,refusalCode='active-use')
        # Valid JSON syntax which json.loads converts to infinity without parse_constant.
        f.cleaner.journal.write_text(json.dumps(record).replace('"at": 0','"at": 1e999')+'\n')
        result=f.cleaner.apply(plan)
        self.assertEqual(result['completed'],0,result)
        self.assertEqual(result['entries'][0]['refusalCode'],'history-unknown')
        self.assertTrue(f.target.exists())

    def test_finite_expired_root_and_member_history_remains_usable(self):
        for member in (False,True):
            for value in (int(time.time()-90000),time.time()-90000):
                with self.subTest(member=member,value=value):
                    f=self.fixture();plan=f.plan()
                    refusal=dict(path=str(f.target),status='failed',at=value,refusalAt=value,refusalCode='active-use')
                    record=dict(refusal,id='expired')
                    if member:record=dict(id='expired',path=str(f.target),status='done',at=time.time(),members=[refusal])
                    f.cleaner.journal.write_text(json.dumps(record)+'\n')
                    result=f.cleaner.apply(plan)
                    self.assertEqual(result['completed'],1,result)
                    self.assertFalse(f.target.exists())

    def test_uninstall_active_refusal_keeps_original_clock_and_expires(self):
        from soji_cli import cleanup, safety
        self.assertIs(cleanup.SafetyRefusal,safety.SafetyRefusal)
        f=self.fixture();app=f.home/'Applications/Fixture.app'
        (app/'Contents').mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps(
            {'CFBundleIdentifier':'org.fixture.app','CFBundleName':'Fixture'}))
        with patch('soji_cli.apps.code_identity',return_value={'team':None,'groups':[]}), \
             patch('soji_cli.apps.user_receipts',return_value={}):
            plan=uninstall_plan(str(app),str(f.home))
            with patch('soji_cli.apps.native',return_value=[{'bundleID':'org.fixture.app','path':str(app)}]):
                first=f.cleaner.apply(plan)
            entry=first['entries'][0]
            self.assertEqual(first['completed'],0,first)
            self.assertEqual(entry['refusalCode'],'active-use')
            at=entry['at']
            # The app-root refusal also holds descendants; retry does not renew it.
            self.assertEqual(f.cleaner.live_use_refusal(str(app/'Contents'))[0],at)
            retry=f.cleaner.apply(plan)
            self.assertEqual(retry['completed'],0,retry)
            self.assertEqual(retry['entries'][0]['refusalAt'],at)
            self.assertTrue(app.exists())
            with patch('soji_cli.cleanup.time.time',return_value=at+90000):
                fresh_plan=uninstall_plan(str(app),str(f.home))
                expired=f.cleaner.apply(fresh_plan)
            self.assertEqual(expired['completed'],1,expired)
            self.assertFalse(app.exists())

    def test_compound_undo_retry_keeps_prior_successes(self):
        from tests.test_compound_sessions import CompoundSessionTests
        f = CompoundSessionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        result = f.cleaner.apply(f.plan()); e = result['entries'][0]
        self.assertEqual(result['completed'], 1, result)
        real = f.cleaner.restore; calls = []
        def restore(member):
            calls.append(member['path'])
            if member['path'] == str(f.subagents) and calls.count(member['path']) == 1:
                raise OSError('injected fixture restore failure')
            return real(member)
        with patch.object(f.cleaner, 'restore', side_effect=restore):
            with self.assertRaisesRegex(ValueError, 'Restore incomplete'):
                f.cleaner.undo(e['id'])
            self.assertTrue(f.transcript.exists())
            restored = f.cleaner.undo(e['id'])
        self.assertEqual(restored['status'], 'restored')
        self.assertEqual(calls.count(str(f.transcript)), 1)
        self.assertEqual(calls.count(str(f.subagents)), 2)
        self.assertTrue((f.tool_results/'out.txt').exists())
