from __future__ import annotations
import dataclasses
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch,Mock
from soji_cli.engine import Scanner,Node,Finding,Catalog
from soji_cli.activity import ActivityIndex
from soji_cli.apps import AppCatalog,InstalledTools
from soji_cli.specialized import SpecializedRules,ProjectPins,DeviceCatalog,FIELDS
from soji_cli.index import IndexedScanner,IndexStore
from soji_cli.cleanup import Cleaner,create_plan,file_identity,validate_plan
from soji_cli.gitstate import GitInspector
from soji_cli.mcp import MCPServer,validate,SCHEMAS
from soji_cli.ai import AIAnalyzer,PRESETS,fingerprint
from soji_cli.util import atomic_json

class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.base=Path(self.temp.name).resolve();self.home=self.base/'home';self.home.mkdir();self.state=self.base/'state'
    def tearDown(self):self.temp.cleanup()
    def file(self,rel,text='x',binary=None):
        p=self.home/rel;p.parent.mkdir(parents=True,exist_ok=True)
        if binary is None:p.write_text(text)
        else:p.write_bytes(binary)
        return p
    def scan(self):
        s=Scanner([str(self.home)],home=str(self.home),context=False,min_bytes=0)
        with patch.object(Scanner,'collect_context',lambda self:None):s.run()
        self.assertFalse(s.error);return s
    def special(self,scanner,devices=None,apps=None):
        return SpecializedRules(scanner,apps or AppCatalog(str(self.home)),ActivityIndex(str(self.home)),InstalledTools(str(self.home)),devices or DeviceCatalog(str(self.home),{'devices':{},'runtimes':[]}).build())

class ActivityTests(Fixture):
    def test_claude_and_codex_cwd(self):
        cwd=str(self.home/'Projects/p')
        self.file('.claude/projects/project/session.jsonl',json.dumps({'cwd':cwd,'timestamp':'2026-01-01T12:00:00Z','message':{'content':'PRIVATE_DO_NOT_RETURN'}})+'\n')
        self.file(time.strftime('.codex/sessions/%Y/%m/%d/rollout.jsonl'),json.dumps({'type':'session_meta','payload':{'cwd':cwd},'timestamp':'2026-02-01T12:00:00Z'})+'\n')
        a=ActivityIndex(str(self.home)).build();self.assertEqual(len(a.records),2)
        self.assertIsNotNone(a.last(str(self.home/'Projects/p/cache'),include_ancestors=True))
        self.assertNotIn('PRIVATE_DO_NOT_RETURN',json.dumps(a.report()))
    def test_t3_exact_query(self):
        p=self.home/'.t3/userdata/statev2.sqlite';p.parent.mkdir(parents=True)
        with sqlite3.connect(p) as c:
            c.execute('CREATE TABLE orchestration_v2_projection_threads(payload_json TEXT,updated_at REAL,archived_at REAL,deleted_at REAL)')
            c.execute('INSERT INTO orchestration_v2_projection_threads VALUES(?,?,NULL,NULL)',(json.dumps({'worktreePath':str(self.home/'work')}),1700000000000))
        c.close()
        a=ActivityIndex(str(self.home),now=1800000000).build();self.assertEqual(a.last(str(self.home/'work')).at,1800000000)
    def test_editor_file_url(self):
        p=self.file('Library/Application Support/Cursor/User/workspaceStorage/id/workspace.json',json.dumps({'folder':(self.home/'project with space').as_uri()}))
        a=ActivityIndex(str(self.home)).build();self.assertEqual(a.records[0].path,str(self.home/'project with space'))
    def test_corrupt_sources_are_nonfatal(self):
        self.file('.claude/projects/a/log.jsonl','not-json\n');self.file('.t3/userdata/statev2.sqlite','garbage')
        a=ActivityIndex(str(self.home)).build();self.assertTrue(a.errors);self.assertFalse(a.records)

