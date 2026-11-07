"""Activity at a project root counts toward the project clock (safety extension)."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus import hermetic  # noqa: E402
from soji_cli.engine import Scanner  # noqa: E402

DAY = 86400


class ProjectActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve() / 'home'
        self.now = time.time()
        for name in ('web', 'other'):
            for rel, size in [('package.json', 64), ('node_modules/lib/index.js', 8192)]:
                p = self.home / 'code' / name / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b'x' * size)

    def tearDown(self):
        self.temp.cleanup()

    def session(self, cwd, age_days):
        p = self.home / '.claude/projects/x' / f'{abs(hash((cwd, age_days)))}.jsonl'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({'cwd': str(cwd)}) + '\n')
        stamp = self.now - age_days * DAY
        os.utime(p, (stamp, stamp))

    def scan(self):
        stamp = self.now - 60 * DAY
        for folder, dirs, files in os.walk(self.home / 'code', topdown=False):
            for name in files + dirs + ['']:
                os.utime(Path(folder, name), (stamp, stamp))
        with hermetic(str(self.home)):
            s = Scanner([str(self.home / 'code')], home=str(self.home), min_bytes=1)
            s.run()
            self.assertFalse(s.error)
            s.decisions('balanced')
        return {Path(f.path).parent.name: f for f in s.findings if f.hint_id == 'node-modules'}

    def test_recent_root_session_shortens_project_clock(self):
        self.session(self.home / 'code/web', 2)
        rows = self.scan()
        self.assertAlmostEqual(rows['web'].project_idle_hours, 48, delta=0.1)
        self.assertFalse(rows['web'].selected)
        self.assertTrue(any(e.get('check') == 'projectActivity' for e in rows['web'].evidence))
        # A sibling project's session does not leak across projects.
        self.assertGreater(rows['other'].project_idle_hours, 59 * 24)
        self.assertTrue(rows['other'].selected)

    def test_old_root_session_does_not_block(self):
        self.session(self.home / 'code/web', 30)
        rows = self.scan()
        self.assertAlmostEqual(rows['web'].project_idle_hours, 30 * 24, delta=0.1)
        self.assertTrue(rows['web'].selected)

    def test_live_session_holds(self):
        self.session(self.home / 'code/web', 0)
        rows = self.scan()
        self.assertIn('Coding agent or editor used this project recently', rows['web'].holds)


if __name__ == '__main__':
    unittest.main()
