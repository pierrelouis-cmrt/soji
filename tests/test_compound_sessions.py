"""Compound Claude session cleanup on disposable temp homes only (never ~/.claude)."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from soji_cli.cleanup import Cleaner,create_plan,digest,validate_plan
from soji_cli.engine import Scanner

OLD=10*86400


class CompoundSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='soji-sessions-');self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name).resolve()/'home';self.home.mkdir()
        self.trash=self.home/'.Trash';self.state=Path(self.tmp.name).resolve()/'state'
        self.proj=self.home/'.claude/projects/-code-x';(self.home/'code/x').mkdir(parents=True)
        self.transcript=self.write('sess.jsonl',json.dumps({'cwd':str(self.home/'code/x'),'timestamp':'2020-01-01T00:00:00Z'})+'\n')
        self.subagents=self.write('sess/subagents/agent.jsonl','{}\n').parent
        self.tool_results=self.write('sess/tool-results/out.txt','tool output').parent
        self.memory=self.write('memory/MEMORY.md','keep me').parent
        self.age(self.home,OLD)
        context=patch.object(Scanner,'collect_context',lambda self:None);context.start();self.addCleanup(context.stop)
        self.cleaner=Cleaner(self.state,context=False,trash_directory=self.trash)
    def write(self,rel,text):
        p=self.proj/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p
    def age(self,root,seconds):
        stamp=time.time()-seconds
        for d,dirs,files in os.walk(root,topdown=False):
            for n in files+dirs:os.utime(os.path.join(d,n),(stamp,stamp),follow_symlinks=False)
        os.utime(root,(stamp,stamp))
    def scan(self):
        s=Scanner([str(self.home)],home=str(self.home),context=False,min_bytes=0);s.run();self.assertFalse(s.error);return s
    def session(self,s):
        return next(f for f in s.findings if f.hint_id=='claude-sessions' and f.path==str(self.transcript))
    def plan(self,mode='careful',method='trash'):
        p=create_plan(self.scan(),mode,method=method);self.assertEqual(len(p['items']),1,p['items']);return p

    def test_row_measures_members_once_and_excludes_memory(self):
        s=self.scan();f=self.session(s)
        self.assertEqual([m['path'] for m in f.members],[str(self.transcript),str(self.subagents),str(self.tool_results)])
        self.assertEqual(f.size,sum(s.nodes[m['path']].size for m in f.members))
        self.assertEqual(f.files,3)
        rows=[g for g in s.findings if g.hint_id=='claude-sessions']
        self.assertEqual(len(rows),1,'sidecar JSONL must not also be its own row')
        self.assertFalse(any('memory' in m['path'] for g in s.findings for m in g.members))
        self.assertTrue(f.decide('careful',time.time())[0])
    def test_members_cleaned_together_and_undone(self):
        p=self.plan();item=p['items'][0];validate_plan(p)
        self.assertEqual(len(item['members']),3);self.assertTrue(all(m['identity'] for m in item['members']))
        result=self.cleaner.apply(p);e=result['entries'][0]
        self.assertEqual((result['completed'],result['failed'],result['partial']),(1,0,0),e)
        self.assertEqual(e['status'],'done');self.assertEqual(len(e['members']),3)
        for path in (self.transcript,self.subagents,self.tool_results):self.assertFalse(path.exists())
        self.assertEqual((self.memory/'MEMORY.md').read_text(),'keep me');self.assertTrue((self.proj/'sess').is_dir())
        self.assertEqual(len(self.cleaner.entries()),1,'one journal entry per session')
        self.cleaner.undo(e['id'])
        self.assertTrue(self.transcript.exists());self.assertEqual((self.tool_results/'out.txt').read_text(),'tool output')
        self.assertTrue((self.subagents/'agent.jsonl').exists())
        self.assertEqual(self.cleaner.entries()[0]['status'],'restored')
    def test_permanent_removes_every_member(self):
        result=self.cleaner.apply(self.plan(method='permanent'),permanent=True)
        self.assertEqual(result['completed'],1,result)
        for path in (self.transcript,self.subagents,self.tool_results):self.assertFalse(path.exists())
        self.assertTrue(self.memory.exists())
    def test_recent_member_retains_whole_session(self):
        self.age(self.subagents,3600)  # newest member is 1 h old
        f=self.session(self.scan())
        for mode in ('careful','balanced','aggressive'):self.assertFalse(f.decide(mode,time.time())[0],mode)
        (self.tool_results/'out.txt').write_text('active now')
        f=self.session(self.scan())
        self.assertIn('Changed or created within the last 5 minutes',f.holds)
    def test_activity_on_a_sidecar_counts(self):
        from soji_cli.activity import ActivityIndex
        hit=type('Activity',(),{'at':time.time()-1800,'source':'fixture'})()
        with patch.object(ActivityIndex,'last',lambda index,path,**kw:hit if path==str(self.tool_results) else None):
            f=self.session(self.scan())
        self.assertEqual(f.last_activity,hit.at)
        self.assertFalse(f.decide('aggressive',time.time())[0])
    def test_member_changed_after_planning_refused(self):
        p=self.plan()
        (self.tool_results/'out.txt').write_text('changed after planning, longer');self.age(self.tool_results,OLD)
        result=self.cleaner.apply(p);e=result['entries'][0]
        self.assertEqual(result['failed'],1);self.assertEqual(e['status'],'failed')
        self.assertRegex(e['error'],'changed')
        for path in (self.transcript,self.subagents,self.tool_results):self.assertTrue(path.exists())
    def test_member_added_after_planning_refused(self):
        import shutil
        shutil.rmtree(self.tool_results);p=self.plan();self.assertEqual(len(p['items'][0]['members']),2)
        self.write('sess/tool-results/new.txt','new');self.age(self.proj/'sess',OLD);self.age(self.proj,OLD)
        result=self.cleaner.apply(p);e=result['entries'][0]
        self.assertEqual(e['status'],'failed');self.assertTrue(self.transcript.exists())
    def test_standalone_subagent_becoming_compound_is_refused(self):
        self.transcript.unlink()
        p=self.plan();self.assertEqual(p['items'][0]['path'],str(self.subagents/'agent.jsonl'))
        self.transcript.write_text('{}\n')
        result=self.cleaner.apply(p)
        self.assertEqual(result['failed'],1)
        self.assertIn('membership changed',result['entries'][0]['error'])
        self.assertTrue((self.subagents/'agent.jsonl').exists())
    def test_scoped_verification_preserves_catalog_policy(self):
        p=self.plan();original=Scanner._build_findings;captured=[]
        def build(scan):
            original(scan)
            captured.append([(f.path,f.levels,f.holds,f.members,f.action) for f in scan.findings if f.path==str(self.transcript)])
        def whole(cleaner,scan,path,root,hint):scan.visit(root)
        with patch.object(Scanner,'_build_findings',build):
            self.cleaner.fresh(p['items'][0],p)
            with patch.object(Cleaner,'measure_catalog_target',whole):self.cleaner.fresh(p['items'][0],p)
        self.assertEqual(captured[0],captured[1])
    def test_tampered_members_rejected(self):
        p=self.plan();p['items'][0]['members'].append(dict(p['items'][0]['members'][1],path=str(self.memory)))
        p.pop('digest');p['digest']=digest(p)
        with self.assertRaisesRegex(ValueError,'members'):validate_plan(p)
        self.assertTrue(self.memory.exists())
    def test_partial_failure_reported_as_partial(self):
        p=self.plan();real=Cleaner.move
        def failing(cleaner,rec,*a):
            if rec['path']==str(self.transcript):rec.update(status='failed',error='injected failure');return False
            return real(cleaner,rec,*a)
        with patch.object(Cleaner,'move',failing):result=self.cleaner.apply(p)
        e=result['entries'][0]
        self.assertEqual((result['completed'],result['partial'],result['failed']),(0,1,1))
        self.assertEqual(e['status'],'partial');self.assertTrue(e['partial']);self.assertIn('2 of 3',e['error'])
        self.assertIn('injected failure',e['error'])
        self.assertTrue(self.transcript.exists());self.assertFalse(self.subagents.exists())
        self.assertEqual(self.cleaner.entries()[0]['status'],'partial')
        self.cleaner.undo(e['id']);self.assertTrue(self.subagents.exists());self.assertTrue(self.tool_results.exists())
    def test_first_member_failure_stops_and_moves_nothing(self):
        p=self.plan()
        def failing(cleaner,rec,*a):rec.update(status='failed',error='injected failure');return False
        with patch.object(Cleaner,'move',failing):result=self.cleaner.apply(p)
        e=result['entries'][0];self.assertEqual(e['status'],'failed')
        self.assertEqual([m['status'] for m in e['members']],['skipped','failed','skipped'])
        for path in (self.transcript,self.subagents,self.tool_results):self.assertTrue(path.exists())


if __name__=='__main__':unittest.main()
