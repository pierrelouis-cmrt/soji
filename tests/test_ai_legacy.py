import dataclasses
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from soji_cli.ai import (AIAnalyzer, PRESETS, read_submission, decode_submission,
    judgement_lapsed, judgement_needed, same_content_fingerprint, classify_failure, stop_agent, content_fingerprint, reusable_verdict, fingerprint)
from soji_cli.cadence import AnalysisCadence, Backlog, Moment


def claim(path='/fixture/cache'):
    return dict(path=path, title='Cache', group='Caches', regenerable=True,
                recommendation='remove', confidence=0.9)


class CadenceTests(unittest.TestCase):
    def test_backlog_thresholds_quiet_and_hour_boundaries(self):
        policy = AnalysisCadence()
        m = Moment(10000, last_change=9820, last_backlog_run=6400)
        self.assertEqual(policy.due(Backlog(10), m), 'backlog')
        self.assertEqual(policy.due(Backlog(0, 1_000_000_000), m), 'backlog')
        self.assertIsNone(policy.due(Backlog(9, 999_999_999), m))
        self.assertIsNone(policy.due(Backlog(10), dataclasses.replace(m, last_change=9820.001)))
        self.assertIsNone(policy.due(Backlog(10), dataclasses.replace(m, last_backlog_run=6400.001)))

    def test_backlog_precedes_power_and_idle_daily_checks(self):
        m = Moment(10000, on_battery=True, battery_percent=1, pause_below_percent=20)
        self.assertEqual(AnalysisCadence().due(Backlog(10), m), 'backlog')
        self.assertIsNone(AnalysisCadence().due(Backlog(1), m))

    def test_daily_counts_stale_rows_and_requires_idle(self):
        m = Moment(10000, idle_seconds=600)
        p = AnalysisCadence()
        self.assertEqual(p.due(Backlog(stale_count=1), m), 'daily')
        self.assertIsNone(p.due(Backlog(), m))
        self.assertIsNone(p.due(Backlog(1), dataclasses.replace(m, idle_seconds=599.99)))
        self.assertIsNone(p.due(Backlog(1), dataclasses.replace(m, last_daily_run=9999)))
        self.assertEqual(p.due(Backlog(1), dataclasses.replace(m, last_daily_run=10000-86400)), 'daily')

    def test_daily_battery_threshold_is_inclusive_and_unknown_is_zero(self):
        m = Moment(10000, idle_seconds=600, on_battery=True, pause_below_percent=20)
        p = AnalysisCadence()
        for percent in (None, 19, 20):
            self.assertIsNone(p.due(Backlog(1), dataclasses.replace(m, battery_percent=percent)))
        self.assertEqual(p.due(Backlog(1), dataclasses.replace(m, battery_percent=20.01)), 'daily')
        self.assertEqual(p.due(Backlog(1), dataclasses.replace(m, on_battery=False)), 'daily')


class VerdictPolicyTests(unittest.TestCase):
    def setUp(self):
        self.old = dict(sizeBytes=1_000_000_000, fileCount=20, newestChange=100)

    def test_fingerprint_timestamp_tolerance_and_nil(self):
        self.assertTrue(same_content_fingerprint(self.old, dict(self.old, newestChange=100.999)))
        self.assertFalse(same_content_fingerprint(self.old, dict(self.old, newestChange=101)))
        self.assertFalse(same_content_fingerprint(self.old, dict(self.old, fileCount=21)))
        self.assertTrue(same_content_fingerprint(dict(self.old, newestChange=None), dict(self.old, newestChange=None)))
        self.assertFalse(same_content_fingerprint(self.old, dict(self.old, newestChange=None)))

    def test_regular_size_and_age_boundaries(self):
        self.assertFalse(judgement_lapsed(self.old, dict(self.old, sizeBytes=1_250_000_000), 0, 14*86400))
        self.assertTrue(judgement_lapsed(self.old, dict(self.old, sizeBytes=1_250_000_001), 0, 1))
        self.assertTrue(judgement_lapsed(self.old, None, 0, 14*86400+0.1))
        small = dict(self.old, sizeBytes=1)
        self.assertFalse(judgement_lapsed(small, dict(small, sizeBytes=100_000_001), 0, 1))
        self.assertTrue(judgement_lapsed(small, dict(small, sizeBytes=100_000_002), 0, 1))

    def test_keep_size_and_timestamp_boundaries(self):
        self.assertFalse(judgement_lapsed(self.old, dict(self.old, sizeBytes=1_100_000_000, newestChange=3700), 0, 1, keep=True))
        self.assertTrue(judgement_lapsed(self.old, dict(self.old, sizeBytes=1_100_000_001), 0, 1, keep=True))
        self.assertTrue(judgement_lapsed(self.old, dict(self.old, newestChange=3700.01), 0, 1, keep=True))
        self.assertFalse(judgement_lapsed(self.old, dict(self.old, newestChange=None), 0, 1, keep=True))

    def test_negative_and_missing_levels(self):
        self.assertFalse(judgement_needed(self.old, self.old, 0, 86400, None))
        self.assertTrue(judgement_needed(self.old, self.old, 0, 86401, None))
        self.assertTrue(judgement_needed(self.old, self.old, 0, 1, claim()))
        self.assertFalse(judgement_needed(self.old, self.old, 0, 1, dict(claim(), levels={})))
        self.assertFalse(judgement_needed(self.old, self.old, 0, 1, dict(claim(), recommendation='keep')))


