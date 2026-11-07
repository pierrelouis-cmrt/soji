import json
import os
from pathlib import Path
import plistlib
import sqlite3
import time
import unittest
from unittest.mock import patch
from test_core_v2 import Fixture
from soji_cli.engine import Finding,Scanner
from soji_cli.specialized import DeviceCatalog
from soji_cli.commands import CommandPolicy
from soji_cli.routines import Routines,auto_clean_plan
from soji_cli.nativeplans import versions_plan,runtimes_plan
from soji_cli.cleanup import validate_plan
from soji_cli.activity import ActivityIndex

class AdvancedRules(Fixture):
    def test_specific_cache_not_hidden_by_app_leftovers(self):
        self.file('Library/Application Support/Example/Cache/blob')
        self.file('Library/Application Support/Example/Code Cache/blob')
        s=self.scan()
        self.assertTrue(any('Cache' in f.path and f.path.endswith(('Cache','Code Cache')) for f in s.findings),[f.path for f in s.findings])
    def test_case_glob_does_not_cross_separator_with_question(self):
        from soji_cli.engine import glob_regex
        self.assertFalse(glob_regex('/a/*?*/Cache').fullmatch('/a/b/c/Cache'))
    def test_careful_download_default_can_be_judged(self):
        now=time.time();f=Finding('/a',100,100,1,now-40*86400,'Package caches','Downloads',tier='regenerable',list_only=False,comes_back='downloads')
        self.assertFalse(f.decide('careful',now)[0]);f.levels={'careful':168,'balanced':24,'aggressive':1};self.assertTrue(f.decide('careful',now)[0])
    def test_newest_device_build_connected(self):
        self.file('Library/Developer/Xcode/iOS DeviceSupport/18.0 (22A100)/data')
        s=self.scan();f=next(f for f in s.findings if f.hint_id=='xcode-ios-device-support')
        devices=DeviceCatalog(str(self.home),{'devices':{},'runtimes':[],'connectedBuilds':['22A100']}).build()
        sp=self.special(s,devices)
        with patch.object(devices,'connected',return_value=True):sp.evaluate(f)
        self.assertIn('A connected device uses this build',f.holds)
    def test_grouping_major_and_product(self):
        self.file('tmp/data');s=self.scan();sp=self.special(s)
        self.assertEqual(sp.grouping('/sdk/build-tools/35.0.0','major'),sp.grouping('/sdk/build-tools/35.0.1','major'))
        self.assertNotEqual(sp.grouping('/sdk/build-tools/34.0.0','major'),sp.grouping('/sdk/build-tools/35.0.1','major'))
        self.assertEqual(sp.grouping('/tools/chrome-120','product'),sp.grouping('/tools/chrome-121','product'))
    def test_session_parts_and_memory_exclusion(self):
        self.file('.claude/projects/proj/one.jsonl',json.dumps({'cwd':str(self.home/'project'),'timestamp':'2020-01-01T00:00:00Z'})+'\n')
        self.file('.claude/projects/proj/memory/private.txt')
        self.file('.claude/projects/proj/one/subagents/agent.jsonl','{}\n')
        s=self.scan();parts=[f for f in s.findings if f.hint_id=='claude-sessions']
        self.assertEqual(len(parts),2);self.assertTrue(all(f.managed for f in parts));self.assertFalse(any('private' in f.path for f in parts))
    def test_configured_cache_root_without_shell_execution(self):
        from soji_cli.locations import cache_locations
        self.file('.zshrc','export UV_CACHE_DIR="$HOME/custom-cache"\nexport PIP_CACHE_DIR="$(touch /tmp/never-run)"\n')
        locations=cache_locations(str(self.home),{})
        self.assertIn(('uv-cache',str(self.home/'custom-cache'),'UV_CACHE_DIR'),locations)
        self.assertFalse(any(h=='pip-cache' for h,p,s in locations))
    def test_open_files_within_symlinked_cache_are_not_followed(self):
        self.file('.cache/uv/data');outside=self.file('source/private')
        (self.home/'.cache/uv/link').symlink_to(outside)
        s=self.scan();f=next(f for f in s.findings if f.hint_id=='uv-cache')
        self.assertFalse(any('excluded' in h for h in f.holds))

class NativeCatalogTests(Fixture):
    def test_document_plan_preserves_newest_and_conflicts(self):
        doc=self.file('Documents/report.txt')
        catalog={'versions':[{'url':'/versions/new','modified':300,'retained':True},{'url':'/versions/conflict','modified':200,'retained':True},{'url':'/versions/old','modified':100,'retained':False},{'url':'/versions/older','modified':50,'retained':False}]}
        with patch('soji_cli.nativeplans.document_versions',return_value=catalog):plan=versions_plan(doc,str(self.home))
        self.assertEqual(len(plan['items']),2);validate_plan(plan)
    def test_runtime_plan_preserves_newest_and_booted(self):
        old=self.file('runtimes/old.dmg');new=self.file('runtimes/new.dmg')
        base={'runtimeIdentifier':'ios','deletable':True,'state':'Ready','lastUsedAt':time.time()-30*86400,'sizeBytes':10}
        catalog={'available':True,'images':{'images':{'old':dict(base,path=str(old),identifier='old',build='22A100'),'new':dict(base,path=str(new),identifier='new',build='22A200')}},'devices':{'devices':{'ios':[{'state':'Shutdown'}]}}}
        plan=runtimes_plan(str(self.home),catalog);self.assertEqual(len(plan['items']),1);self.assertEqual(plan['items'][0]['action']['identifier'],'old')
        catalog['devices']['devices']['ios'][0]['state']='Booted';self.assertFalse(runtimes_plan(str(self.home),catalog)['items'])

