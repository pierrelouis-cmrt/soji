"""Regression fixtures for index contracts; all mutations are disposable."""
import dataclasses
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from soji_cli.engine import Node, Scanner, within
from soji_cli.index import IndexStore, IndexedScanner, INDEX_DEFAULTS
from soji_cli.locations import cache_locations


class IndexRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='soji-index-')
        self.base=Path(self.tmp.name).resolve();self.root=self.base/'root';self.root.mkdir()
        self.database=self.base/'state/index.sqlite'
    def tearDown(self):self.tmp.cleanup()
    def model(self, sizes=None, complete=True):
        nodes={str(self.root):Node(str(self.root),size=100)}
        for name,size in (sizes or {'cache':10}).items():
            p=str(self.root/name);nodes[p]=Node(p,size=size)
        if not complete:nodes[str(self.root)].own_errors=1
        return SimpleNamespace(nodes=nodes,roots=[str(self.root)],limited=False,cancel=threading.Event(),error='')
    def scanner(self):
        return IndexedScanner([str(self.root)],home=str(self.root),database=self.database,context=False,min_bytes=0)
    def run_scan(self, event_id=100, changes=None):
        s=self.scanner()
        with patch.object(Scanner,'collect_context',lambda _:None),patch.object(Scanner,'_build_findings',lambda _:None),patch('soji_cli.index.native',return_value={'eventID':event_id}),patch('soji_cli.index.events',return_value=changes if changes is not None else [{'checkpoint':event_id}]):
            s.run()
        self.assertFalse(s.error,s.error);return s
    def test_legacy_verdict_schema_migrates_without_losing_strict_hash_gate(self):
        import sqlite3
        self.database.parent.mkdir(parents=True)
        with sqlite3.connect(self.database) as db:
            db.execute('CREATE TABLE verdicts(path TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,judged_at REAL NOT NULL,data TEXT NOT NULL)')
            db.execute('INSERT INTO verdicts VALUES(?,?,?,?)',('/fixture','hash',100,'{"levels":{}}'))
        db.close()
        store=IndexStore(self.database)
        try:
            self.assertEqual(store.verdict_record('/fixture'),{'fingerprint':'hash','judgedAt':100,'data':{'levels':{}},'content':None})
            self.assertIsNone(store.verdict('/fixture','different',101))
            self.assertIsNotNone(store.verdict('/fixture','hash',101))
            self.assertIsNone(store.verdict('/fixture','hash',100+7*86400))
            content={'sizeBytes':10,'newestChange':20,'fileCount':1,'identity':{'device':1,'inode':2,'type':32768,'parentDevice':1,'parentInode':3}}
            store.save_verdict('/new','new-hash',{'levels':{}},101,content=content)
            self.assertEqual(store.verdict_record('/new')['content'],content)
            self.assertIsNone(store.verdict_record('/missing'))
            store.save_verdict('/new','other-hash',{},102)
            self.assertIsNone(store.verdict_record('/new')['content'])
        finally:store.close()
    def test_index_defaults(self):
        self.assertEqual(INDEX_DEFAULTS['fullCheckInterval'],7*86400)
        self.assertEqual(INDEX_DEFAULTS['snapshotDays'],60)
        self.assertEqual(INDEX_DEFAULTS['rollUpBytes'],50_000_000)
    def test_daily_snapshot_is_first_complete_scan_and_growth_is_live(self):
        store=IndexStore(self.database)
        try:
            store.save(self.model(),1,'s')
            store.save(self.model({'cache':35,'new':20}),2,'s',full_scan=False)
            snapshot=dict(store.db.execute('SELECT path,bytes FROM snapshots'))
            self.assertEqual(snapshot[str(self.root/'cache')],10)
            self.assertNotIn(str(self.root/'new'),snapshot)
            growth=store.growth()
            self.assertEqual([(Path(r['path']).name,r['delta']) for r in growth],[('cache',25),('new',20)])
        finally:store.close()
    def test_partial_scan_does_not_poison_snapshot(self):
        store=IndexStore(self.database)
        try:
            store.save(self.model(complete=False),1,'s')
            self.assertFalse(store.meta('complete'));self.assertEqual(store.db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0],0)
            self.assertIsNone(store.meta('fullCheckedAt'))
            store.save(self.model(),2,'s');self.assertTrue(store.meta('complete'))
        finally:store.close()
    def test_incremental_save_does_not_postpone_full_check(self):
        store=IndexStore(self.database)
        try:
            with patch('soji_cli.index.time.time',return_value=1_700_000_000):store.save(self.model(),1,'s')
            with patch('soji_cli.index.time.time',return_value=1_700_100_000):store.save(self.model(),2,'s',full_scan=False)
            self.assertEqual(store.meta('fullCheckedAt'),1_700_000_000)
            self.assertEqual(store.meta('updatedAt'),1_700_100_000)
        finally:store.close()
    def test_retention_is_sixty_days(self):
        store=IndexStore(self.database)
        try:
            now=time.time()
            for age in (40,61):
                day=time.strftime('%Y-%m-%d',time.localtime(now-age*86400))
                store.db.execute('INSERT INTO snapshots VALUES(?,?,?)',(day,'/fixture',age))
            store.save(self.model(),1,'s')
            self.assertEqual(store.db.execute("SELECT bytes FROM snapshots WHERE path='/fixture'").fetchall(),[(40,)])
        finally:store.close()
    def test_growth_requested_day_and_earliest_fallback(self):
        store=IndexStore(self.database)
        try:
            store.save(self.model({'cache':50}),1,'s')
            store.db.execute('INSERT INTO snapshots VALUES(?,?,?)',('2000-01-01',str(self.root/'cache'),5));store.db.commit()
            self.assertEqual(store.growth(since=0)[0]['delta'],45)
            self.assertEqual(store.growth(since=1_000_000_000)[0]['delta'],45)
        finally:store.close()
    def test_actual_incremental_rescan_and_hardlink_reassignment(self):
        a=self.root/'a';b=self.root/'b';a.mkdir();b.mkdir()
        first=a/'file';second=b/'link';first.write_bytes(b'x'*16384);os.link(first,second)
        initial=self.run_scan();self.assertEqual(initial.index_info['strategy'],'full')
        first.unlink()
        updated=self.run_scan(101,[{'path':str(first),'flags':0x200,'id':101},{'checkpoint':101}])
        self.assertEqual(updated.index_info['strategy'],'incremental')
        self.assertNotIn(str(first),updated.nodes)
        self.assertEqual(updated.nodes[str(second)].size,second.stat().st_blocks*512)
        self.assertEqual(updated.nodes[str(self.root)].files,1)
    def counted_scan(self, event_id, changes):
        calls=[];real_lstat=os.lstat;real_stat=os.stat
        def lstat(p,*a,**k):calls.append(os.fspath(p));return real_lstat(p,*a,**k)
        def stat_(p,*a,**k):calls.append(os.fspath(p));return real_stat(p,*a,**k)
        with patch('os.lstat',lstat),patch('os.stat',stat_):s=self.run_scan(event_id,changes)
        return s,calls
    def assert_matches_full(self, incremental):
        full=IndexedScanner([str(self.root)],home=str(self.root),database=self.base/'full/index.sqlite',context=False,min_bytes=0,refresh=True)
        with patch.object(Scanner,'collect_context',lambda _:None),patch.object(Scanner,'_build_findings',lambda _:None),patch('soji_cli.index.native',return_value={'eventID':1}),patch('soji_cli.index.events',return_value=[]):
            full.run()
        self.assertFalse(full.error,full.error)
        for p in (str(self.root),*[str(x) for x in self.root.iterdir()]):
            self.assertEqual((incremental.nodes[p].size,incremental.nodes[p].files),(full.nodes[p].size,full.nodes[p].files),p)
        self.assertEqual(incremental.nodes[str(self.root)].apparent,full.nodes[str(self.root)].apparent)
    def test_incremental_stat_work_is_bounded_by_dirty_subtree_and_identities(self):
        for d in range(30):
            folder=self.root/f'unrelated{d}';folder.mkdir()
            for f in range(40):(folder/f'f{f}').write_bytes(b'z'*64)
        dirty=self.root/'dirty';dirty.mkdir();(dirty/'keep').write_bytes(b'k')
        removed=dirty/'link';removed.write_bytes(b'x'*16384)
        survivor=self.root/'unrelated0/survivor';os.link(removed,survivor)
        initial=self.run_scan();self.assertEqual(initial.index_info['strategy'],'full')
        self.assertEqual(initial.nodes[str(survivor)].size,survivor.stat().st_blocks*512//2)
        removed.unlink()
        s,calls=self.counted_scan(101,[{'path':str(removed),'flags':0x200,'id':101},{'checkpoint':101}])
        self.assertEqual(s.index_info['strategy'],'incremental')
        # Only cached index entries count; signature() probes home config files.
        outside=[c for c in calls if c in initial.nodes and not initial.nodes[c].directory and not within(c,str(dirty))]
        # Before: every cached regular file (1,202) was re-statted.
        self.assertEqual(outside,[str(survivor)])
        self.assertEqual(s.index_info['restatted'],1)
        self.assertEqual(s.nodes[str(survivor)].size,survivor.stat().st_blocks*512)
        self.assertEqual(s.nodes[str(survivor)].apparent,16384)
        self.assertLess(s.index_info['recomputedDirectories'],5)
        self.assert_matches_full(s)
    def test_new_link_to_single_link_cached_file_refreshes_its_share(self):
        a=self.root/'a';b=self.root/'b';a.mkdir();b.mkdir()
        original=a/'file';original.write_bytes(b'x'*16384)
        self.run_scan()
        os.link(original,b/'link')
        s=self.run_scan(101,[{'path':str(b/'link'),'flags':0x100,'id':101},{'checkpoint':101}])
        self.assertEqual(s.index_info['dirtySubtrees'],[str(b)])
        share=original.stat().st_blocks*512//2
        self.assertEqual((s.nodes[str(original)].size,s.nodes[str(b/'link')].size),(share,share))
        self.assertEqual(s.nodes[str(self.root)].apparent-s.nodes[str(self.root)].own_apparent-s.nodes[str(a)].own_apparent-s.nodes[str(b)].own_apparent,16384)
        self.assert_matches_full(s)
    def test_link_removed_outside_roots_refreshes_share(self):
        outside=self.base/'outside';outside.mkdir()
        inner=self.root/'a';inner.mkdir()
        f=inner/'file';f.write_bytes(b'x'*16384);os.link(f,outside/'link')
        first=self.run_scan()
        self.assertEqual(first.nodes[str(f)].size,f.stat().st_blocks*512//2)
        (outside/'link').unlink()  # no event inside the indexed roots
        s=self.run_scan(101,[{'checkpoint':101}])
        self.assertEqual(s.index_info['strategy'],'incremental')
        self.assertEqual(s.index_info.get('externalChecked'),1)
        self.assertEqual(s.nodes[str(f)].size,f.stat().st_blocks*512)
        self.assertEqual(s.nodes[str(self.root)].size,first.nodes[str(self.root)].size+f.stat().st_blocks*512//2)
    def test_new_outside_link_to_large_single_link_file_is_caught(self):
        outside=self.base/'outside';outside.mkdir()
        inner=self.root/'a';inner.mkdir()
        big=inner/'big';big.write_bytes(b'x'*(2<<20))
        small=inner/'small';small.write_bytes(b'x'*16384)
        first=self.run_scan()
        blocks=big.stat().st_blocks*512
        self.assertEqual(first.nodes[str(big)].size,blocks)
        os.link(big,outside/'big');os.link(small,outside/'small')  # no event inside the roots
        s=self.run_scan(101,[{'checkpoint':101}])
        self.assertEqual(s.index_info['strategy'],'incremental')
        self.assertEqual(s.index_info.get('linkProbed'),1)
        self.assertEqual(s.nodes[str(big)].size,blocks//2)
        self.assertEqual(s.nodes[str(self.root)].size,first.nodes[str(self.root)].size-blocks//2)
        # Below the probe size the share is left to the weekly full check.
        self.assertEqual(s.nodes[str(small)].size,first.nodes[str(small)].size)
        # The new identity is now tracked, so removing the outside link is seen too.
        (outside/'big').unlink()
        again=self.run_scan(102,[{'checkpoint':102}])
        self.assertEqual(again.index_info.get('externalChecked'),1)
        self.assertEqual(again.nodes[str(big)].size,blocks)
    def test_legacy_index_backfills_link_identities(self):
        import sqlite3
        a=self.root/'a';b=self.root/'b';a.mkdir();b.mkdir()
        first=a/'file';first.write_bytes(b'x'*16384);os.link(first,b/'link')
        self.run_scan()
        with sqlite3.connect(self.database) as db:db.execute('DROP TABLE links')
        db.close()
        store=IndexStore(self.database)
        try:self.assertEqual(sorted(r[0] for r in store.db.execute('SELECT path FROM links')),[str(first),str(b/'link')])
        finally:store.close()
        first.unlink()
        s=self.run_scan(101,[{'path':str(first),'flags':0x200,'id':101},{'checkpoint':101}])
        self.assertEqual(s.nodes[str(b/'link')].size,(b/'link').stat().st_blocks*512)
    def test_prorated_scanner_hook_does_not_deduplicate_shares_twice(self):
        s=self.scanner();a=str(self.root/'a');b=str(self.root/'b')
        s.nodes={str(self.root):Node(str(self.root),children=[a,b])}
        for p in (a,b):
            n=SimpleNamespace(**dataclasses.asdict(Node(p,directory=False,device=1,inode=5,own_size=4096,own_apparent=8192,files=1)))
            n.link_count=2  # engine-owned Node field proposed in the report
            s.nodes[p]=n
        fresh=SimpleNamespace(st_dev=1,st_ino=5,st_mode=0o100644,st_nlink=2,st_blocks=16)
        with patch('soji_cli.index.os.lstat',return_value=fresh):s.recompute()
        self.assertEqual(s.nodes[str(self.root)].size,8192)
        self.assertEqual(s.nodes[a].size,s.nodes[b].size)
    def test_mount_or_lost_event_forces_full(self):
        self.run_scan()
        for flag in (1,2,4,8,32,64,128):
            with self.subTest(flag=flag):
                s=self.run_scan(101,[{'path':str(self.root),'flags':flag,'id':101},{'checkpoint':101}])
                self.assertEqual(s.index_info['strategy'],'full')
    def test_history_marker_does_not_dirty_root(self):
        self.run_scan()
        s=self.run_scan(101,[{'path':str(self.root),'flags':16,'id':101},{'checkpoint':101}])
        self.assertEqual(s.index_info['dirtySubtrees'],[])
    def test_periodic_full_check_uses_age_of_full_walk(self):
        self.run_scan();store=IndexStore(self.database)
        try:
            store.set_meta('fullCheckedAt',time.time()-8*86400);store.set_meta('walkedAt',time.time()-8*86400);store.db.commit()
        finally:store.close()
        self.assertEqual(self.run_scan().index_info['strategy'],'full')
    def test_unreadable_folder_keeps_index_reusable_and_is_rechecked(self):
        denied=self.root/'denied';denied.mkdir();(denied/'blob').write_bytes(b'x'*50_000)
        os.chmod(denied,0)
        try:
            first=self.run_scan()
            self.assertEqual(first.index_info['strategy'],'full')
            self.assertTrue(first.nodes[str(denied)].own_errors)
            store=IndexStore(self.database)
            try:self.assertFalse(store.meta('complete'));self.assertTrue(store.meta('reusable'))
            finally:store.close()
            second=self.run_scan()
            self.assertEqual(second.index_info['strategy'],'incremental')
            self.assertEqual(second.index_info['dirtySubtrees'],[])  # Still denied: cached row kept.
            self.assertFalse(second.index_info['unreadableRechecked'])
            self.assertTrue(second.nodes[str(denied)].own_errors)
            self.assertNotIn(str(denied/'blob'),second.nodes)
        finally:os.chmod(denied,0o755)
        # A permission grant fires no event; the recheck measures it anyway.
        third=self.run_scan()
        self.assertEqual(third.index_info['strategy'],'incremental')
        self.assertTrue(third.index_info['unreadableRechecked'])
        self.assertFalse(third.nodes[str(denied)].own_errors)
        self.assertIn(str(denied/'blob'),third.nodes)
        self.assertEqual(third.nodes[str(self.root)].files,self.full_walk().nodes[str(self.root)].files)
    def full_walk(self):
        s=Scanner([str(self.root)],home=str(self.root),context=False,min_bytes=0);s.started=time.monotonic()
        s.visit(str(self.root));return s
    def test_snapshot_round_trip_and_unknown_format_forces_full_walk(self):
        (self.root/'cache').mkdir(exist_ok=True);(self.root/'cache'/'a.bin').write_bytes(b'x'*5000)
        first=self.run_scan()
        second=self.run_scan()
        self.assertEqual(second.index_info['strategy'],'incremental')
        self.assertEqual(list(second.nodes),list(first.nodes))
        for p,n in first.nodes.items():self.assertEqual(dataclasses.asdict(second.nodes[p]),dataclasses.asdict(n))
        store=IndexStore(self.database)
        try:store.db.execute('UPDATE node_snapshot SET format=99');store.db.commit()
        finally:store.close()
        self.assertEqual(self.run_scan().index_info['strategy'],'full')
    def test_path_only_matches_are_reused_and_conditional_ones_recomputed(self):
        from soji_cli.engine import Catalog,NO_MATCH
        home=str(self.root)
        first=Catalog(home)
        paths=[home+'/Library/Caches/com.example.app',home+'/proj/node_modules',home+'/proj/package.json',home+'/notes.txt']
        results=[first.match(p) for p in paths]
        second=Catalog(home);second.seed(first.key,dict(first.pure))
        self.assertEqual([second.match(p) for p in paths],results)
        self.assertTrue(set(first.pure)<=set(paths))
        self.assertIn(NO_MATCH,first.pure.values())
        third=Catalog(home);third.seed('other-catalog',dict(first.pure))
        self.assertEqual(third.seeded,{})
        # Conditional hints (onlyIfContains/unlessContains/onlyIfAncestorContains) are never cached.
        conditional={i for i,r in enumerate(first.records) if r[1].get('onlyIfContains') or r[1].get('unlessContains') or r[1].get('onlyIfAncestorContains')}
        self.assertFalse(conditional & set(first.pure.values()))
    def test_unreadable_sample_is_spread_and_bounded(self):
        from soji_cli.index import unreadable_sample
        rows=[(f'/r/{i:03}',None) for i in range(100)]
        sample=unreadable_sample(list(reversed(rows)),limit=4)
        self.assertEqual([p for p,_ in sample],['/r/000','/r/025','/r/050','/r/075'])
        self.assertEqual(len(unreadable_sample(rows[:3])),3)
    def test_outermost_and_subtree_set(self):
        from soji_cli.index import outermost,SubtreeSet
        self.assertEqual(outermost(['/a/b/c','/a/b','/a/b c','/x','/a/b']),['/a/b','/a/b c','/x'])
        inside=SubtreeSet(['/a/b'])
        self.assertTrue(inside('/a/b') and inside('/a/b/c/d'))
        self.assertFalse(inside('/a/bc') or inside('/a') or inside('/a/b c'))
    def test_regressed_cursor_and_incomplete_replay_force_full(self):
        self.run_scan(100)
        self.assertEqual(self.run_scan(99).index_info['strategy'],'full')
        self.assertEqual(self.run_scan(101,[{'checkpoint':100,'replayComplete':False}]).index_info['strategy'],'full')
    def test_dirty_subtree_keeps_depth_and_device_boundary(self):
        nested=self.root/'one/two';nested.mkdir(parents=True);(nested/'file').write_text('data')
        self.run_scan()
        s=self.scanner()
        with patch.object(Scanner,'collect_context',lambda _:None),patch.object(Scanner,'_build_findings',lambda _:None),patch('soji_cli.index.native',return_value={'eventID':101}),patch('soji_cli.index.events',return_value=[{'path':str(nested),'id':101,'flags':0}]),patch.object(s,'visit',wraps=s.visit) as visit:
            s.run()
        self.assertFalse(s.error,s.error)
        self.assertEqual(visit.call_args_list[0].args,(str(nested),2,self.root.stat().st_dev))
    def test_yarn_bun_roots_and_no_shell_execution(self):
        (self.root/'.zshrc').write_text('export YARN_CACHE_FOLDER="$HOME/yarn"\nexport BUN_INSTALL_CACHE_DIR="$HOME/bun"\nexport UV_CACHE_DIR="$(touch /tmp/never-execute-soji)"\n')
        roots=cache_locations(self.root,{})
        self.assertIn(('yarn-cache',str(self.root/'yarn'),'YARN_CACHE_FOLDER'),roots)
        self.assertIn(('bun-cache',str(self.root/'bun'),'BUN_INSTALL_CACHE_DIR'),roots)
        self.assertFalse(any(h=='uv-cache' for h,p,s in roots))


@unittest.skipUnless(os.environ.get('SOJI_TEST_NATIVE'),'Set SOJI_TEST_NATIVE to a disposable compiled helper')
class NativeRecovery(unittest.TestCase):
    def test_unavailable_versions_is_explicit_and_never_removes_fixture(self):
        helper=os.environ['SOJI_TEST_NATIVE']
        with tempfile.TemporaryDirectory(prefix='soji-versions-') as tmp:
            missing=str(Path(tmp)/'missing.txt')
            result=subprocess.run([helper,'versions',missing],text=True,capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('unavailable',json.loads(result.stdout)['error'].lower())
            doc=Path(tmp)/'document.txt';doc.write_text('disposable document')
            result=subprocess.run([helper,'remove-version',str(doc),'soji-version-v1:invalid'],text=True,capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('error',json.loads(result.stdout))
            self.assertEqual(doc.read_text(),'disposable document')
    def test_metadata_sparse_hardlink_clone_and_symlink(self):
        helper=os.environ['SOJI_TEST_NATIVE']
        with tempfile.TemporaryDirectory(prefix='soji-native-') as tmp:
            root=Path(tmp);file=root/'file';file.write_bytes(b'x'*65536)
            link=root/'hardlink';os.link(file,link)
            sparse=root/'sparse'
            with sparse.open('wb') as f:f.truncate(8*1024*1024)
            symlink=root/'symlink';symlink.symlink_to(file)
            clone=root/'clone';subprocess.run(['/bin/cp','-c',str(file),str(clone)],check=True)
            rows=json.loads(subprocess.check_output([helper,'metadata',*map(str,(file,link,sparse,symlink,clone))],text=True))
            rows={Path(r['path']).name:r for r in rows}
            self.assertEqual(rows['file']['linkCount'],2)
            self.assertEqual(rows['file']['inode'],rows['hardlink']['inode'])
            self.assertEqual(rows['sparse']['logicalBytes'],8*1024*1024)
            self.assertLess(rows['sparse']['statAllocatedBytes'],rows['sparse']['logicalBytes'])
            self.assertTrue(rows['symlink']['symlink']);self.assertNotEqual(rows['symlink']['inode'],rows['file']['inode'])
            self.assertFalse(rows['file']['dataless']);self.assertFalse(rows['file']['compressed'])
            if rows['file'].get('cloneID') and rows['clone'].get('cloneID'):
                self.assertEqual(rows['file']['cloneID'],rows['clone']['cloneID'])
            identity=json.loads(subprocess.check_output([helper,'event-id',str(root)],text=True))
            self.assertEqual(identity['volumes'][str(root)]['device'],root.stat().st_dev)

if __name__=='__main__':unittest.main()
