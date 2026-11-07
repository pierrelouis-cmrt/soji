"""Specific hints nested under the generic ~/Library/Caches/* catch-all."""
import os
import tempfile
import time
import unittest
from pathlib import Path

from soji_cli.engine import Scanner, generic_container, Catalog

OLD = time.time() - 20 * 86400


class GenericSplitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve() / 'home'
        for rel in ['Library/Caches/JetBrains/Idea2025.1/caches/blob',
                    'Library/Caches/JetBrains/Idea2025.1/log/blob',
                    'Library/Caches/com.example.Plain/blob']:
            p = self.home / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'x' * 8192)
        for folder, dirs, files in os.walk(self.home, topdown=False):
            for name in files + dirs:
                os.utime(Path(folder, name), (OLD, OLD))

    def tearDown(self):
        self.temp.cleanup()

    def scan(self, root, **kw):
        s = Scanner([str(root)], home=str(self.home), min_bytes=1, context=False, **kw)
        s.run()
        self.assertFalse(s.error)
        return {Path(f.path).relative_to(self.home).as_posix(): f.hint_id for f in s.findings}

    def test_generic_classification(self):
        cat = Catalog(str(self.home))
        caches = cat.match(str(self.home / 'Library/Caches/JetBrains'))
        self.assertEqual(caches[0]['id'], 'user-caches')
        self.assertTrue(generic_container(caches))
        devices = cat.match(str(self.home / 'Library/Developer/CoreSimulator/Devices/X'))
        self.assertFalse(generic_container(devices))  # a device is one unit

    def test_specific_hint_applies_and_remainder_keeps_catch_all(self):
        rows = self.scan(self.home)
        self.assertEqual(rows['Library/Caches/JetBrains/Idea2025.1/caches'], 'jetbrains-caches')
        self.assertEqual(rows['Library/Caches/JetBrains/Idea2025.1/log'], 'user-caches')
        self.assertEqual(rows['Library/Caches/com.example.Plain'], 'user-caches')
        self.assertNotIn('Library/Caches/JetBrains', rows)

    def test_root_inherits_only_the_plan_hint(self):
        log = self.home / 'Library/Caches/JetBrains/Idea2025.1/log'
        # Without the plan's hint, or with a different one, nothing is inherited.
        self.assertEqual(set(self.scan(log).values()), {''})
        self.assertEqual(set(self.scan(log, inherit_hint='temp-folders').values()), {''})
        self.assertEqual(self.scan(log, inherit_hint='user-caches'),
                         {'Library/Caches/JetBrains/Idea2025.1/log': 'user-caches'})

    def test_own_match_wins_over_inherit_hint(self):
        caches = self.home / 'Library/Caches/JetBrains/Idea2025.1/caches'
        self.assertEqual(self.scan(caches, inherit_hint='user-caches'),
                         {'Library/Caches/JetBrains/Idea2025.1/caches': 'jetbrains-caches'})

    def test_inherited_row_revalidates_for_cleanup(self):
        import plistlib
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from corpus import hermetic
        from soji_cli.cleanup import Cleaner, create_plan
        app = self.home / 'Applications/JetBrains.app/Contents'
        app.mkdir(parents=True)
        (app / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.jetbrains.x', 'CFBundleName': 'JetBrains'}))
        log = str(self.home / 'Library/Caches/JetBrains/Idea2025.1/log')
        with hermetic(str(self.home)):
            s = Scanner([str(self.home)], home=str(self.home), min_bytes=1)
            s.run()
            plan = create_plan(s, 'aggressive', paths={log})
            self.assertEqual([(i['path'], i['hint']) for i in plan['items']], [(log, 'user-caches')])
            cleaner = Cleaner(Path(self.temp.name) / 'state')
            self.assertEqual(cleaner.fresh(plan['items'][0], plan), plan['items'][0]['identity'])
            # The same item without its hint must not be re-admitted by inheritance.
            stripped = dict(plan['items'][0], hint='')
            with self.assertRaises(ValueError):
                cleaner.fresh(stripped, plan)

if __name__ == '__main__':
    unittest.main()
