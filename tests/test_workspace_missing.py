"""DerivedData missing-workspace early Outcome (consumer build 2026.11.14).

Two evidence levels are tested separately:
- CONFIRMED (static trace): SmartRules' early rule result is Careful and the
  verifier combines it with `judged` (max, none propagates).
- STATICALLY TRACED, NOT RUNTIME-OBSERVED: final per-mode selection. The level
  becomes Finding.minLevel and CleanupLevels.apply (0x100660bf4) applies the
  normal recency/age policy because levelByOwnRule is false for these rows.
  No original-app run has confirmed these selections; the parity gap stays open.
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


class CostlyBranchUnreachable(unittest.TestCase):
    def test_workspace_missing_hints_are_never_costly(self):
        """The unported verifier adjustment (0x1006782f4) requires tier == costly.
        Every shipped workspaceMissing hint is regenerable, so it cannot apply."""
        import json
        from soji_cli.engine import DATA
        hints = [h for h in json.loads((DATA / 'hints.json').read_text()) if (h.get('rule') or {}).get('workspaceMissing')]
        self.assertTrue(hints)
        self.assertEqual({h['tier'] for h in hints}, {'regenerable'})


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

    def test_confirmed_rule_result_is_careful(self):
        """Confirmed: the early rule level, independent of age."""
        for name, age in [('Old', 20), ('Recent', 3), ('Hours', 2 / 24), ('Fresh', 60 / DAY)]:
            self.project(name, age, self.home / 'code/gone')
        rows = self.scan()
        for name in ('Old', 'Recent', 'Hours', 'Fresh'):
            f = rows[name]['finding']
            self.assertEqual((f.rule_level, f.rule_early_reason), ('careful', 'workspaceMissing'), name)
            self.assertEqual(f.rule_min_hours, {}, name)

    def test_missing_versus_present_old(self):
        """Final selection: statically traced, not runtime-observed."""
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
        """Final selection for recently created caches: statically traced through
        CleanupLevels.apply (forIdle 7 d / 1 d / 1 h, 300 s floor), not observed."""
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
        """Confirmed (0x100678ec0, CleanupLevels.apply): with an agent judgement the
        rule level is discarded; the judgement's levels decide by idle time."""
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
