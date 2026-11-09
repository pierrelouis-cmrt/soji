"""Version policy context: project pins at fresh/apply time, and nvm aliases.

Every case runs in a disposable fake home with a disposable state folder and
Trash; processes, open files, apps and native helpers are pinned by `hermetic`.

Pin scope: `Cleaner.fresh` re-measures only the target (or its version
family), so pins must be rediscovered live across the plan's scope; a pin
created after the plan, or a discovery that cannot complete, refuses.

nvm aliases: `~/.nvm/alias/default` may name another alias (`lts/*` ->
`lts/<codename>` -> version), a builtin (`node`, `stable`, `system`) or a
partial version. Resolution is bounded and confined to `alias/`; anything it
cannot establish holds every version in the family.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus import hermetic  # noqa: E402
from soji_cli import specialized  # noqa: E402
from soji_cli.cleanup import Cleaner, create_plan  # noqa: E402
from soji_cli.engine import MODES, Scanner  # noqa: E402

DAY = 86400
BLOB = 64 * 1024
NODE = '.nvm/versions/node/'
VERSIONS = {'v18.20.0': 180, 'v22.0.0': 120, 'v24.0.0': 90}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='soji-version-policy-')
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.home = base / 'home'
        self.state = base / 'state'
        self.trash = base / 'trash'
        for version, days in VERSIONS.items():
            self.write(NODE + version + '/bin/node', b'x' * BLOB, days)
        self.write('code/app/package.json', '{}', 200)
        self.alias('default', '24')
        self.ctx = hermetic(str(self.home))
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        self.locked = []
        self.addCleanup(lambda: [os.chmod(p, 0o700) for p in self.locked])

    def write(self, rel, data, age=200):
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            p.write_bytes(data)
        else:
            p.write_text(data)
        stamp = time.time() - age * DAY
        for q in [p, *p.parents]:
            if q == self.home.parent:
                break
            os.utime(q, (stamp, stamp), follow_symlinks=False)
        return p

    def alias(self, name, value):
        return self.write('.nvm/alias/' + name, value + '\n')

    def lock(self, path):
        os.chmod(path, 0)
        self.locked.append(path)

    def path(self, version):
        return str(self.home / NODE / version)

    def scan(self, roots=None):
        s = Scanner([str(r) for r in (roots or [self.home])], home=str(self.home), min_bytes=1)
        s.run()
        self.assertEqual(s.error, '')
        return s

    def finding(self, version, scanner=None):
        s = scanner or self.scan()
        return next(f for f in s.findings if f.path == self.path(version))

    def holds(self, version, scanner=None):
        return self.finding(version, scanner).holds

    def assert_never_selected(self, version, scanner=None):
        s = scanner or self.scan()
        for mode in MODES:
            f = next(f for f in s.decisions(mode) if f.path == self.path(version))
            self.assertFalse(f.selected, (mode, f.decision))

    def plan(self, version, mode='aggressive', roots=None):
        s = self.scan(roots)
        plan = create_plan(s, mode, paths={self.path(version)})
        self.assertEqual([i['path'] for i in plan['items']], [self.path(version)], 'fixture must start eligible')
        return plan

    def fresh(self, plan):
        cleaner = Cleaner(self.state, trash_directory=self.trash)
        return cleaner.fresh(plan['items'][0], plan)

    def refuses(self, plan, text):
        with self.assertRaises(ValueError) as caught:
            self.fresh(plan)
        self.assertIn(text, str(caught.exception))
        return str(caught.exception)


class FreshPinScope(Fixture):
    def eligible_modes(self):
        s = self.scan()
        return [m for m in MODES if next(f for f in s.decisions(m) if f.path == self.path('v18.20.0')).selected]

    def test_new_pin_after_plan_refuses_fresh_and_apply_in_every_eligible_mode(self):
        modes = self.eligible_modes()
        self.assertIn('aggressive', modes)
        for mode in modes:
            with self.subTest(mode=mode):
                pin = self.home / 'code/app/.nvmrc'
                pin.unlink(missing_ok=True)
                plan = self.plan('v18.20.0', mode)
                self.write('code/app/.nvmrc', '18.20.0\n', 200)
                self.assertIn('Version pinned by a project', self.holds('v18.20.0'))
                self.refuses(plan, 'Version pinned by a project')
                result = Cleaner(self.state, trash_directory=self.trash).apply(plan)
                entry = result['entries'][0]
                self.assertEqual(entry['status'], 'failed')
                self.assertIn('Version pinned by a project', entry['error'])
                self.assertTrue(os.path.isdir(self.path('v18.20.0')))

    def test_new_pin_deep_in_dependencies_and_partial_version(self):
        plan = self.plan('v18.20.0')
        self.write('code/app/node_modules/tool/.node-version', 'v18\n', 200)
        self.refuses(plan, 'Version pinned by a project')

    def test_existing_pin_holds_in_scan_every_mode(self):
        self.write('code/app/.nvmrc', '18.20.0\n')
        self.assertIn('Version pinned by a project', self.holds('v18.20.0'))
        self.assert_never_selected('v18.20.0')
        self.assertNotIn('Version pinned by a project', self.holds('v22.0.0'))

    def test_removed_pin_is_judged_on_current_facts(self):
        # A pin that no longer exists protects nothing: fresh checks judge the
        # current filesystem, exactly like a new full scan would.
        pin = self.write('code/app/.nvmrc', '18.20.0\n')
        self.assert_never_selected('v18.20.0')
        pin.unlink()
        os.utime(pin.parent, (time.time() - 200 * DAY,) * 2)
        plan = self.plan('v18.20.0')
        self.assertEqual(self.fresh(plan), plan['items'][0]['identity'])
        # Added then removed between plan and apply: still accepted.
        self.write('code/app/.nvmrc', '18.20.0\n').unlink()
        os.utime(self.home / 'code/app', (time.time() - 200 * DAY,) * 2)
        self.assertEqual(self.fresh(plan), plan['items'][0]['identity'])

    def test_pin_outside_partial_scan_roots_is_discovered(self):
        # Scanning only ~/.nvm never saw ~/code; discovery still covers home.
        self.write('code/app/.nvmrc', '18.20.0\n')
        s = self.scan([self.home / '.nvm'])
        self.assertIn('Version pinned by a project', self.holds('v18.20.0', s))
        (self.home / 'code/app/.nvmrc').unlink()
        os.utime(self.home / 'code/app', (time.time() - 200 * DAY,) * 2)
        plan = self.plan('v18.20.0', roots=[self.home / '.nvm'])
        self.write('code/app/.nvmrc', '18.20.0\n')
        self.refuses(plan, 'Version pinned by a project')

    def test_unreadable_folder_makes_discovery_incomplete(self):
        plan = self.plan('v18.20.0')
        locked = self.write('code/locked/README', 'x').parent
        self.lock(locked)
        self.refuses(plan, 'Project pin discovery incomplete')
        s = self.scan()
        self.assertTrue(any(h.startswith('Project pin discovery incomplete') for h in self.holds('v18.20.0', s)))
        self.assert_never_selected('v18.20.0', s)

    def test_unreadable_pin_file_makes_discovery_incomplete(self):
        plan = self.plan('v18.20.0')
        self.lock(self.write('code/app/.nvmrc', '18.20.0\n'))
        self.refuses(plan, 'Project pin discovery incomplete: pin file unreadable')

    def test_discovery_time_limit_refuses(self):
        plan = self.plan('v18.20.0')
        with mock.patch.object(specialized, 'PIN_DISCOVERY_SECONDS', -1):
            self.refuses(plan, 'Project pin discovery incomplete: time or size limit reached')

    def test_fresh_never_reuses_scan_or_index_pins(self):
        plan = self.plan('v18.20.0')
        self.write('code/app/.nvmrc', '18.20.0\n')
        with mock.patch.object(specialized.ProjectPins, 'from_nodes', side_effect=AssertionError('reused nodes')):
            self.refuses(plan, 'Version pinned by a project')

    def test_pin_created_between_batch_items_refuses_later_item(self):
        plan = create_plan(self.scan(), 'aggressive', paths={self.path('v18.20.0'), self.path('v22.0.0')})
        if len(plan['items']) != 2:
            self.skipTest('fixture selects one version only')
        original = Cleaner.fresh
        calls = []

        def fresh(cleaner, item, plan):
            result = original(cleaner, item, plan)
            if not calls:
                other = next(i for i in plan['items'] if i['path'] != item['path'])
                self.write('code/app/.nvmrc', Path(other['path']).name + '\n')
            calls.append(item['path'])
            return result
        with mock.patch.object(Cleaner, 'fresh', fresh):
            result = Cleaner(self.state, trash_directory=self.trash).apply(plan)
        entries = result['entries']
        self.assertEqual([e['status'] for e in entries][1], 'failed')
        self.assertIn('Version pinned by a project', entries[1]['error'])
        self.assertTrue(os.path.isdir(entries[1]['path']))


class NvmAliasResolution(Fixture):
    def assert_active(self, version, text='Active version: ~/.nvm/alias/default'):
        s = self.scan()
        self.assertIn(text, self.holds(version, s))
        self.assert_never_selected(version, s)
        return s

    def assert_family_held(self, why):
        s = self.scan()
        for version in VERSIONS:
            holds = self.holds(version, s)
            self.assertTrue(any(h.startswith('Active version cannot be determined') and why in h for h in holds), (version, holds))
            self.assert_never_selected(version, s)

    def lts_chain(self):
        self.alias('default', 'lts/*')
        self.alias('lts/*', 'lts/hydrogen')
        self.alias('lts/hydrogen', 'v18.20.0')

    def test_lts_chain_protects_default_in_every_mode(self):
        self.lts_chain()
        s = self.assert_active('v18.20.0')
        self.assertFalse(any(h.startswith('Active version') for h in self.holds('v22.0.0', s)))

    def test_direct_named_alias(self):
        self.alias('default', 'lts/hydrogen')
        self.alias('lts/hydrogen', 'v18.20.0')
        self.assert_active('v18.20.0')

    def test_partial_versions_match_installed_set(self):
        for value in ('18', 'v18', '18.20', 'v18.20', '18.20.0'):
            with self.subTest(value=value):
                self.alias('default', value)
                self.assert_active('v18.20.0')
        self.alias('default', '22')
        self.assertFalse(any(h.startswith('Active version') for h in self.holds('v18.20.0')))

    def test_node_and_stable_mean_newest_installed(self):
        for value in ('node', 'stable'):
            with self.subTest(value=value):
                self.alias('default', value)
                s = self.assert_active('v24.0.0')
                self.assertFalse(any(h.startswith('Active version') for h in self.holds('v18.20.0', s)))

    def test_system_selects_no_nvm_version(self):
        self.alias('default', 'system')
        self.assertFalse(any(h.startswith('Active version') for h in self.holds('v18.20.0')))

    def test_absent_default_holds_nothing(self):
        (self.home / '.nvm/alias/default').unlink()
        self.assertFalse(any(h.startswith('Active version') for h in self.holds('v18.20.0')))

    def test_cycle_holds_family(self):
        self.alias('default', 'one')
        self.alias('one', 'two')
        self.alias('two', 'one')
        self.assert_family_held('cycle')

    def test_self_reference_holds_family(self):
        self.alias('default', 'default')
        self.assert_family_held('cycle')

    def test_depth_limit_holds_family(self):
        self.alias('default', 'a0')
        for i in range(40):
            self.alias(f'a{i}', f'a{i + 1}')
        self.alias('a40', 'v18.20.0')
        self.assert_family_held('too deep')

    def test_missing_target_holds_family(self):
        self.alias('default', 'lts/*')
        self.alias('lts/*', 'lts/iron')
        self.assert_family_held('has no target')

    def test_unreadable_alias_holds_family(self):
        self.lts_chain()
        self.lock(self.home / '.nvm/alias/lts/hydrogen')
        self.assert_family_held('unreadable')

    def test_invalid_utf8_alias_holds_family(self):
        self.alias('default', 'lts/hydrogen')
        self.write('.nvm/alias/lts/hydrogen', b'v18.20.0\xff')
        self.assert_family_held('unreadable')

    def test_traversal_outside_alias_folder_holds_family(self):
        self.write('x', 'v18.20.0\n')
        for value in ('../../x', '../versions', '/etc/passwd', 'lts/../../x', './default'):
            with self.subTest(value=value):
                self.alias('default', value)
                self.assert_family_held('would leave the alias folder')

    def test_symlinked_alias_is_not_followed(self):
        outside = self.write('elsewhere/hydrogen', 'v18.20.0\n')
        self.alias('default', 'lts/hydrogen')
        (self.home / '.nvm/alias/lts').mkdir()
        (self.home / '.nvm/alias/lts/hydrogen').symlink_to(outside)
        self.assert_family_held('symlink')

    def test_alias_changed_between_scan_and_fresh(self):
        plan = self.plan('v18.20.0')
        self.lts_chain()
        self.refuses(plan, 'Active version: ~/.nvm/alias/default')
        self.alias('default', 'loop')
        self.alias('loop', 'loop')
        self.refuses(plan, 'Active version cannot be determined')
        self.alias('lts/hydrogen', 'v22.0.0')
        self.alias('default', 'lts/hydrogen')
        self.assertEqual(self.fresh(plan), plan['items'][0]['identity'])

    def test_project_pin_alias_resolves_through_nvm(self):
        self.alias('lts/hydrogen', 'v18.20.0')
        self.write('code/app/.nvmrc', 'lts/hydrogen # team default\n')
        s = self.scan()
        self.assertIn('Version pinned by a project (nvm alias lts/hydrogen)', self.holds('v18.20.0', s))
        self.assert_never_selected('v18.20.0', s)
        self.assertFalse(any('pinned' in h for h in self.holds('v22.0.0', s)))

    def test_project_pin_unresolvable_alias_holds_family(self):
        self.write('code/app/.nvmrc', 'lts/argon\n')
        s = self.scan()
        for version in VERSIONS:
            self.assertTrue(any(h.startswith('Project-pinned nvm alias cannot be resolved') for h in self.holds(version, s)))
            self.assert_never_selected(version, s)

    def test_project_pin_alias_created_after_plan_refuses(self):
        plan = self.plan('v18.20.0')
        self.alias('lts/*', 'lts/hydrogen')
        self.alias('lts/hydrogen', 'v18.20.0')
        self.write('code/app/.nvmrc', 'lts/*\n')
        self.refuses(plan, 'Version pinned by a project (nvm alias lts/*)')


if __name__ == '__main__':
    unittest.main()
