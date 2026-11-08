"""Native bulk walk == Scanner.visit, node for node, on a tricky fixture.

Skipped when the helper is not built (python3 build_release.py). The Python
walk stays the reference; the scanner falls back to it whenever the helper
is missing, disabled, patched out, or returns something it cannot decode.
"""
import dataclasses
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from soji_cli import walker
from soji_cli.engine import Node, Scanner

FIELDS = [f.name for f in dataclasses.fields(Node)]


def python_walk(roots, **kw):
    s = Scanner(roots, min_bytes=0, context=False, **kw)
    s.started = time.monotonic()
    with patch.dict(os.environ, {'SOJI_NATIVE_WALK': '0'}):
        s.walk([(r, 0, None, False) for r in s.roots])
    return s


def native_walk(roots, **kw):
    s = Scanner(roots, min_bytes=0, context=False, **kw)
    s.started = time.monotonic()
    if not walker.walk(s, [(r, 0, None, False) for r in s.roots]):
        raise AssertionError('native walk did not run')
    return s


@unittest.skipUnless(walker.helper(), 'native helper not built')
class NativeWalkParity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='soji-walk-')
        self.root = Path(self.tmp.name).resolve() / 'home'
        r = self.root
        (r / 'proj/node_modules/pkg').mkdir(parents=True)
        (r / 'proj/node_modules/pkg/index.js').write_bytes(b'x' * 9000)
        (r / 'proj/.env').write_text('SECRET=1')
        (r / 'proj/key.pem').write_text('k')
        (r / 'proj/.git/objects').mkdir(parents=True)  # private: not descended
        (r / 'proj/.git/objects/blob').write_bytes(b'g' * 4000)
        (r / 'Library/Mail/V10').mkdir(parents=True)  # private home path
        (r / 'Dropbox (Work)').mkdir()
        (r / 'Tool.app/Contents').mkdir(parents=True)
        (r / '.claude/projects/x/memory').mkdir(parents=True)
        (r / 'links').mkdir()
        (r / 'links/a').write_bytes(b'h' * 70000)
        os.link(r / 'links/a', r / 'links/b')
        os.link(r / 'links/a', r / 'proj/c')
        os.symlink('a', r / 'links/sym')
        os.symlink('/nonexistent', r / 'links/dangling')
        os.mkfifo(r / 'links/fifo')
        (r / 'denied').mkdir()
        (r / 'denied/inner').write_text('x')
        os.chmod(r / 'denied', 0)
        (r / 'deep').mkdir()
        p = r / 'deep'
        for i in range(6):
            p = p / f'd{i}'
            p.mkdir()
        (p / 'leaf').write_text('x' * 100)
        (r / 'many').mkdir()
        for i in range(300):
            (r / 'many' / f'f{i:03}').write_bytes(b'y' * (i * 37))
        # APFS rejects non-UTF-8 names; cover composed, decomposed and astral.
        for name in ('caf\u00e9', 'cafe\u0301-nfd', 'Ünïcødé 📦.APP-not', 'MEMORY'):
            (r / name).mkdir()
            (r / name / 'x').write_bytes(b'z' * 10)

    def tearDown(self):
        os.chmod(self.root / 'denied', 0o755)
        self.tmp.cleanup()

    def assertSameWalk(self, a, b):
        self.assertEqual(list(a.nodes), list(b.nodes))
        for path, x in a.nodes.items():
            self.assertEqual(dataclasses.asdict(x), dataclasses.asdict(b.nodes[path]), path)
        for counter in ('visited', 'bytes', 'unreadable', 'skipped', 'limited'):
            self.assertEqual(getattr(a, counter), getattr(b, counter), counter)
        self.assertEqual(a._inodes, b._inodes)

    def test_identical_nodes_counters_and_order(self):
        roots = [str(self.root)]
        self.assertSameWalk(python_walk(roots), native_walk(roots))

    def test_identical_in_reference_stat_mode(self):
        with patch.dict(os.environ, {'SOJI_NATIVE_WALK_STAT': '1'}):
            native = native_walk([str(self.root)])
        self.assertSameWalk(python_walk([str(self.root)]), native)

    def test_protected_paths_multiple_roots_and_single_thread(self):
        roots = [str(self.root / 'proj'), str(self.root / 'links'), str(self.root / 'many')]
        kw = {'protected': [str(self.root / 'proj/node_modules')]}
        with patch.dict(os.environ, {'SOJI_NATIVE_WALK_THREADS': '1'}):
            native = native_walk(roots, **kw)
        self.assertSameWalk(python_walk(roots, **kw), native)

    def test_depth_and_device_arguments(self):
        deep = str(self.root / 'deep')
        a = Scanner([deep], min_bytes=0, context=False); a.started = time.monotonic()
        with patch.dict(os.environ, {'SOJI_NATIVE_WALK': '0'}):
            a.walk([(deep, 124, 1, True)])  # depth limit inside, foreign device
        b = Scanner([deep], min_bytes=0, context=False); b.started = time.monotonic()
        self.assertTrue(walker.walk(b, [(deep, 124, 1, True)]))
        self.assertSameWalk(a, b)
        dev = os.lstat(deep).st_dev
        a = Scanner([deep], min_bytes=0, context=False); a.started = time.monotonic()
        with patch.dict(os.environ, {'SOJI_NATIVE_WALK': '0'}):
            a.walk([(deep, 124, dev, True)])
        b = Scanner([deep], min_bytes=0, context=False); b.started = time.monotonic()
        self.assertTrue(walker.walk(b, [(deep, 124, dev, True)]))
        self.assertSameWalk(a, b)

    def test_file_limit_marks_partial_and_holds(self):
        native = native_walk([str(self.root)], max_files=50)
        self.assertTrue(native.limited)
        self.assertEqual(native.visited, 50)
        self.assertGreater(native.nodes[str(self.root)].errors, 0)

    def test_spent_budget_root_rows(self):
        s = Scanner([str(self.root)], min_bytes=0, context=False, max_files=0)
        s.started = time.monotonic()
        self.assertTrue(walker.walk(s, [(str(self.root), 0, None, True), (str(self.root / 'x'), 0, None, False)]))
        self.assertEqual(list(s.nodes), [str(self.root)])
        self.assertEqual(s.nodes[str(self.root)].reason, 'Scan stopped before measuring')

    def test_truncated_output_falls_back(self):
        s = Scanner([str(self.root)], min_bytes=0, context=False)
        with self.assertRaises(ValueError):
            walker.decode(s, b'{"count": 5, "namesBytes": 10}\n\x00\x01')

    def test_patched_visit_keeps_python_walk(self):
        s = Scanner([str(self.root)], min_bytes=0, context=False)
        with patch.object(s, 'visit', wraps=s.visit):
            self.assertFalse(walker.available(s))
        self.assertTrue(walker.available(s))


if __name__ == '__main__':
    unittest.main()
