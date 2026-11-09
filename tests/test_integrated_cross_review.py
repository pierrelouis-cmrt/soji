"""Independent exact-head proofs. Only disposable fake homes/state/Trash; inventories mocked.

Safe-expectation tests intentionally fail where the integrated head is unsafe.
All host inventories and native calls are mocked by corpus.hermetic.
"""
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / 'tests')]
from corpus import hermetic
from test_nov8_regressions import FakeHome, write, age_tree, git
from test_version_policy_context import Fixture
from soji_cli.cleanup import Cleaner, create_plan
from soji_cli.ai import AIAnalyzer
from soji_cli.specialized import ProjectPins
from soji_cli.engine import Scanner

class CrossReview(FakeHome):
    def test_unreadable_global_ruby_marker_must_hold_current(self):
        for v, days in [('3.1.0',180),('3.2.0',120),('3.3.0',90)]:
            write(self.home / '.rbenv/versions' / v / 'bin/ruby', age=days)
            age_tree(self.home / '.rbenv/versions' / v, days)
        marker = write(self.home / '.rbenv/version', '3.1.0\n', 200)
        # Positive reference works before its readability becomes unknown.
        s = self.scan()
        target = str(self.home / '.rbenv/versions/3.1.0')
        self.assertFalse(next(f for f in s.decisions('aggressive') if f.path == target).selected)
        marker.chmod(0)
        self.addCleanup(marker.chmod, 0o600)
        with self.assertRaises(PermissionError): marker.read_text()
        s = self.scan()
        plan = create_plan(s, 'aggressive', paths={target})
        if plan['items']:
            with hermetic(str(self.home)):
                cleaner = Cleaner(self.home.parent/'state', trash_directory=self.home.parent/'trash')
                identity = cleaner.fresh(plan['items'][0], plan)
                self.assertEqual(identity, plan['items'][0]['identity'])
                result=cleaner.apply(plan)
                self.assertEqual(result['completed'],1,result)
                self.assertFalse(Path(target).exists())
                self.assertTrue(any((self.home.parent/'trash').iterdir()))
        self.assertFalse(bool(plan['items']), 'Current Ruby version moved to disposable Trash despite unreadable global marker')

    def test_unknown_session_identity_agent_must_keep_normal_threshold(self):
        import json
        p = write(self.home / '.claude/projects/old/session.jsonl', json.dumps({'cwd':str(self.home/'projects/missing')})+'\n', 30/24)
        s = self.scan()
        f = next(f for f in s.findings if f.path == str(p))
        self.assertEqual(f.levels['balanced'],48)
        self.assertFalse(f.decide('balanced',time.time())[0])
        AIAnalyzer(self.home.parent/'state').apply(s,[{'path':str(p),'recommendation':'remove','levels':{'careful':1,'balanced':1,'aggressive':1}}])
        plan=create_plan(s,'balanced',paths={str(p)})
        if plan['items']:
            with hermetic(str(self.home)):
                cleaner=Cleaner(self.home.parent/'state',trash_directory=self.home.parent/'trash')
                self.assertEqual(cleaner.fresh(plan['items'][0],plan),plan['items'][0]['identity'])
        self.assertFalse(bool(plan['items']),'Unknown historical identity session at 30 h became selected AND fresh accepted under agent judgment')

class AgentSidecar(CrossReview):
    # Do not inherit the two original proof tests into this class.
    test_unreadable_global_ruby_marker_must_hold_current = None
    test_unknown_session_identity_agent_must_keep_normal_threshold = None
    def test_agent_sidecar_plan_is_conservatively_refused_fresh(self):
        p=write(self.home/'.claude/projects/old/orphan/subagents/agent.jsonl','{}\n',30/24)
        s=self.scan();f=next(f for f in s.findings if f.path==str(p))
        self.assertEqual(f.levels['careful'],72)
        AIAnalyzer(self.home.parent/'state').apply(s,[{'path':str(p),'recommendation':'remove','levels':{'careful':1,'balanced':1,'aggressive':1}}])
        plan=create_plan(s,'careful',paths={str(p)})
        self.assertEqual(len(plan['items']),0)
        self.assertTrue(p.exists())
    def test_agent_cannot_lower_24h_floor(self):
        p=write(self.home/'.claude/projects/old/young.jsonl','{}\n',20/24)
        s=self.scan()
        AIAnalyzer(self.home.parent/'state').apply(s,[{'path':str(p),'recommendation':'remove','levels':{'careful':0,'balanced':0,'aggressive':0}}])
        f=next(f for f in s.findings if f.path==str(p))
        for mode in ('careful','balanced'):
            self.assertFalse(f.decide(mode,time.time())[0])