class SpecializedTests(Fixture):
    def finding(self,s,path):return s.classify(s.nodes[str(path)])
    def test_every_rule_field_has_handler(self):
        fields={k for h in Catalog(str(self.home)).hints for k in h.get('rule',{})}
        self.assertEqual(fields,FIELDS)
    def test_retention_uses_newest_timestamps(self):
        a=self.file('.nvm/versions/node/v18.9.0/bin/node');b=self.file('.nvm/versions/node/v18.10.0/bin/node')
        s=self.scan();sp=self.special(s)
        old=self.finding(s,a.parent.parent);new=self.finding(s,b.parent.parent)
        old.newest=100;new.newest=200
        s.nodes[old.path].newest=100;s.nodes[new.path].newest=200
        old.rule={'keepNewest':1};new.rule={'keepNewest':1}
        sp.evaluate(old);sp.evaluate(new)
        self.assertNotIn('balanced',old.mode_holds);self.assertIn('balanced',new.mode_holds)
    def test_active_symlink(self):
        p=self.file('.local/share/claude/versions/1.0/claude');self.file('.local/share/claude/versions/2.0/claude')
        link=self.home/'.local/bin/claude';link.parent.mkdir(parents=True);link.symlink_to(p)
        s=self.scan();f=self.finding(s,p.parent);self.special(s).evaluate(f)
        self.assertTrue(any('Active version' in h for h in f.holds))
    def test_pins(self):
        self.file('project/.nvmrc','18\n');self.file('project/.ruby-version','3.2.1\n');self.file('project/build.gradle','compileSdk = 35\nbuildToolsVersion "35.0.0"')
        pins=ProjectPins().scan([str(p) for p in self.home.rglob('*')])
        self.assertTrue(pins.keeps('/versions/v18.20.0','node'));self.assertTrue(pins.keeps('/platforms/android-35','android'));self.assertFalse(pins.keeps('/versions/v20.0.0','node'))
    def test_app_ownership_running_and_apple(self):
        p=self.file('Library/Caches/co.example.Test/item');s=self.scan()
        apps=AppCatalog(str(self.home));apps.apps=[{'path':'/Applications/Test.app','bundle':'co.example.Test','name':'Test','version':'1'}];apps.running=[{'bundleID':'co.example.Test'}]
        f=self.finding(s,p.parent);f.rule={'notWhileOwnerRuns':True,'onlyIfOwnerInstalled':True};sp=self.special(s,apps=apps);sp.evaluate(f)
        self.assertTrue(any('application is running' in h for h in f.holds))
        f=self.finding(s,p.parent);f.rule={'onlyIfOwnerNotInstalled':True};sp.evaluate(f);self.assertIn('Owning application is installed',f.holds)
        f=self.finding(s,p.parent);f.path=str(self.home/'Library/Containers/com.apple.Example/Data/Library/Caches');f.rule={'notIfAppleOwned':True};sp.evaluate(f);self.assertTrue(any('Apple-owned' in h for h in f.holds))
    def test_vendor_folder_of_installed_app_is_not_a_leftover(self):
        p=self.file('Library/Application Support/MathWorks/MATLAB/R2026a/matlab.prf');other=self.file('Library/Application Support/Gone Vendor/data').parent;connector=self.file('Library/Application Support/com.mathworks.matlabconnector/x').parent;s=self.scan()
        apps=AppCatalog(str(self.home));apps.apps=[{'path':'/Applications/MATLAB_R2026a.app','bundle':'com.mathworks.matlab','name':'MATLAB_R2026a','version':'26.1'}]
        vendor=self.home/'Library/Application Support/MathWorks';sp=self.special(s,apps=apps)
        self.assertEqual(apps.owner(str(vendor)),[])
        f=self.finding(s,vendor);f.rule={'onlyIfOwnerNotInstalled':True};sp.evaluate(f);self.assertIn('Owning application is installed',f.holds)
        # Vendor matching only adds holds: it never satisfies an installed-owner requirement.
        f=self.finding(s,vendor);f.rule={'onlyIfOwnerInstalled':True};sp.evaluate(f);self.assertIn('Owning application is unknown',f.holds)
        f=self.finding(s,connector);f.rule={'onlyIfOwnerNotInstalled':True};sp.evaluate(f);self.assertIn('Owning application is installed',f.holds)
        f=self.finding(s,other);f.rule={'onlyIfOwnerNotInstalled':True};sp.evaluate(f);self.assertNotIn('Owning application is installed',f.holds)
    def test_missing_workspace_early(self):
        import plistlib
        p=self.file('Library/Developer/Xcode/DerivedData/Old/info.plist',binary=plistlib.dumps({'WorkspacePath':str(self.home/'gone.xcodeproj')}))
        s=self.scan();f=self.finding(s,p.parent);self.special(s).evaluate(f);self.assertEqual(f.rule_early_reason,'workspaceMissing');self.assertNotEqual(f.special_min_hours,1)
    def test_booted_simulator_blocked(self):
        p=self.file('Library/Developer/CoreSimulator/Devices/ABC/data/file');s=self.scan()
        devices=DeviceCatalog(str(self.home),{'devices':{'runtime':[{'udid':'ABC','state':'Booted'}]},'runtimes':[]}).build()
        f=self.finding(s,p.parents[1]);self.special(s,devices).evaluate(f);self.assertIn('Simulator is not shut down',f.holds)
    def test_retention_age_and_minimum(self):
        self.file('.cache/sample/a');s=self.scan();f=s.findings[0];f.rule={'minIdleDays':14,'minSizeBytes':10**12}
        self.special(s).evaluate(f);self.assertEqual(f.rule_min_hours['balanced'],336);self.assertIn('Below hint minimum size',f.holds)