class SubmissionTests(unittest.TestCase):
    def test_salvages_valid_rows_and_rejects_bad_envelopes(self):
        value = {'findings': [claim(), dict(claim(), confidence=2), None], 'runID':'external'}
        self.assertEqual(decode_submission(value), {'findings':[claim()], 'processVerdicts':[]})
        for invalid in (None, [], {}, {'findings':'bad'}):
            self.assertIsNone(decode_submission(invalid))
        self.assertIsNone(decode_submission({'findings':[claim()]*501}))

    def test_invalid_file_falls_back_to_fenced_marker_in_result(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'submission.json').write_text('{broken')
            answer = 'SOJI_FINDINGS_BEGIN\n```json\n'+json.dumps({'findings':[claim()]})+'\n```\nSOJI_FINDINGS_END'
            self.assertEqual(read_submission(d,json.dumps({'result':answer}))['findings'], [claim()])
            Path(d,'submission.json').write_text(json.dumps({'findings':[]}))
            self.assertEqual(read_submission(d,answer)['findings'], [])

    def test_failure_patterns_and_precedence(self):
        cases = {'oauth token has revoked':'authentication', 'api error: 529':'rate-limit',
                 'billing_error':'quota', 'error: unexpected argument --bad':'cli',
                 'model alpha not supported; invalid api key':'model'}
        for text, expected in cases.items():
            self.assertEqual(classify_failure(text,''),expected)


class LaunchTests(unittest.TestCase):
    def scanner(self, root):
        return SimpleNamespace(home=str(root), protected=[], roots=[str(root)], database=None,
            findings=[], bytes=0, report=lambda level: {'roots':[str(root)], 'findings':[]})

    def test_presets_keep_mcp_extras(self):
        with tempfile.TemporaryDirectory() as d:
            for preset in PRESETS:
                if preset['id']=='custom': continue
                ai = AIAnalyzer(Path(d)/'state', preset=preset['id'])
                with patch.object(ai,'detect',return_value='/fixture/fake-agent'):
                    run, argv, env = ai.prepare(self.scanner(Path(d)))
                config = json.loads((run/'soji-mcp.json').read_text())['mcpServers']['soji']
                for key, value in preset.get('mcpServerFields',{}).items():
                    self.assertEqual(config[key], value)
                if preset['id']=='codex':
                    self.assertIn('default_tools_approval_mode="approve"', argv[argv.index('-c')+1])

    def test_fake_agent_run_salvages_output_without_provider(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); run=root/'run'; (run/'work').mkdir(parents=True)
            (run/'prompt.md').write_text('Synthetic fixture only')
            fake=root/'fake.py'
            fake.write_text('import json,sys\nassert sys.stdin.read()=="Synthetic fixture only"\nprint("SOJI_FINDINGS_BEGIN")\nprint(json.dumps({"findings":[]}))\nprint("SOJI_FINDINGS_END")\n')
            ai=AIAnalyzer(root); scanner=self.scanner(root)
            scanner.findings=[SimpleNamespace(path=str(root/'cache'),size=1,newest=0,files=1,identity={},hint_id=None,rule=None,tier='unmatched')]
            with patch.object(ai,'prepare',return_value=(run,[sys.executable,str(fake)],{})), patch.object(ai,'apply') as apply:
                result=ai.run(scanner)
            self.assertTrue(result['executed']); self.assertEqual(result['exitCode'],0)
            self.assertEqual(result['submitted'],0); apply.assert_called_once_with(scanner,[])
            self.assertEqual(json.loads(next(root.glob('agent-runs-*.json')).read_text())['count'],1)

    def test_stubborn_fake_agent_is_killed_and_reaped(self):
        p=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready",flush=True); time.sleep(30)'],stdout=subprocess.PIPE,start_new_session=True,text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(),'ready')
            stop_agent(p,grace=0.05)
            self.assertEqual(p.returncode,-signal.SIGKILL)
        finally:
            if p.poll() is None: os.killpg(p.pid,signal.SIGKILL);p.wait()
            p.stdout.close()

