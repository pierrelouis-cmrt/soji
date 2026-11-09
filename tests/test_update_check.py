"""Launch-time version check: outdated copies scan but never clean."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from soji_cli import __version__, update
from soji_cli.cleanup import Cleaner


def bump(version):
    major, minor, patch_ = update.parse_version(version)
    return f'{major}.{minor + 1}.0'


class UpdateCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name)
        update.block(None)

    def tearDown(self):
        update.block(None)
        self.temp.cleanup()

    def test_versions_compare_numerically(self):
        self.assertGreater(update.parse_version('v0.10.0'), update.parse_version('0.9.9'))
        self.assertEqual(update.parse_version('v1.2'), (1, 2, 0))
        self.assertIsNone(update.parse_version('nightly'))

    def test_newer_release_is_outdated_and_cached(self):
        calls = []
        def fetch(timeout):
            calls.append(timeout)
            return bump(__version__)
        first = update.check(self.state, fetch=fetch, now=1000)
        second = update.check(self.state, fetch=fetch, now=1000 + 60)
        self.assertEqual(first['status'], 'outdated')
        self.assertEqual(second['status'], 'outdated')
        self.assertEqual(len(calls), 1)
        update.check(self.state, fetch=fetch, now=1000 + update.CACHE_SECONDS + 1)
        self.assertEqual(len(calls), 2)

    def test_same_or_older_release_is_current(self):
        self.assertEqual(update.check(None, fetch=lambda timeout: __version__)['status'], 'current')
        self.assertEqual(update.check(None, fetch=lambda timeout: '0.0.1')['status'], 'current')

    def test_cache_from_another_version_is_ignored(self):
        (self.state / 'update-check.json').write_text(json.dumps(
            {'checkedAt': 1000, 'current': '0.0.1', 'latest': '99.0.0'}))
        result = update.check(self.state, fetch=lambda timeout: __version__, now=1001)
        self.assertEqual(result['status'], 'current')

    def test_network_failure_is_unknown_and_does_not_block(self):
        def fetch(timeout):
            raise OSError('offline')
        result = update.check(self.state, fetch=fetch)
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse((self.state / 'update-check.json').exists())
        with patch.object(update, 'check', return_value=result):
            update.enforce(self.state)
        self.assertIsNone(update.blocked_reason())

    def test_outdated_blocks_every_cleanup(self):
        outdated = {'status': 'outdated', 'current': __version__, 'latest': bump(__version__), 'error': None}
        with patch.object(update, 'check', return_value=outdated):
            update.enforce(self.state)
        self.assertIn('Cleaning is disabled', update.blocked_reason())
        with self.assertRaisesRegex(ValueError, 'Cleaning is disabled'):
            Cleaner(self.state).apply({'items': []})

    def test_interactive_gate_declined_continues_scan_only(self):
        outdated = {'status': 'outdated', 'current': __version__, 'latest': bump(__version__), 'error': None}
        ran = []
        with patch.object(update, 'check', return_value=outdated), \
             patch.object(update, 'upgrade_command', return_value=['brew', 'upgrade', 'soji']), \
             patch.dict('os.environ', {}, clear=False) as env:
            env.pop('SOJI_RELAUNCHED', None)
            update.interactive_gate(self.state, ask=lambda _: 'n', out=io.StringIO(),
                                    run=lambda cmd: ran.append(cmd))
        self.assertEqual(ran, [])
        self.assertIsNotNone(update.blocked_reason())

    def test_interactive_gate_accepted_runs_upgrade_then_relaunches(self):
        outdated = {'status': 'outdated', 'current': __version__, 'latest': bump(__version__), 'error': None}
        ran = []
        with patch.object(update, 'check', return_value=outdated), \
             patch.object(update, 'upgrade_command', return_value=['brew', 'upgrade', 'soji']), \
             patch.object(update, 'relaunch', side_effect=SystemExit(0)) as relaunch, \
             patch.dict('os.environ', {}, clear=False) as env:
            env.pop('SOJI_RELAUNCHED', None)
            with self.assertRaises(SystemExit):
                update.interactive_gate(self.state, ask=lambda _: '', out=io.StringIO(),
                                        run=lambda cmd: ran.append(cmd) or NS(returncode=0))
        self.assertEqual(ran, [['brew', 'upgrade', 'soji']])
        relaunch.assert_called_once()

    def test_failed_upgrade_stays_scan_only(self):
        outdated = {'status': 'outdated', 'current': __version__, 'latest': bump(__version__), 'error': None}
        with patch.object(update, 'check', return_value=outdated), \
             patch.object(update, 'upgrade_command', return_value=['brew', 'upgrade', 'soji']), \
             patch.object(update, 'relaunch') as relaunch, \
             patch.dict('os.environ', {}, clear=False) as env:
            env.pop('SOJI_RELAUNCHED', None)
            update.interactive_gate(self.state, ask=lambda _: 'y', out=io.StringIO(),
                                    run=lambda cmd: NS(returncode=1))
        relaunch.assert_not_called()
        self.assertIsNotNone(update.blocked_reason())


if __name__ == '__main__':
    unittest.main()