class IndexTests(Fixture):
    def test_cache_reuse_and_incremental_update(self):
        path=self.file('data/a','a'*5000);db=self.state/'index.sqlite'
        def scanner():return IndexedScanner([str(self.home)],home=str(self.home),context=False,min_bytes=0,database=db)
        with patch('soji_cli.index.native',return_value={'eventID':100}),patch('soji_cli.index.events',return_value=[{'checkpoint':100}]):
            first=scanner();first.run();self.assertFalse(first.error);self.assertEqual(first.index_info['strategy'],'full')
            second=scanner();second.run();self.assertFalse(second.error);self.assertEqual(second.visited,0);self.assertEqual(first.bytes,second.bytes)
            path.write_text('b'*15000)
            with patch('soji_cli.index.events',return_value=[{'path':str(path),'flags':0x1000,'id':101},{'checkpoint':101}]):
                third=scanner();third.run();self.assertFalse(third.error);self.assertEqual(third.nodes[str(path)].apparent,15000);self.assertEqual(third.index_info['strategy'],'incremental')
    def test_lost_events_force_full(self):
        self.file('data/a');db=self.state/'index.sqlite'
        with patch('soji_cli.index.native',return_value={'eventID':10}),patch('soji_cli.index.events',return_value=[{'flags':2,'path':str(self.home)},{'checkpoint':12}]):
            for i in range(2):
                s=IndexedScanner([str(self.home)],home=str(self.home),context=False,min_bytes=0,database=db);s.run();self.assertFalse(s.error);self.assertEqual(s.index_info['strategy'],'full')
    def test_incremental_recompute_preserves_unreadable_holds(self):
        scanner=IndexedScanner([str(self.home)],home=str(self.home),context=False,database=self.state/'index.sqlite')
        bad=str(self.home/'unreadable')
        scanner.nodes={str(self.home):Node(str(self.home),children=[bad]),bad:Node(bad,errors=1,own_errors=1,reason='Unreadable entry')}
        scanner.recompute()
        self.assertEqual(scanner.nodes[str(self.home)].errors,1)
    def test_verdict_fingerprint_expiry(self):
        store=IndexStore(self.state/'index.sqlite');store.save_verdict('/a','hash',{'levels':{}},100)
        self.assertIsNotNone(store.verdict('/a','hash',101));self.assertIsNone(store.verdict('/a','changed',101));self.assertIsNone(store.verdict('/a','hash',900000));store.close()

class MCPTests(Fixture):
    def server(self,run=True):
        return MCPServer({'roots':[str(self.home)],'home':str(self.home),'allocatedBytes':123,'findings':[]},self.state if run else None,hidden=[str(self.home/'hidden')])
    def test_protocol_and_all_tools(self):
        s=self.server();r=s.handle({'jsonrpc':'2.0','id':1,'method':'initialize'});self.assertEqual(r['result']['serverInfo']['name'],'soji')
        self.assertEqual(len(s.handle({'id':2,'method':'tools/list'})['result']['tools']),10)
    def test_hidden_symlink_and_outside_root(self):
        self.file('hidden/private');(self.home/'alias').symlink_to(self.home/'hidden',target_is_directory=True)
        s=self.server()
        for path in [str(self.home/'hidden'),str(self.home/'alias'),str(self.base)]:
            with self.assertRaises(ValueError):s.call('path_info',{'path':path})
    def test_invalid_output_rejected(self):
        with self.assertRaises(ValueError):validate({'findings':[{'path':'/a','confidence':2}]},SCHEMAS['submit_findings'])
        with self.assertRaises(ValueError):self.server().call('disk_summary',{'unexpected':True})
    def test_submission_once(self):
        s=self.server();s.call('submit_findings',{'findings':[]});self.assertTrue((self.state/'submission.json').exists())
        with self.assertRaises(ValueError):s.call('submit_findings',{'findings':[]})
    def test_snapshot_query_uses_aggregates(self):
        scan=self.scan();store=IndexStore(self.state/'index.sqlite');store.save(scan,1,'x');store.close()
        s=self.server();s.database=str(self.state/'index.sqlite');self.assertTrue(s.call('disk_summary',{})['largest'])

