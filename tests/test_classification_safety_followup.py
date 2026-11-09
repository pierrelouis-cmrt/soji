"""Follow-up controls for ecb4ece. Disposable paths and mocked inventories only."""
import dataclasses
import json
from pathlib import Path
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_nov8_regressions import FakeHome, write, age_tree, git
from corpus import hermetic
from soji_cli.ai import AIAnalyzer
from soji_cli.cleanup import Cleaner, create_plan, digest, file_identity
from soji_cli.engine import Scanner

class GenericReferences(FakeHome):
    def test_every_generic_marker_consumer_fails_closed_on_unknown(self):
        rules=self.scan().specialized
        consumers=[h for h in rules.scanner.catalog.hints if h.get('rule',{}).get('keepVersionPointedToBy') and h['id']!='nvm-versions']
        self.assertEqual(len(consumers),7)
        for hint in consumers:
            # Substitute literal disposable marker paths; the production handler
            # is shared by each real catalog consumer, with nvm separately tested.
            target=self.home/'families'/hint['id']/'1.0.0'
            target.mkdir(parents=True);(target.parent/'2.0.0').mkdir()
            marker=self.home/'markers'/hint['id'];marker.parent.mkdir(exist_ok=True)
            for variant in ('unreadable','invalid-utf8','oversized','malformed','empty','dangling','outside','loop'):
                with self.subTest(hint=hint['id'],variant=variant):
                    if variant=='dangling':marker.symlink_to(target.parent/'missing')
                    elif variant=='outside':marker.symlink_to(self.home)
                    elif variant=='loop':marker.symlink_to(marker)
                    else:
                        marker.write_bytes({'invalid-utf8':b'1\xff','oversized':b'1'*4096,'malformed':b'unknown layout\n','empty':b''}.get(variant,b'1.0.0'))
                    if variant=='unreadable':marker.chmod(0)
                    try:
                        self.assertIn('reference unknown',rules.active_reason(str(target),[str(marker)]))
                        self.assertIn('reference unknown',rules.active_reason(str(target.parent/'2.0.0'),[str(marker)]))
                    finally:
                        if variant=='unreadable':marker.chmod(0o600)
                        marker.unlink()
            with self.subTest(hint=hint['id'],variant='positive-controls'):
                self.assertIsNone(rules.active_reason(str(target),[str(marker)]))
                marker.write_text('1.0.0\n')
                self.assertIn('Active version:',rules.active_reason(str(target),[str(marker)]))
                self.assertIsNone(rules.active_reason(str(target.parent/'2.0.0'),[str(marker)]))
                marker.unlink();marker.symlink_to(target)
                self.assertIn('Active version:',rules.active_reason(str(target),[str(marker)]))
                self.assertIsNone(rules.active_reason(str(target.parent/'2.0.0'),[str(marker)]))
                marker.unlink()

    def test_ruby_marker_becomes_unknown_after_plan_preserves_runtime(self):
        for version,days in [('3.1.0',180),('3.2.0',120),('3.3.0',90)]:
            write(self.home/'.rbenv/versions'/version/'bin/ruby',age=days)
            age_tree(self.home/'.rbenv/versions'/version,days)
        marker=write(self.home/'.rbenv/version','3.2.0\n')
        target=self.home/'.rbenv/versions/3.1.0'
        scan=self.scan();plan=create_plan(scan,'aggressive',paths={str(target)})
        self.assertEqual(len(plan['items']),1)
        marker.chmod(0)
        try:
            with hermetic(str(self.home)):
                cleaner=Cleaner(self.home.parent/'state',trash_directory=self.home.parent/'trash')
                with self.assertRaisesRegex(ValueError,'reference unknown'):cleaner.fresh(plan['items'][0],plan)
                result=cleaner.apply(plan)
            self.assertEqual(result['completed'],0,result);self.assertTrue(target.exists())
        finally:marker.chmod(0o600)

