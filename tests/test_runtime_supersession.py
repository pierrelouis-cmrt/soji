"""Codex runtime supersession must be positively identified (review probes
p1a-p1d of commit 21ce749).

An install is a cleanup candidate only when `codex-primary-runtime` is a
readable link resolving to a DIFFERENT install with readable metadata. Missing
primary, an extracted primary directory (the November 8 layout), missing or
malformed runtime.json, or unreadable folders hold every install. A running
program or open file anywhere inside an install holds the whole root, at scan
time and at fresh verification, whatever the reference says.

Everything runs in a disposable fake home; process and open-file snapshots are
injected, nothing is ever moved.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus import hermetic  # noqa: E402
from test_nov8_regressions import (FakeHome, write, age_tree, RUNTIMES, ACTIVE, OLD,  # noqa: E402
                                   PRIMARY, DEPS)
from soji_cli import engine  # noqa: E402
from soji_cli.cleanup import Cleaner, create_plan  # noqa: E402
from soji_cli.engine import MODES  # noqa: E402

NEW = RUNTIMES + '/codex-runtime-install-NEWxyz'


def runtime(version):
    return json.dumps({'bundleVersion': version, 'nodeVersion': '24'})


class Supersession(FakeHome):
    def install(self, rel, version, age, payload=True):
        h = self.home
        write(h / rel / 'node-runtime.tar.xz', age=age)
        if version is not None:
            write(h / rel / 'payload/codex-primary-runtime/runtime.json', runtime(version), age)
        if payload:
            write(h / (rel + DEPS) / 'node/bin/node', age=age)
            write(h / (rel + DEPS) / 'python/bin/python3.12', age=age)
            write(h / (rel + DEPS) / 'node/node_modules/x/package.json', '{}', age)
            write(h / (rel + DEPS) / 'node/node_modules/x/package-lock.json', '{}', age)
            write(h / (rel + DEPS) / 'node/node_modules/x/node_modules/y/index.js', age=age)
        age_tree(h / rel, age)

    def link_primary(self, rel):
        (self.home / PRIMARY).parent.mkdir(parents=True, exist_ok=True)
        (self.home / PRIMARY).symlink_to(self.home / rel / 'payload/codex-primary-runtime')

    def rel(self, f):
        return str(Path(f.path).relative_to(self.home))

    def rows(self, s):
        return {self.rel(f): f for f in s.findings}

    def picked(self, s, mode):
        return {self.rel(f) for f in self.selected(s, mode)}

    def assert_held_everywhere(self, s, *installs):
        """No row at or inside the install, in any mode."""
        for rel in installs:
            self.assert_never_selected_inside(s, self.home / rel, strict=False)

    # -- p1a ---------------------------------------------------------------
    def test_missing_primary_holds_every_install(self):
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        s = self.scan()
        self.assert_held_everywhere(s, OLD, ACTIVE)
        self.assertIn('codex-primary-runtime is missing', ' '.join(self.rows(s)[OLD].holds))

    # -- p1b ---------------------------------------------------------------
    def test_complete_install_without_runtime_json_is_not_proof(self):
        self.install(OLD, None, 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        write(self.home / PRIMARY / 'runtime.json', runtime('26.1007.11041'), 3)
        s = self.scan()
        self.assert_held_everywhere(s, OLD, ACTIVE)

    def test_referenced_install_without_metadata_holds_all(self):
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, None, 20)
        (self.home / ACTIVE / 'payload/codex-primary-runtime').mkdir(parents=True, exist_ok=True)
        self.link_primary(ACTIVE)
        s = self.scan()
        self.assert_held_everywhere(s, OLD, ACTIVE)

    def test_malformed_metadata_holds_all(self):
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        write(self.home / ACTIVE / 'payload/codex-primary-runtime/runtime.json', '{"bundleVersion": 7}', 20)
        age_tree(self.home / ACTIVE, 20)
        self.link_primary(ACTIVE)
        s = self.scan()
        self.assert_held_everywhere(s, OLD, ACTIVE)

    def test_unreadable_payload_folder_holds(self):
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        self.link_primary(ACTIVE)
        locked = self.home / OLD / 'payload'
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o700)
        s = self.scan()
        self.assert_held_everywhere(s, OLD, ACTIVE)

    # -- p1c ---------------------------------------------------------------
    def test_incident_layout_in_use_install_kept_when_newer_install_arrives(self):
        # Primary is an extracted directory at 26.1105 while L2Mqle (26.1007)
        # is in use; a newer 26.1105 install appears 8 days ago.
        write(self.home / PRIMARY / 'runtime.json', runtime('26.1105.12137'), 3)
        write(self.home / PRIMARY / 'dependencies/node/bin/node', age=3)
        self.install(ACTIVE, '26.1007.11041', 29)
        self.install(NEW, '26.1105.12137', 8)
        s = self.scan()
        self.assert_held_everywhere(s, ACTIVE, NEW, PRIMARY)
        ev = next(e for e in self.rows(s)[ACTIVE].evidence if e.get('check') == 'codexRuntime')
        self.assertIsNotNone(ev['current'])

    def test_primary_link_outside_installs_holds_all(self):
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        write(self.home / 'elsewhere/runtime.json', runtime('26.1007.11041'))
        (self.home / PRIMARY).symlink_to(self.home / 'elsewhere')
        s = self.scan()
        self.assert_held_everywhere(s, OLD, ACTIVE)

    def test_primary_link_to_arbitrary_descendant_is_not_runtime_reference(self):
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        (self.home / PRIMARY).symlink_to(self.home / (ACTIVE + DEPS) / 'node')
        self.assert_held_everywhere(self.scan(), OLD, ACTIVE)

    def test_conflicting_metadata_holds_all(self):
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        write(self.home / OLD / 'runtime.json', runtime('99.1'), 40)
        age_tree(self.home / OLD, 40)
        self.link_primary(ACTIVE)
        self.assert_held_everywhere(self.scan(), OLD, ACTIVE)

    def test_dangling_primary_link_holds_all(self):
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        (self.home / PRIMARY).symlink_to(self.home / RUNTIMES / 'codex-runtime-install-gone/payload/x')
        s = self.scan()
        self.assert_held_everywhere(s, OLD, ACTIVE)

    # Positive identification: the referenced install is kept, the others
    # (even with a higher version or a newer date) become candidates.
    def test_positive_reference_supersedes_other_installs(self):
        self.install(OLD, '26.901.1', 40)
        self.install(NEW, '26.1105.12137', 30)  # higher version, not referenced
        self.install(ACTIVE, '26.1007.11041', 20)
        self.link_primary(ACTIVE)
        s = self.scan()
        rows = self.rows(s)
        self.assert_held_everywhere(s, ACTIVE)
        self.assertIn('codex-primary-runtime points to this install', ' '.join(rows[ACTIVE].holds))
        self.assertIn(OLD, self.picked(s, 'balanced'))
        self.assertIn(OLD, self.picked(s, 'aggressive'))
        self.assertIn(NEW, self.picked(s, 'aggressive'))
        for rel in (OLD, NEW):
            self.assertFalse(any(h.startswith('Current Codex runtime') for h in rows[rel].holds), rows[rel].holds)

    def test_referenced_install_held_even_if_old_and_lower_version(self):
        self.install(OLD, '26.901.1', 60)
        self.install(ACTIVE, '26.1007.11041', 20)
        self.link_primary(OLD)
        s = self.scan()
        self.assert_held_everywhere(s, OLD)

    # -- p1d / any descendant in use holds the root ----------------------
    def test_program_launched_through_symlink_holds_whole_install(self):
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        self.link_primary(ACTIVE)
        link = self.home / '.local/bin/codex-node'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.home / (OLD + DEPS) / 'node/bin/node')
        self.processes = [str(link)]
        s = self.scan()
        self.assertTrue(any(h.startswith('A running program is installed here') for h in self.rows(s)[OLD].holds),
                        self.rows(s)[OLD].holds)
        self.assert_held_everywhere(s, OLD)

    def test_program_inside_symlinked_install_folder_holds(self):
        # The install itself reached through a symlinked parent directory.
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        self.link_primary(ACTIVE)
        alias = self.home / 'runtime-alias'
        alias.symlink_to(self.home / OLD)
        self.processes = [str(alias / ('payload/codex-primary-runtime/dependencies/python/bin/python3.12'))]
        s = self.scan()
        self.assert_held_everywhere(s, OLD)

    def test_descendant_use_holds_root_in_every_mode(self):
        for kind in ('process', 'open'):
            with self.subTest(kind=kind):
                self.setUp()
                self.install(OLD, '26.901.1', 40)
                self.install(ACTIVE, '26.1007.11041', 20)
                self.link_primary(ACTIVE)
                deep = str(self.home / (OLD + DEPS) / 'node/node_modules/x/node_modules/y/index.js')
                self.processes = [deep] if kind == 'process' else []
                self.open_paths = [deep] if kind == 'open' else []
                s = self.scan()
                self.assert_held_everywhere(s, OLD)
        self.processes = self.open_paths = ()

    def test_descendant_project_activity_holds_whole_install(self):
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        self.link_primary(ACTIVE)
        cwd = self.home / (OLD + DEPS) / 'node'
        write(self.home / '.claude/projects/runtime/session.jsonl',
              json.dumps({'cwd': str(cwd)}) + '\n', 0.01)
        s = self.scan()
        self.assert_held_everywhere(s, OLD)

    def test_missing_candidate_metadata_with_valid_reference_holds_inventory(self):
        self.install(OLD, None, 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        self.link_primary(ACTIVE)
        self.assert_held_everywhere(self.scan(), OLD, ACTIVE)

    # -- fresh verification ----------------------------------------------
    def fresh(self, mutate):
        """Plan OLD (positively superseded), apply `mutate`, re-verify fresh."""
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        self.link_primary(ACTIVE)
        s = self.scan()
        plan = create_plan(s, 'aggressive', paths={str(self.home / OLD)})
        self.assertEqual([str(Path(i['path']).relative_to(self.home)) for i in plan['items']], [OLD])
        mutate()
        test = self

        def collect_context(scan):
            scan.processes = sorted(p.casefold() for p in test.processes)
            scan.open_paths = sorted(test.open_paths)
        cleaner = Cleaner(self.home.parent / 'state', trash_directory=self.home.parent / 'trash')
        with hermetic(str(self.home)):
            saved = engine.Scanner.collect_context
            engine.Scanner.collect_context = collect_context
            try:
                with self.assertRaises(ValueError) as caught:
                    cleaner.fresh(plan['items'][0], plan)
            finally:
                engine.Scanner.collect_context = saved
        self.assertTrue((self.home / OLD / 'node-runtime.tar.xz').exists())
        return str(caught.exception)

    def test_fresh_refuses_when_reference_disappears(self):
        msg = self.fresh(lambda: (self.home / PRIMARY).unlink())
        self.assertIn('Fresh guards refuse', msg)

    def test_fresh_refuses_when_reference_moves_to_candidate(self):
        def relink():
            (self.home / PRIMARY).unlink()
            self.link_primary(OLD)
        self.assertIn('codex-primary-runtime points to this install', self.fresh(relink))

    def test_fresh_refuses_program_started_through_symlink(self):
        def launch():
            link = self.home / '.local/bin/node'
            link.parent.mkdir(parents=True)
            link.symlink_to(self.home / (OLD + DEPS) / 'node/bin/node')
            self.processes = [str(link)]
        self.addCleanup(setattr, self, 'processes', ())
        self.assertIn('A running program is installed here', self.fresh(launch))

    def test_fresh_refuses_open_descendant(self):
        def opened():
            self.open_paths = [str(self.home / (OLD + DEPS) / 'node/bin/node')]
        self.addCleanup(setattr, self, 'open_paths', ())
        self.assertIn('Fresh guards refuse', self.fresh(opened))

    def test_fresh_positive_case_still_verifies(self):
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        self.link_primary(ACTIVE)
        s = self.scan()
        plan = create_plan(s, 'balanced', paths={str(self.home / OLD)})
        self.assertEqual(len(plan['items']), 1)
        cleaner = Cleaner(self.home.parent / 'state', trash_directory=self.home.parent / 'trash')
        with hermetic(str(self.home)):
            saved = engine.Scanner.collect_context
            engine.Scanner.collect_context = lambda sc: (setattr(sc, 'processes', []), setattr(sc, 'open_paths', []))
            try:
                identity = cleaner.fresh(plan['items'][0], plan)
            finally:
                engine.Scanner.collect_context = saved
        self.assertEqual(identity, plan['items'][0]['identity'])


if __name__ == '__main__':
    unittest.main()
