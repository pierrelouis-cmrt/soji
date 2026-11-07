import dataclasses
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from soji_cli.engine import Catalog, Scanner, Finding, Node, glob_regex, within

class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent);self.home=Path(self.temp.name).resolve()
    def tearDown(self):self.temp.cleanup()
    def file(self,relative,size=8192):
        p=self.home/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'x'*size);return p
    def scan(self,**kw):
        s=Scanner([str(self.home)],home=str(self.home),min_bytes=0,context=False,**kw);s.run();self.assertFalse(s.error);return s
    def test_segment_glob(self):
        r=glob_regex('**/node_modules')
        self.assertTrue(r.fullmatch('node_modules'));self.assertTrue(r.fullmatch('/a/b/node_modules'))
        self.assertFalse(glob_regex('/a/*/Cache').fullmatch('/a/b/c/Cache'))
        self.assertTrue(glob_regex('/a/**/Cache').fullmatch('/a/Cache'))
    def test_exact_catalog_provenance(self):
        cat=Catalog(str(self.home));self.assertEqual(len(cat.hints),375);self.assertEqual(len(cat.groups),28)
    def test_marker_disambiguates_target(self):
        self.file('project/Cargo.toml');self.file('project/target/output')
        self.file('other/pom.xml');self.file('other/target/output')
        cat=Catalog(str(self.home))
        self.assertEqual(cat.match(str(self.home/'project/target'))[0]['id'],'cargo-target')
        self.assertEqual(cat.match(str(self.home/'other/target'))[0]['id'],'jvm-project-target')
        self.assertIsNone(cat.match(str(self.home/'unrelated/target')))
    def test_inside_marker(self):
        self.file('project/venv/pyvenv.cfg')
        cat=Catalog(str(self.home));self.assertEqual(cat.match(str(self.home/'project/venv'))[0]['id'],'python-venv')
    def test_hardlinks_and_symlinks(self):
        a=self.file('data/a',65536);os.link(a,self.home/'data/b');(self.home/'link').symlink_to(self.home/'data',target_is_directory=True)
        s=self.scan()
        self.assertEqual(sum(s.nodes[str(self.home/p)].size for p in ['data/a','data/b']),os.stat(a).st_blocks*512)
        self.assertEqual(s.nodes[str(self.home/'link')].reason,'Symlink; not followed')
        self.assertEqual(s.nodes[str(self.home/'data')].files,2)
        self.assertEqual(s.bytes,s.nodes[str(self.home)].size)
    def test_private_contents_are_not_traversed(self):
        secret=self.file('.ssh/key');s=self.scan()
        self.assertNotIn(str(secret),s.nodes)
        self.assertEqual(s.nodes[str(self.home/'.ssh')].size,0)
    def test_secrets_propagate_to_candidate(self):
        self.file('project/package.json');self.file('project/node_modules/lib/.env')
        s=self.scan();f=next(f for f in s.findings if f.hint_id=='node-modules')
        self.assertTrue(any('credential' in h for h in f.holds))
    def test_budget_never_marks_incomplete_ready(self):
        for i in range(20):self.file('cache/'+str(i))
        s=self.scan(max_files=4);self.assertTrue(s.limited)
        self.assertFalse(any(f.selected for f in s.decisions('strict')))
    def test_no_nested_double_count(self):
        self.file('.npm/_cacache/sub/a',32768);self.file('project/package.json');self.file('project/node_modules/a',32768)
        s=self.scan();paths=[f.path for f in s.findings if f.hint_id]
        self.assertTrue(any('_cacache' in p for p in paths))
        self.assertFalse(any(a!=b and within(a,b) for a in paths for b in paths))
        self.assertLessEqual(sum(f.size for f in s.findings),s.bytes)
    def test_deep_known_candidate_not_hidden_by_rollup(self):
        self.file('a/b/c/d/e/project/package.json');self.file('a/b/c/d/e/project/node_modules/output')
        s=self.scan();self.assertTrue(any(f.hint_id=='node-modules' for f in s.findings))
    def test_roots_deduplicated(self):
        self.file('a/data');s=Scanner([str(self.home),str(self.home/'a')],home=str(self.home));self.assertEqual(s.roots,[str(self.home)])
    def test_report_schema(self):
        self.file('a/data');s=self.scan();r=json.loads(json.dumps(s.report('smart')))
        self.assertEqual(r['format'],'soji/1');self.assertIn('findings',r)

class DecisionTests(unittest.TestCase):
    def f(self,days=8,**kw):
        return Finding('/test/cache',8192,8192,1,1000000000-days*86400,'Package caches','Cache',tier='regenerable',comes_back='rebuilds',list_only=False,**kw)
    def test_modes_cumulative(self):
        for days in [0.1,0.5,1,2,6,8,30]:
            f=self.f(days);result=[f.decide(m,1000000000)[0] for m in ['careful','balanced','aggressive']]
            self.assertEqual(result,sorted(result))
    def test_smart_original_rule(self):
        f=self.f(10,rule={'untouchedDays':14})
        f.special_min_hours=14*24;self.assertFalse(f.decide('balanced',1000000000)[0]);f.newest-=7*86400;self.assertTrue(f.decide('balanced',1000000000)[0])
    def test_project_rule(self):
        f=self.f(2,rule={'projectUntouchedDays':14},project_idle_hours=15*24)
        self.assertTrue(f.decide('balanced',1000000000)[0]);f.holds.append('Project used within 14 days');self.assertFalse(f.decide('balanced',1000000000)[0])
    def test_holds_and_personal_data_never_auto_selected(self):
        for mode in ['careful','balanced','aggressive']:
            self.assertFalse(self.f(30,holds=['Running']).decide(mode,1000000000)[0])
            f=self.f(30);f.tier='userData';self.assertFalse(f.decide(mode,1000000000)[0])
    def test_mode_change_uses_newest_descendant(self):
        f=self.f(0.01);self.assertFalse(f.decide('strict',1000000000)[0])
    def test_low_cost_and_costly_not_equivalent(self):
        f=self.f(30);f.tier='costly'
        self.assertFalse(f.decide('safe',1000000000)[0]);self.assertTrue(f.decide('strict',1000000000)[0])

if __name__=='__main__':unittest.main()
