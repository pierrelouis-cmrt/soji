"""Simulator device parsing, twin detection and simulator outcomes."""
import os
import plistlib
import time
import unittest
from test_core_v2 import Fixture
from soji_cli.specialized import DeviceCatalog, simulator_device, simulator_has_twin

DEV = 'Library/Developer/CoreSimulator/Devices'
RT17 = 'com.apple.CoreSimulator.SimRuntime.iOS-17-0'
A, B, C = ('AAAAAAAA-0000-4000-8000-%012d' % i for i in (1, 2, 3))


class SimulatorTwins(Fixture):
    def device(self, udid, name='iPhone 15', runtime=RT17, state=1, apps=0, days=10):
        p = self.home / DEV / udid
        (p / 'data/Library').mkdir(parents=True, exist_ok=True)
        (p / 'data/Library/blob').write_bytes(b'x' * 4096)
        (p / 'device.plist').write_bytes(plistlib.dumps({'UDID': udid, 'name': name, 'runtime': runtime, 'state': state}))
        for i in range(apps):
            (p / f'data/Containers/Bundle/Application/APP{i}').mkdir(parents=True, exist_ok=True)
        old = time.time() - days * 86400
        for q in [*p.rglob('*'), p]:
            os.utime(q, (old, old), follow_symlinks=False)
        return p

    def test_device_plist_requires_name_runtime_and_integer_state(self):
        p = self.device(A)
        self.assertEqual(simulator_device(p), {'name': 'iPhone 15', 'runtime': RT17, 'state': 1})
        (p / 'device.plist').write_bytes(plistlib.dumps({'name': 'x', 'runtime': RT17, 'state': 'Shutdown'}))
        self.assertIsNone(simulator_device(p))

    def test_twin_needs_same_name_and_runtime_and_other_uuid(self):
        a = self.device(A)
        self.device(B, name='iPhone 15 Pro')
        self.assertFalse(simulator_has_twin(a))
        self.device(C, runtime='com.apple.CoreSimulator.SimRuntime.iOS-18-0')
        self.assertFalse(simulator_has_twin(a))
        self.device(B)  # now same name and runtime
        self.assertTrue(simulator_has_twin(a))

    def test_same_uuid_in_other_case_is_not_a_twin(self):
        a = self.device(A)
        self.device(A.lower())
        self.assertFalse(simulator_has_twin(a))

    def evaluate(self, s, path, runtimes=({'identifier': RT17, 'isAvailable': True},)):
        devices = {}
        for p in (self.home / DEV).iterdir():
            d = simulator_device(p)
            devices.setdefault(d['runtime'], []).append({'udid': p.name, 'state': 'Shutdown', 'name': d['name'], 'isAvailable': True})
        cat = DeviceCatalog(str(self.home), {'devices': devices, 'runtimes': list(runtimes)}).build()
        f = next(f for f in s.findings if f.path == str(path))
        self.special(s, cat).evaluate(f)
        return f

    def test_spare_twin_without_apps_gets_judgement(self):
        a = self.device(A); self.device(B, apps=1); self.device(C, name='iPad')
        s = self.scan()
        f = self.evaluate(s, a)
        self.assertEqual(f.levels['balanced'], 168)
        self.assertTrue(next(e for e in f.evidence if e['check'] == 'simulatorTwin')['twin'])
        # The twin itself has apps, so it is not spare.
        g = self.evaluate(s, self.home / DEV / B)
        self.assertIsNone(g.levels)
        # Another model on the same runtime is not a twin (port previously said spare).
        h = self.evaluate(s, self.home / DEV / C)
        self.assertIsNone(h.levels)

    def test_missing_runtime_is_careful_with_normal_recency(self):
        a = self.device(A, runtime='com.apple.CoreSimulator.SimRuntime.iOS-16-0', days=3)
        s = self.scan()
        f = self.evaluate(s, a)
        self.assertEqual(f.rule_early_reason, 'runtimeMissing')
        self.assertEqual({k: v for k, v in f.levels.items() if k != 'reason'}, {'careful': 168, 'balanced': 24, 'aggressive': 1})
        self.assertFalse(f.decide('careful', s.now)[0])
        self.assertTrue(f.decide('balanced', s.now)[0], f.decide('balanced', s.now)[1])


if __name__ == '__main__':
    unittest.main()
