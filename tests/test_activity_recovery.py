"""Disposable metadata and Git fixtures for executable-derived adapter contracts."""
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from soji_cli.engine import Finding

from soji_cli.activity import ActivityIndex
from soji_cli.apps import InstalledTools
from soji_cli.catalogs import codex_writer_ids, codex_idle_ordinal, codex_process_freshness, expand_catalogs, runtime_catalog, document_versions
from soji_cli.gitstate import GitInspector


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.now=dt.datetime(2026,11,7,12).timestamp()
        self.env=patch.dict(os.environ,{'CODEX_HOME':''});self.env.start()
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def file(self,path,text,mtime=1000):
        p=self.home/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
        os.utime(p,(mtime,mtime));return p
    def test_metadata_head_uses_first_cwd_and_mtime(self):
        p=self.file('head.jsonl',json.dumps({'cwd':'/fixture/project','timestamp':'2099-01-01'})+'\n'+json.dumps({'cwd':'/wrong'})+'\n',1234)
        a=ActivityIndex(self.home);a.jsonl_metadata(p,'Claude Code')
        self.assertEqual([(r.path,r.at) for r in a.records],[('/fixture/project',1234)])
    def test_metadata_extracts_cwd_without_decoding_large_transcript(self):
        p=self.file('large.jsonl','{"cwd":"/fixture/quoted\\"path","message":"'+'x'*100000+'"}',4321)
        a=ActivityIndex(self.home);a.jsonl_metadata(p,'Claude Code')
        self.assertEqual(a.records[0].path,'/fixture/quoted"path')
        self.assertNotIn('message',str(a.report()))
    def test_no_tail_fallback_and_symlinks_not_read(self):
        p=self.file('tail.jsonl','x'*65536+'\n{"cwd":"/fixture/tail"}')
        link=self.home/'link.jsonl';link.symlink_to(p)
        a=ActivityIndex(self.home);a.jsonl_metadata(p,'Claude Code');a.jsonl_metadata(link,'Claude Code')
        self.assertEqual(a.records,[])
    def test_claude_profile_roots(self):
        for name in ('.claude','.claude-work','.claudex'):
            self.file(name+'/projects/p/session.jsonl','{"cwd":"/fixture/'+name+'"}')
        a=ActivityIndex(self.home);a.claude()
        self.assertEqual({Path(r.path).name for r in a.records},{'.claude','.claude-work'})
    def test_codex_override_30_dates_and_16k_head(self):
        base=self.home/'custom-codex'
        for days in (0,29,30):
            day=dt.datetime.fromtimestamp(self.now).date()-dt.timedelta(days=days)
            self.file('custom-codex/sessions/'+day.strftime('%Y/%m/%d')+'/rollout.jsonl','{"payload":{"cwd":"/fixture/day'+str(days)+'"}}')
        self.file('custom-codex/sessions/2026/11/07/late.jsonl',' '*16384+'{"cwd":"/fixture/late"}')
        with patch.dict(os.environ,{'CODEX_HOME':str(base)}):
            a=ActivityIndex(self.home,self.now);a.codex()
        self.assertEqual({Path(r.path).name for r in a.records},{'day0','day29'})
    def test_t3_unarchived_now_archived_max_and_deleted_excluded(self):
        db=self.home/'.t3/userdata/statev2.sqlite';db.parent.mkdir(parents=True)
        with sqlite3.connect(db) as c:
            c.execute('CREATE TABLE orchestration_v2_projection_threads(payload_json,updated_at,archived_at,deleted_at)')
            c.executemany('INSERT INTO orchestration_v2_projection_threads VALUES(?,?,?,?)',[
                (json.dumps({'worktreePath':'/fixture/live'}),'2026-01-01T00:00:00Z',None,None),
                (json.dumps({'worktreePath':'/fixture/archived'}),'2026-01-01T00:00:00Z','2026-02-01T00:00:00Z',None),
                (json.dumps({'worktreePath':'/fixture/deleted'}),'2026-01-01T00:00:00Z',None,'yes')])
        a=ActivityIndex(self.home,self.now);a.t3();records={Path(r.path).name:r for r in a.records}
        self.assertEqual(set(records),{'live','archived'});self.assertEqual(records['live'].at,self.now)
        self.assertTrue(records['live'].active);self.assertEqual(records['archived'].at,dt.datetime(2026,2,1,tzinfo=dt.timezone.utc).timestamp())
    def test_last_is_directory_boundary_descendant_query(self):
        a=ActivityIndex(self.home);a.add('/fixture/project/sub',200,'test');a.add('/fixture/project-other',300,'test')
        self.assertEqual(a.last('/fixture/project').at,200)
        self.assertIsNone(a.last('/fixture/project/sub/deep'))
        self.assertEqual(a.last('/fixture/project/sub/deep',include_ancestors=True).at,200)
    def test_editor_uses_storage_directory_or_state_db(self):
        p=self.file('Library/Application Support/Code/User/workspaceStorage/id/workspace.json',json.dumps({'folder':'file:///fixture/space%20name'}),900)
        os.utime(p.parent,(100,100))
        a=ActivityIndex(self.home);a.editors();self.assertEqual(a.records[0].at,100)
        self.assertEqual(a.records[0].path,'/fixture/space name')
        self.file(str(p.parent.relative_to(self.home))+'/state.vscdb','',200)
        os.utime(p.parent,(100,100));a=ActivityIndex(self.home);a.editors();self.assertEqual(a.records[0].at,200)
    def test_codex_catalog_idle_boundaries_and_process_freshness(self):
        for seconds,ordinal in ((-1,3),(10799,3),(10800,2),(172799,2),(172800,1),(604799,1),(604800,0)):
            self.assertEqual(codex_idle_ordinal(seconds),ordinal)
        self.assertEqual(codex_process_freshness(0),300)
        self.assertEqual(codex_process_freshness(0.01),300)
        self.assertEqual(codex_process_freshness(2),7200)

    def test_catalog_compressed_session_and_live_lock_retention(self):
        p=self.file('.codex/archived_sessions/rollout-12345678.jsonl.zst','compressed fixture',1000)
        self.file('.codex/thread-writer-locks/12345678.lock','')
        root=str(p.parent)
        def finding(path):return Finding(str(path),100,100,1,1000,'Agent and editor history','session')
        initial=finding(root);initial.hint_id='codex-sessions'
        scanner=SimpleNamespace(home=self.home,now=self.now,activity=None,findings=[initial],
            nodes={str(p):SimpleNamespace(path=str(p),directory=False)},classify=lambda node:finding(node.path))
        rows=expand_catalogs(scanner)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0].path,str(p))
        self.assertEqual(rows[0].levels['careful'],168);self.assertEqual(rows[0].levels['balanced'],48)
        self.assertEqual(rows[0].levels['aggressive'],3);self.assertEqual(rows[0].last_activity,self.now)
        self.assertFalse(rows[0].decide('aggressive',self.now)[0])

    def test_catalog_process_freshness_all_modes_and_exact_boundary(self):
        p=self.file('.codex/sessions/rollout-old.jsonl','{}',self.now-10800)
        root=str(p.parent)
        def finding(path):return Finding(str(path),100,100,1,self.now-10800,'Agent and editor history','session')
        initial=finding(root);initial.hint_id='codex-sessions'
        scanner=SimpleNamespace(home=self.home,now=self.now,activity=None,processes=['/fixture/bin/codex'],recent_activity_hours=4,
            findings=[initial],nodes={str(p):SimpleNamespace(path=str(p),directory=False)},classify=lambda node:finding(node.path))
        row=expand_catalogs(scanner)[0]
        self.assertIn('Codex is running',row.holds[0])
        for mode in ('careful','balanced','aggressive'):self.assertFalse(row.decide(mode,self.now)[0])
        scanner.recent_activity_hours=3
        self.assertEqual(expand_catalogs(scanner)[0].holds,[])
        scanner.recent_activity_hours=4;scanner.processes=['/fixture/bin/codex-helper']
        self.assertEqual(expand_catalogs(scanner)[0].holds,[])

    def test_runtime_process_snapshot_available_busy_and_unavailable(self):
        with patch('soji_cli.catalogs.json_command',side_effect=[{},{}]),patch('soji_cli.catalogs.command',return_value=(0,'123 /usr/bin/other\n','')):
            data=runtime_catalog()
        self.assertTrue(data['available']);self.assertTrue(data['processesAvailable']);self.assertEqual(data['busyProcesses'],[])
        with patch('soji_cli.catalogs.json_command',side_effect=[{},{}]),patch('soji_cli.catalogs.command',return_value=(0,'123 /Applications/Xcode.app/usr/bin/xcodebuild\n456 /usr/bin/simctl\n','')):
            data=runtime_catalog()
        self.assertFalse(data['available']);self.assertTrue(data['busy'])
        self.assertEqual([p['name'] for p in data['busyProcesses']],['xcodebuild','simctl'])
        for output in ((-1,'','unavailable'),(0,'',''),(0,'malformed','')):
            with patch('soji_cli.catalogs.json_command',side_effect=[{},{}]),patch('soji_cli.catalogs.command',return_value=output):
                data=runtime_catalog()
            self.assertFalse(data['available']);self.assertFalse(data['processesAvailable']);self.assertIsNone(data['busy'])

    def test_document_versions_explicit_unavailable(self):
        for result in (None,{'error':'native failure'},'bad output'):
            with patch('soji_cli.catalogs.native',return_value=result):data=document_versions('/fixture/document')
            self.assertFalse(data['available']);self.assertIn('error',data);self.assertNotIn('versions',data)

    def test_codex_lock_names_strip_extension_and_reject_short_ids(self):
        self.file('.codex/thread-writer-locks/12345678.lock','private ignored')
        self.file('.codex/thread-writer-locks/short.lock','')
        self.assertEqual(codex_writer_ids(self.home),{'12345678'})
    def test_jsonc_comments_do_not_break_url_or_quoted_command(self):
        p=self.file('mcp.jsonc','// header\n{"url":"https://example.invalid",/*block*/"command":"/fixture/tool"}')
        t=InstalledTools(self.home);data=t.config_json(p);t.extract(data,'fixture')
        self.assertEqual(data['url'],'https://example.invalid');self.assertEqual(t.targets,[('/fixture/tool','fixture')])
        self.file('oversize.json',' '*4000001);self.assertIsNone(t.config_json(self.home/'oversize.json'))
    def git(self,repo,*args):
        return subprocess.run(['/usr/bin/git','-C',str(repo),*args],check=True,capture_output=True,text=True).stdout.strip()
    def repo(self,branch='main'):
        repo=self.home/'repo';repo.mkdir();self.git(repo,'init','-b',branch)
        self.git(repo,'config','user.email','fixture@example.invalid');self.git(repo,'config','user.name','Fixture')
        (repo/'file').write_text('one');self.git(repo,'add','file');self.git(repo,'commit','-m','fixture');return repo
    def test_git_recognizes_trunk_and_locked_worktree(self):
        repo=self.repo('trunk');work=self.home/'work';self.git(repo,'worktree','add','--detach',str(work))
        self.git(repo,'worktree','lock',str(work))
        state=GitInspector().inspect(str(work),True)
        self.assertEqual(state['defaultBranch'],'trunk');self.assertFalse(state['unmerged']);self.assertTrue(state['locked'])
    def test_git_origin_head_precedes_unrelated_local_main(self):
        repo=self.repo();first=self.git(repo,'rev-parse','HEAD')
        self.git(repo,'update-ref','refs/remotes/origin/trunk',first)
        self.git(repo,'symbolic-ref','refs/remotes/origin/HEAD','refs/remotes/origin/trunk')
        (repo/'file').write_text('two');self.git(repo,'commit','-am','new commit only local main')
        work=self.home/'work';self.git(repo,'worktree','add','--detach',str(work))
        state=GitInspector().inspect(str(work),True)
        self.assertEqual(state['defaultBranch'],'origin/trunk');self.assertTrue(state['unmerged']);self.assertTrue(state['unpushed'])

if __name__=='__main__':unittest.main()
