"""DerivedData missing-workspace early Outcome (consumer build 2026.11.14).

SmartRules returns level Careful and skips the rule's age gates; the verifier
combines it with the judged risk level. Holds, recency and age policy remain.
"""
import os
import plistlib
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus import hermetic  # noqa: E402
from soji_cli.engine import Scanner  # noqa: E402
from soji_cli.levels import combine_rule_level  # noqa: E402

MODES = ('careful', 'balanced', 'aggressive')
DAY = 86400


class CombineTests(unittest.TestCase):
    def test_stricter_wins_and_none_propagates(self):
        self.assertEqual(combine_rule_level('careful', 'careful'), 'careful')
        self.assertEqual(combine_rule_level('careful', 'aggressive'), 'aggressive')
        self.assertEqual(combine_rule_level('balanced', 'careful'), 'balanced')
        self.assertIsNone(combine_rule_level('careful', None))
        self.assertIsNone(combine_rule_level(None, 'careful'))


class WorkspaceMissingScan(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve() / 'home'
        self.dd = self.home / 'Library/Developer/Xcode/DerivedData'
        (self.home / 'code/app').mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def project(self, name, age_days, workspace):
        folder = self.dd / name
        (folder / 'Build').mkdir(parents=True)
        (folder / 'Build/blob').write_bytes(b'x' * 65536)
        info = {} if workspace is None else {'WorkspacePath': str(workspace)}
        (folder / 'info.plist').write_bytes(plistlib.dumps(info))
        stamp = time.time() - age_days * DAY
        for p in [folder / 'Build/blob', folder / 'info.plist', folder / 'Build', folder]:
            os.utime(p, (stamp, stamp))

    def scan(self, processes=()):
        with hermetic(str(self.home)):
            from soji_cli import engine
            original = engine.Scanner.collect_context
            engine.Scanner.collect_context = lambda s: (setattr(s, 'processes', list(processes)), setattr(s, 'open_paths', []))
            try:
                s = Scanner([str(self.dd)], home=str(self.home), min_bytes=1)
                s.run()
            finally:
                engine.Scanner.collect_context = original
        self.assertFalse(s.error)
        rows = {}
        for mode in MODES:
            for f in s.decisions(mode):
                rows.setdefault(Path(f.path).name, {'finding': f})[mode] = f.selected
        return rows

    def picks(self, row):
        return [row[m] for m in MODES]

    def test_missing_versus_present_old(self):
        self.project('Missing', 20, self.home / 'code/gone')
        self.project('Present', 20, self.home / 'code/app')
        self.project('NoInfo', 20, None)  # absent WorkspacePath counts as missing
        rows = self.scan()
        self.assertEqual(rows['Missing']['finding'].rule_level, 'careful')
        self.assertEqual(self.picks(rows['Missing']), [True, True, True])
        self.assertEqual(self.picks(rows['NoInfo']), [True, True, True])
        # Present workspace keeps the 14-day rule clock (28 d at careful).
        self.assertIsNone(rows['Present']['finding'].rule_level)
        self.assertEqual(self.picks(rows['Present']), [False, True, True])

    def test_recent_data_still_follows_age_policy(self):
        self.project('Days', 3, self.home / 'code/gone')
        self.project('Hours', 2 / 24, self.home / 'code/gone')
        self.project('Fresh', 60 / DAY, self.home / 'code/gone')
        rows = self.scan()
        self.assertEqual(self.picks(rows['Days']), [False, True, True])
        self.assertEqual(self.picks(rows['Hours']), [False, False, True])
        self.assertEqual(self.picks(rows['Fresh']), [False, False, False])

    def test_holds_survive_early_outcome(self):
        self.project('Missing', 20, self.home / 'code/gone')
        rows = self.scan(processes=['xcodebuild'])
        self.assertIn('Running: xcodebuild', rows['Missing']['finding'].holds)
        self.assertEqual(self.picks(rows['Missing']), [False, False, False])

    def test_explicit_judgment_takes_precedence(self):
        self.project('Missing', 20, self.home / 'code/gone')
        rows = self.scan()
        f = rows['Missing']['finding']
        f.levels = {'careful': None, 'balanced': None, 'aggressive': 24 * 30, 'reason': 'agent'}
        now = time.time()
        self.assertEqual([f.decide(m, now)[0] for m in MODES], [False, False, False])
        f.levels = {'careful': None, 'balanced': 24, 'aggressive': 1, 'reason': 'agent'}
        self.assertEqual([f.decide(m, now)[0] for m in MODES], [False, True, True])


if __name__ == '__main__':
    unittest.main()
