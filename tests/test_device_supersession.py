"""Device support newer-build detection and its SmartRules early outcome."""
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from test_core_v2 import Fixture
from soji_cli.specialized import DeviceCatalog, newer_build, is_device_support

ROOT = 'Library/Developer/Xcode/iOS DeviceSupport'


class NewerBuild(Fixture):
    def folder(self, name, prepared=True, days=None):
        p = self.home / ROOT / name
        (p / 'Symbols').mkdir(parents=True, exist_ok=True)
        (p / 'Symbols/blob').write_bytes(b'x' * 4096)
        if prepared:
            (p / '.processed_dyld_shared_cache_arm64e').write_text('')
        if days is not None:
            # Setting an earlier mtime also pulls the APFS birth time back.
            old = time.time() - days * 86400
            for q in [*p.rglob('*'), p]:
                os.utime(q, (old, old), follow_symlinks=False)
        return p

    def test_same_train_higher_number_is_newer(self):
        old = self.folder('iPhone15,2 17.0 (21A329)')
        new = self.folder('iPhone15,2 17.0 (21A331)')
        self.assertEqual(newer_build(str(old)), '21A331')
        self.assertIsNone(newer_build(str(new)))

    def test_replacement_must_be_prepared_and_match_device_and_version(self):
        old = self.folder('iPhone15,2 17.0 (21A329)')
        self.folder('iPhone15,2 17.0 (21A331)', prepared=False)
        self.folder('iPhone15,2 17.1 (21B80)')
        self.folder('iPhone16,1 17.0 (21A340)')
        self.folder('17.0 (21A350)')            # no device: a different release
        self.assertIsNone(newer_build(str(old)))

    def test_unparsed_or_different_train_uses_creation_time(self):
        beta = self.folder('iPhone15,2 18.0 (22A5316k)', days=30)
        final = self.folder('iPhone15,2 18.0 (22A3354)')
        self.assertEqual(newer_build(str(beta)), '22A3354')
        self.assertIsNone(newer_build(str(final)))

    def test_only_inside_xcode_device_support(self):
        self.assertTrue(is_device_support(str(self.home / ROOT / 'x')))
        self.assertFalse(is_device_support(str(self.home / 'Library/Developer/Other/iOS DeviceSupport/x')))
        p = self.home / 'Elsewhere DeviceSupport' / '17.0 (21A329)'; p.mkdir(parents=True)
        self.assertIsNone(newer_build(str(p)))

    def evaluate(self, s, path, connected=()):
        f = next(f for f in s.findings if f.path == str(path))
        devices = DeviceCatalog(str(self.home), {'devices': {}, 'runtimes': [], 'connectedBuilds': list(connected)}).build()
        sp = self.special(s, devices)
        with patch.object(devices, 'connected', return_value=True):
            sp.evaluate(f)
        return f

    def test_superseded_build_takes_early_careful_outcome(self):
        old = self.folder('iPhone15,2 17.0 (21A329)', days=10)
        new = self.folder('iPhone15,2 17.0 (21A331)', days=9)
        s = self.scan()
        f = self.evaluate(s, old)
        self.assertEqual((f.rule_early_reason, f.rule_level), ('newerBuild', 'careful'))
        # keepNewest 2 per device would otherwise retain it.
        self.assertEqual(f.mode_holds, {})
        # comesBack=downloads keeps the judged floor at Balanced (as for workspaceMissing).
        self.assertTrue(f.decide('balanced', s.now)[0], f.decide('balanced', s.now)[1])
        self.assertFalse(f.decide('careful', s.now)[0])
        g = self.evaluate(s, new)
        self.assertIsNone(g.rule_early_reason)
        self.assertIn('balanced', g.mode_holds)
        self.assertFalse(g.decide('balanced', s.now)[0])

    def test_without_newer_build_retention_still_holds(self):
        old = self.folder('iPhone15,2 17.0 (21A329)', days=10)
        self.folder('iPhone15,2 17.1 (21B80)', days=9)
        s = self.scan()
        f = self.evaluate(s, old)
        self.assertIsNone(f.rule_early_reason)
        self.assertFalse(f.decide('balanced', s.now)[0])

    def test_connected_device_hold_survives_supersession(self):
        old = self.folder('iPhone15,2 17.0 (21A329)', days=10)
        self.folder('iPhone15,2 17.0 (21A331)', days=9)
        s = self.scan()
        f = self.evaluate(s, old, connected=['21A329'])
        self.assertEqual(f.rule_early_reason, 'newerBuild')
        self.assertIn('A connected device uses this build', f.holds)
        self.assertFalse(f.decide('aggressive', s.now)[0])


if __name__ == '__main__':
    unittest.main()