class CommandTests(Fixture):
    def test_exact_command_and_scope_enforced(self):
        action={'kind':'official-command','hint':'npm-cache','argv':['npm','cache','clean','--force']}
        home=str(Path.home());target=str(Path(home)/'.npm/_cacache')
        with patch('soji_cli.commands.shutil.which',return_value='/fake/npm'),patch('soji_cli.commands.command',return_value=(0,str(Path(home)/'.npm')+'\n','')):
            self.assertEqual(CommandPolicy().bound(action,target,home)[0],'/fake/npm')
            with self.assertRaises(ValueError):CommandPolicy().bound(action,str(Path(home)/'other'),home)
        action['argv'].append('--unexpected')
        with self.assertRaises(ValueError):CommandPolicy().bound(action,target,home)
    def test_all_eleven_recovered_commands_present(self):
        self.assertEqual(sum(bool(h.get('cleanCommand')) for h in CommandPolicy().hints.values()),11)

class RoutineTests(Fixture):
    def test_disabled_and_due(self):
        r=Routines(self.state);routine={'id':'test','paths':[str(self.home)],'enabled':False,'everyHours':24}
        r.save(routine);self.assertFalse(r.due(routine));routine['enabled']=True;self.assertTrue(r.due(routine));routine['lastRun']=time.time();self.assertFalse(r.due(routine))
    def test_auto_mode_off_by_default(self):
        self.assertEqual(auto_clean_plan(self.scan(),{}),{'skipped':'Auto mode is disabled'})


class CalendarTests(Fixture):
    def test_weekly_and_month_end_schedule(self):
        import datetime as dt
        r=Routines(self.state)
        now=dt.datetime(2026,2,28,12).timestamp()
        routine={'enabled':True,'lastRun':dt.datetime(2026,2,1).timestamp(),'schedule':{'repeats':'monthly','day':31,'hour':10,'minute':0}}
        self.assertTrue(r.due(routine,now));routine['lastRun']=now;self.assertFalse(r.due(routine,now+1))
    def test_clock_backwards_prevents_duplicate(self):
        self.assertFalse(Routines(self.state).due({'enabled':True,'lastRun':200},100))

class UninstallTests(Fixture):
    def test_explicit_app_plan_and_system_refusal(self):
        from soji_cli.uninstall import uninstall_plan
        from soji_cli.apps import AppCatalog
        appdir=self.home/'Applications/Example.app';(appdir/'Contents').mkdir(parents=True)
        self.file('Library/Application Support/Example/data')
        app={'path':str(appdir),'bundle':'co.example.App','name':'Example','version':'1'}
        def build(cat):cat.apps=[app];cat.running=[];return cat
        with patch.object(AppCatalog,'build',build):
            plan=uninstall_plan('co.example.App',str(self.home))
            self.assertEqual(len(plan['items']),2);validate_plan(plan)
            app['bundle']='com.apple.Example'
            with self.assertRaises(ValueError):uninstall_plan('com.apple.Example',str(self.home))

class RecoveryTests(Fixture):
    def test_interrupted_trash_move_can_be_reconciled_and_undone(self):
        from soji_cli.cleanup import Cleaner,file_identity
        target=self.file('data/original');before=file_identity(target)
        trash=self.base/'trash';trash.mkdir();destination=trash/'moved'
        cleaner=Cleaner(self.state)
        cleaner.append({'id':'interrupted','path':str(target),'identity':before,'method':'trash','status':'prepared','trashedTo':str(destination)})
        target.rename(destination)
        self.assertTrue(cleaner.recover()[0]['recoverableTrashMove']);cleaner.recover(apply=True)
        cleaner.undo('interrupted');self.assertTrue(target.exists())

class WorktreeTests(Fixture):
    def test_real_git_dirty_unmerged_and_unpushed(self):
        from soji_cli.gitstate import GitInspector
        import subprocess
        repo=self.home/'repo';repo.mkdir()
        def git(*args):return subprocess.run(['/usr/bin/git','-C',str(repo),*args],check=True,capture_output=True,text=True)
        git('init','-b','main');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture')
        (repo/'source').write_text('one');git('add','source');git('commit','-m','fixture')
        remote=self.base/'remote.git';subprocess.run(['/usr/bin/git','init','--bare',str(remote)],check=True,capture_output=True)
        git('remote','add','origin',str(remote));git('push','-u','origin','main')
        work=self.home/'agent';git('worktree','add','--detach',str(work))
        state=GitInspector().inspect(str(work),worktree=True)
        self.assertFalse(state['dirty']);self.assertFalse(state['unmerged']);self.assertFalse(state['unpushed'])
        (work/'source').write_text('changed');state=GitInspector().inspect(str(work),worktree=True);self.assertTrue(state['dirty'])
        from soji_cli.cleanup import Cleaner
        action={'kind':'git-worktree','repository':str(repo),'path':str(work)}
        with self.assertRaises(ValueError):Cleaner(self.state).tool_action(action)
        subprocess.run(['/usr/bin/git','-C',str(work),'restore','source'],check=True,capture_output=True)
        Cleaner(self.state).tool_action(action);self.assertFalse(work.exists())

if __name__=='__main__':unittest.main()