class CacheIntegrationTests(unittest.TestCase):
    def finding(self):
        return SimpleNamespace(path='/fixture/cache', size=1_000_000_000,
            newest=100, files=20, hint_id=None, rule=None, tier='unmatched',
            identity=dict(device=1,inode=2,type=16384,parentDevice=1,parentInode=3,mtimeNs=10,ctimeNs=20))

    def test_content_snapshot_and_identity_guard(self):
        f=self.finding(); content=content_fingerprint(f)
        self.assertNotIn('mtimeNs',content['identity'])
        c=dict(claim(f.path),levels={'careful':168,'balanced':24,'aggressive':1,'reason':'Fixture'})
        store=SimpleNamespace(verdict_record=lambda path:dict(content=content,data=c,judgedAt=0))
        f.identity['mtimeNs']=100
        self.assertEqual(reusable_verdict(store,f,1),c)
        for key in ('device','inode','type','parentDevice','parentInode'):
            original=f.identity[key];f.identity[key]=original+1
            self.assertIsNone(reusable_verdict(store,f,1));f.identity[key]=original
        f.identity={}
        self.assertIsNone(reusable_verdict(store,f,1))

    def test_ordinary_and_backlog_policies(self):
        f=self.finding(); c=dict(claim(f.path),levels={'careful':168,'balanced':24,'aggressive':1,'reason':'Fixture'})
        record=dict(content=content_fingerprint(f),data=c,judgedAt=0)
        store=SimpleNamespace(verdict_record=lambda path:record)
        self.assertIsNone(reusable_verdict(store,f,14*86400+1))
        self.assertEqual(reusable_verdict(store,f,14*86400+1,trigger='backlog'),c)
        f.size=1_250_000_000
        self.assertEqual(reusable_verdict(store,f,1),c)
        f.size+=1
        self.assertIsNone(reusable_verdict(store,f,1,trigger='backlog'))
        f.size=1_000_000_000;c.pop('levels')
        self.assertIsNone(reusable_verdict(store,f,1))
        self.assertEqual(reusable_verdict(store,f,1,trigger='backlog'),c)
        record['data']=None
        self.assertIsNone(reusable_verdict(store,f,1))

    def test_legacy_store_and_nullable_migration_fallback(self):
        f=self.finding();c=claim(f.path)
        legacy=SimpleNamespace(verdict=Mock(return_value=c))
        self.assertEqual(reusable_verdict(legacy,f,123),c)
        legacy.verdict.assert_called_once_with(f.path,fingerprint(f),123)
        legacy.verdict_record=lambda path:dict(content=None)
        self.assertEqual(reusable_verdict(legacy,f,124),c)

    def test_run_saves_pre_apply_baseline_and_reuses_cache(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run=root/'run';(run/'work').mkdir(parents=True)
            (run/'prompt.md').write_text('synthetic')
            f=self.finding();f.path=str(root/'cache')
            expected_content=content_fingerprint(f);expected_strict=fingerprint(f)
            c=dict(claim(f.path),levels={'careful':168,'balanced':24,'aggressive':1,'reason':'Fixture'})
            fake=root/'fake.py'
            fake.write_text('print('+repr('SOJI_FINDINGS_BEGIN\n'+json.dumps({'findings':[c]})+'\nSOJI_FINDINGS_END')+')')
            db=sqlite3.connect(':memory:');db.execute('CREATE TABLE runs(id,start,end,status,usage)')
            saved=[]
            store=SimpleNamespace(db=db,verdict_record=lambda path:None,
                save_verdict=lambda *args,**kwargs:saved.append((args,kwargs)),close=Mock())
            scanner=SimpleNamespace(database='synthetic',findings=[f])
            ai=AIAnalyzer(root)
            def mutate(scanner,findings):
                f.tier='regenerable';f.rule={'changed':True};f.identity['inode']=999;f.size=2
            with patch('soji_cli.ai.IndexStore',return_value=store),patch.object(ai,'prepare',return_value=(run,[sys.executable,str(fake)],{})),patch.object(ai,'apply',side_effect=mutate):
                result=ai.run(scanner)
            self.assertTrue(result['executed']);self.assertEqual(len(saved),1)
            self.assertEqual(saved[0][0][1],expected_strict)
            self.assertEqual(saved[0][1]['content'],expected_content)
            store.close.assert_called_once()
            # Cache-hit path never prepares or starts a provider.
            f=self.finding();c=dict(claim(f.path),levels={'careful':168,'balanced':24,'aggressive':1,'reason':'Fixture'});scanner.findings=[f]
            store.verdict_record=lambda path:dict(content=content_fingerprint(f),data=c,judgedAt=time.time())
            with patch('soji_cli.ai.IndexStore',return_value=store),patch.object(ai,'prepare') as prepare,patch.object(ai,'apply'):
                result=ai.run(scanner)
            self.assertEqual(result,{'cached':1,'executed':False});prepare.assert_not_called()
            db.close()


if __name__=='__main__': unittest.main()