class PinParity(unittest.TestCase):
    def fixture(self):
        f=Fixture(); f.setUp(); self.addCleanup(f.doCleanups); return f
    def test_full_walk_mount_and_depth_gaps_hold(self):
        f=self.fixture()
        # Real walk flags, synthetic mount device argument (no actual mounts).
        for depth, device in [(128,None),(0,-1)]:
            s=Scanner([str(f.home)],home=str(f.home),context=False,min_bytes=0)
            s.started=time.monotonic();s.visit(str(f.home),depth,device)
            pins=ProjectPins().from_nodes(s)
            self.assertIn('incomplete',pins.hold(f.path('v18.20.0'),'node'))
    def test_live_mount_gap_holds(self):
        f=self.fixture(); original=os.lstat
        external=f.home/'code'
        def lstat(p,*a,**kw):
            st=original(p,*a,**kw)
            if str(p)==str(external):
                values=list(st);values[2]=st.st_dev+1;return os.stat_result(values)
            return st
        with patch('soji_cli.specialized.os.lstat',lstat):
            pins=ProjectPins().discover([str(f.home)],lambda p:'')
        self.assertIn('incomplete',pins.hold(f.path('v18.20.0'),'node'))
    def test_extra_plan_root_new_pin(self):
        f=self.fixture(); extra=f.home.parent/'external-project';extra.mkdir()
        s=f.scan([f.home,extra]);plan=create_plan(s,'aggressive',paths={f.path('v18.20.0')})
        self.assertEqual(len(plan['items']),1)
        (extra/'.nvmrc').write_text('18.20.0\n')
        f.refuses(plan,'Version pinned by a project')
    def test_symlink_pin_is_resolved_live_and_conservatively_held_in_walk(self):
        f=self.fixture();p=f.write('elsewhere/pin','18.20.0\n')
        (f.home/'code/app/.nvmrc').symlink_to(p)
        self.assertTrue(f.holds('v18.20.0'))
        pins=ProjectPins().discover([str(f.home)],lambda p:'')
        self.assertIn('Version pinned',pins.hold(f.path('v18.20.0'),'node'))


class DeepInstall(FakeHome):
    def test_deep_installed_local_vcs_and_lock_cannot_override_install(self):
        install=self.home/'.bun/install/global'
        owner=install/'node_modules/tool/vendor/a/b/c/d/e/f/g/h/i/j/k/pkg'
        write(owner/'package.json','{}');write(owner/'package-lock.json','{}')
        write(owner/'.gitignore','node_modules/\n')
        git(owner,'init','-q','-b','main');git(owner,'add','.');git(owner,'commit','-qm','fixture')
        write(owner/'node_modules/dep/index.js')
        age_tree(self.home,90)
        s=self.scan();target=str(owner/'node_modules')
        plan=create_plan(s,'aggressive',paths={target})
        if plan['items']:
            with hermetic(str(self.home)):
                cleaner=Cleaner(self.home.parent/'state',trash_directory=self.home.parent/'trash')
                self.assertEqual(cleaner.fresh(plan['items'][0],plan),plan['items'][0]['identity'])
        self.assertFalse(bool(plan['items']),'Deep shipped dependencies override explicit global install exclusion using local VCS and lockfile; fresh accepts')

if __name__=='__main__':unittest.main()