class DeepOwnership(FakeHome):
    def test_partial_root_and_cached_old_plan_cannot_bypass_deep_install(self):
        owner=self.home/'.bun/install/global/node_modules/tool/vendor/a/b/c/d/e/f/g/h/i/j/k/pkg'
        write(owner/'package.json','{}');write(owner/'package-lock.json','{}');write(owner/'.gitignore','node_modules/\n')
        git(owner,'init','-q','-b','main');git(owner,'add','.');git(owner,'commit','-qm','fixture')
        payload=write(owner/'node_modules/dep/index.js');target=owner/'node_modules';age_tree(self.home,90)
        scan=self.scan([target]);f=scan.classify(scan.nodes[str(target)])
        self.assertEqual(scan.catalog.installs.containing(str(target))[0],str(self.home/'.bun/install/global'))
        for mode in ('careful','balanced','aggressive'):self.assertFalse(f.decide(mode,scan.now)[0])
        full=self.scan();plan=create_plan(full,'aggressive');plan['items']=[dict(path=str(target),identity=file_identity(target),size=f.size,newest=f.newest,files=f.files,hint='node-modules',group='Project dependencies',action={},method='trash',finding=dataclasses.asdict(f))]
        plan.pop('digest');plan['digest']=digest(plan)
        with hermetic(str(self.home)):
            cleaner=Cleaner(self.home.parent/'state',trash_directory=self.home.parent/'trash')
            # Mutable marker cache must not resurrect a pre-correction assumption.
            full.catalog.markers_cache[('installs.root',str(self.home/'.bun/install/global'))]=''
            cleaner._batch={'catalog':full.catalog}
            with self.assertRaises(ValueError):cleaner.fresh(plan['items'][0],plan)
            cleaner._batch=None
            result=cleaner.apply(plan)
        self.assertEqual(result['completed'],0,result);self.assertTrue(payload.exists())

class SessionJudgments(FakeHome):
    def build(self,hours,compound=False,sidecar=False):
        root=self.home/'.claude/projects/old'
        p=write(root/('orphan/subagents/a.jsonl' if sidecar else 'session.jsonl'),json.dumps({'cwd':str(self.home/'missing/project')})+'\n',hours/24)
        if compound:
            write(root/'session/subagents/a.jsonl','{}\n',hours/24)
            write(root/'session/tool-results/out.txt','unique result',hours/24)
        age_tree(root,hours/24)
        return p

    def test_normal_minima_survive_judgment_replay_and_forged_old_plans(self):
        for compound,sidecar,hours,mode in [(False,False,30,'balanced'),(True,False,30,'balanced'),(False,True,30,'careful')]:
            with self.subTest(compound=compound,sidecar=sidecar):
                # Each subcase gets its own home and separate fixture Trash.
                case=FakeHome();case.setUp();self.addCleanup(case.doCleanups)
                original_home=self.home;self.home=case.home
                try:p=self.build(hours,compound,sidecar)
                finally:self.home=original_home
                scan=case.scan();f=next(f for f in scan.findings if f.path==str(p));members=list(f.members)
                judgment={'path':str(p),'recommendation':'remove','levels':{'careful':1,'balanced':1,'aggressive':1}}
                ai=AIAnalyzer(case.home.parent/'state')
                ai.apply(scan,[judgment]);ai.apply(scan,[judgment])  # cached/replayed input
                f=next(f for f in scan.findings if f.path==str(p))
                self.assertEqual(f.members,members)
                self.assertFalse(f.decide(mode,scan.now)[0]);self.assertEqual(create_plan(scan,mode,paths={str(p)})['items'],[])
                # Historical plan with permissive agent levels, revalidated from live facts.
                plan=create_plan(scan,'aggressive',paths={str(p)});self.assertEqual(len(plan['items']),1)
                plan['mode']=mode;plan.pop('digest');plan['digest']=digest(plan)
                with hermetic(str(case.home)):
                    cleaner=Cleaner(case.home.parent/'state',trash_directory=case.home.parent/'trash')
                    with self.assertRaises(ValueError):cleaner.fresh(plan['items'][0],plan)
                    result=cleaner.apply(plan)
                self.assertEqual(result['completed'],0,result);self.assertTrue(p.exists())
                for member in members:self.assertTrue(Path(member['path']).exists())

    def test_older_compound_session_judgment_remains_usable(self):
        p=self.build(240,compound=True);scan=self.scan();f=next(f for f in scan.findings if f.path==str(p));members=list(f.members)
        AIAnalyzer(self.home.parent/'state').apply(scan,[{'path':str(p),'recommendation':'remove','levels':{'careful':1,'balanced':1,'aggressive':1}}])
        f=next(f for f in scan.findings if f.path==str(p));self.assertEqual(f.members,members)
        plan=create_plan(scan,'careful',paths={str(p)});self.assertEqual(len(plan['items']),1);self.assertEqual(len(plan['items'][0]['members']),3)
        with hermetic(str(self.home)):
            cleaner=Cleaner(self.home.parent/'state',trash_directory=self.home.parent/'trash')
            self.assertEqual(cleaner.fresh(plan['items'][0],plan),plan['items'][0]['identity'])
            result=cleaner.apply(plan)
        self.assertEqual(result['completed'],1,result)
        self.assertFalse(p.exists())