class CleanupTests(Fixture):
    def setup_plan(self):
        target=self.file('.cache/uv/data','x'*10000).parent
        now=time.time()+40*86400
        with patch('time.time',return_value=now),patch.object(Scanner,'collect_context',lambda self:None):
            s=self.scan();plan=create_plan(s,'balanced')
        self.assertEqual(len(plan['items']),1)
        return target,now,plan
    def test_trash_and_undo_roundtrip(self):
        target,now,plan=self.setup_plan();cleaner=Cleaner(self.state,context=False,trash_directory=self.base/'trash')
        with patch('time.time',return_value=now),patch.object(Scanner,'collect_context',lambda self:None):result=cleaner.apply(plan)
        self.assertEqual(result['completed'],1,result);self.assertFalse(target.exists())
        cleaner.undo(result['entries'][0]['id']);self.assertTrue((target/'data').exists())
    def test_permanent_fixture_removal(self):
        target,now,plan=self.setup_plan();plan['items'][0]['method']='permanent';from soji_cli.cleanup import digest
        plan.pop('digest');plan['digest']=digest(plan)
        with patch('time.time',return_value=now),patch.object(Scanner,'collect_context',lambda self:None):result=Cleaner(self.state,context=False).apply(plan,permanent=True)
        self.assertEqual(result['completed'],1,result);self.assertFalse(target.exists())
    def test_changed_file_and_parent_refused(self):
        target,now,plan=self.setup_plan();(target/'data').write_text('changed')
        with patch('time.time',return_value=now),patch.object(Scanner,'collect_context',lambda self:None):result=Cleaner(self.state,context=False).apply(plan)
        self.assertEqual(result['failed'],1);self.assertTrue(target.exists())
    def test_tampered_and_expired_plan(self):
        _,now,plan=self.setup_plan();plan['mode']='aggressive'
        with self.assertRaises(ValueError):validate_plan(plan)
    def test_symlinked_parent_refused(self):
        from soji_cli.cleanup import parent_fd
        self.file('actual/data');(self.home/'alias').symlink_to(self.home/'actual',target_is_directory=True)
        with self.assertRaises(OSError):parent_fd(self.home/'alias/data')

class AITests(Fixture):
    def test_agent_can_override_default_age_but_not_hard_holds(self):
        now=time.time();f=Finding(str(self.home/'cache'),100,100,1,now-86400,'App caches','Cache',tier='regenerable',list_only=False,comes_back='rebuilds',special_min_hours=336,default_holds=['Project default age'])
        self.assertFalse(f.decide('balanced',now)[0]);f.levels={'balanced':1};self.assertTrue(f.decide('balanced',now)[0]);f.holds=['Running'];self.assertFalse(f.decide('balanced',now)[0])
    def test_agent_nominated_cache_is_reverified_during_cleanup(self):
        target=self.file('random/caches/unknown-payload/data','x'*5000).parent
        now=time.time()+40*86400
        with patch('time.time',return_value=now),patch.object(Scanner,'collect_context',lambda self:None):
            s=self.scan();ai=AIAnalyzer(self.state)
            ai.apply(s,[{'path':str(target),'title':'Cache','group':'App caches','regenerable':True,'recommendation':'remove','comesBack':'rebuilds','confidence':0.9,'levels':{'careful':168,'balanced':24,'aggressive':1,'reason':'Fixture cache'}}])
            plan=create_plan(s,'balanced');self.assertEqual(len(plan['items']),1)
            result=Cleaner(self.state,context=False,trash_directory=self.base/'trash').apply(plan)
        self.assertEqual(result['completed'],1,result);self.assertFalse(target.exists())
    def test_all_presets_prepare_without_model_call(self):
        self.file('.cache/uv/data');scanner=self.scan()
        for preset in PRESETS:
            if preset['id']=='custom':continue
            ai=AIAnalyzer(self.state,preset=preset['id'])
            with patch.object(ai,'detect',return_value='/usr/bin/true'):
                run,argv,env=ai.prepare(scanner)
            self.assertEqual(argv[0],'/usr/bin/sandbox-exec');self.assertTrue((run/'prompt.md').exists())
            self.assertIn('(deny file-write* (literal '+json.dumps(str(run/'index.sqlite-wal'))+'))',(run/'sandbox.sb').read_text())
    def test_agent_cannot_remove_holds_or_personal_data(self):
        self.file('Documents/personal.txt');s=self.scan();f=s.findings[0];f.holds=['protected'];ai=AIAnalyzer(self.state)
        ai.apply(s,[{'path':f.path,'regenerable':True,'recommendation':'remove','levels':{'careful':0,'reason':'claimed'},'confidence':1}])
        self.assertIn('protected',f.holds);self.assertFalse(f.decide('aggressive',s.now)[0])
    def test_judgment_levels_are_cumulative(self):
        self.file('.cache/uv/data');s=self.scan();f=s.findings[0];AIAnalyzer(self.state).apply(s,[{'path':f.path,'recommendation':'remove','levels':{'careful':168,'balanced':200,'aggressive':300,'reason':'test'}}])
        self.assertEqual(f.levels['balanced'],168);self.assertEqual(f.levels['aggressive'],168)

if __name__=='__main__':unittest.main()
