"""Regressions for the November 8, 2026 cleanup run (journal of plans
0ea353e2, bcfcf503, 046cd366, 217796c9, 79b34aec).

Every case runs in a disposable fake home. The paths mirror the ones the run
trashed; the assertions hold in every cleanup mode.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus import hermetic  # noqa: E402
from soji_cli import engine  # noqa: E402
from soji_cli.cleanup import Cleaner, create_plan  # noqa: E402
from soji_cli.engine import MODES, Scanner, within  # noqa: E402

DAY = 86400
BLOB = 64 * 1024

RUNTIMES = '.cache/codex-runtimes'
ACTIVE = RUNTIMES + '/codex-runtime-install-L2Mqle'
OLD = RUNTIMES + '/codex-runtime-install-wDayCH'
UNFINISHED = RUNTIMES + '/codex-runtime-install-G1C0iB'
PRIMARY = RUNTIMES + '/codex-primary-runtime'
DEPS = '/payload/codex-primary-runtime/dependencies'

# Installed software whose node_modules the run took as "Project dependencies".
INSTALLED = {
    '.vscode/extensions/ritwickdey.liveserver-5.7.10': 'node_modules',
    '.vscode/extensions/oderwat.indent-rainbow-8.3.1': 'node_modules',
    '.vscode/extensions/esbenp.prettier-vscode-12.4.0': 'node_modules',
    '.vscode/extensions/pranaygp.vscode-css-peek-4.4.3': 'server/node_modules',
    '.vscode/extensions/ms-python.python-2026.10.0-darwin-arm64': 'out/client/node_modules',
    '.config/raycast/extensions/112ad714-bf10-4ccc-a70f-4232bb2241a5': 'node_modules',
    '.config/raycast/extensions/7122ec68-495a-428d-9dc2-7a120818c8f6': 'node_modules',
    'Library/Application Support/Zed/extensions/work/html': 'node_modules',
    'Library/Application Support/Zed/extensions/work/emmet': 'node_modules',
    'Library/Application Support/discord/app-0.0.411/modules/discord_spellcheck-1/discord_spellcheck': 'node_modules',
    '.t3/tools/expo-device-hub/0.15.3': 'node_modules',
    '.cursor/extensions/some.ext-1.0.0': 'dist/node_modules',
    '.windsurf/extensions/some.ext-1.0.0': 'node_modules',
    '.vscode-insiders/extensions/some.ext-1.0.0': 'node_modules',
}


def write(path, data=b'x' * BLOB, age=40):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    stamp = time.time() - age * DAY
    os.utime(path, (stamp, stamp))
    return path


def age_tree(root, age):
    stamp = time.time() - age * DAY
    for folder, dirs, files in os.walk(root, topdown=False):
        for name in [*files, *dirs]:
            os.utime(Path(folder, name), (stamp, stamp), follow_symlinks=False)
        os.utime(folder, (stamp, stamp))


def git(repo, *args):
    env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1',
               GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid',
               GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.invalid')
    subprocess.run(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-C', str(repo), *args], check=True, capture_output=True, env=env)


class FakeHome(unittest.TestCase):
    processes = ()
    open_paths = ()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve() / 'home'
        self.home.mkdir()

    def scan(self, roots=None):
        test = self

        def collect_context(scan):
            scan.processes = sorted(p.casefold() for p in test.processes)
            scan.open_paths = sorted(test.open_paths)

        with hermetic(str(self.home)):
            saved = engine.Scanner.collect_context
            engine.Scanner.collect_context = collect_context
            try:
                s = Scanner([str(r) for r in (roots or [self.home])], home=str(self.home), min_bytes=1)
                s.run()
            finally:
                engine.Scanner.collect_context = saved
        self.assertFalse(s.error)
        return s

    def selected(self, scanner, mode):
        return [f for f in scanner.decisions(mode) if f.selected]

    def assert_never_selected_inside(self, scanner, root, strict=True):
        root = str(root)
        for mode in MODES:
            for f in self.selected(scanner, mode):
                inside = within(f.path, root) and (f.path != root or not strict)
                self.assertFalse(inside, f'{mode} selected {f.path} inside {root}: {f.decision}')


class ToolchainRuntimeTests(FakeHome):
    """Bug 1: the Codex runtime in use was trashed file by file."""

    def build(self, active_age=0):
        h = self.home
        runtime = lambda version: json.dumps({'bundleVersion': version, 'nodeVersion': '24'})
        write(h / PRIMARY / 'runtime.json', runtime('26.1105.12137'), 3)
        write(h / PRIMARY / 'dependencies/node/bin/node', age=3)
        # The install in use: old archive, fresh __pycache__ (0.0 h idle).
        write(h / ACTIVE / 'node-runtime.tar.xz', age=29)
        write(h / ACTIVE / 'payload/codex-primary-runtime/runtime.json', runtime('26.1007.11041'), 30)
        for rel in ('node/bin/node', 'python/bin/python3.12', 'python/lib/libpython3.12.dylib',
                    'node/node_modules/pdfjs-dist/build/pdf.mjs', 'node/node_modules/playwright-core/index.js',
                    'node/node_modules/tesseract.js-core/core.wasm', 'node/node_modules/sharp/lib/sharp.node',
                    'python/lib/python3.12/site-packages/numpy/core/_multiarray.so',
                    'python/lib/python3.12/site-packages/lxml/etree.so'):
            write(h / (ACTIVE + DEPS) / rel, age=29)
        write(h / (ACTIVE + DEPS) / 'node/node_modules/@oai/artifact-tool/package.json', '{}', 29)
        write(h / (ACTIVE + DEPS) / 'node/node_modules/@oai/artifact-tool/package-lock.json', '{}', 29)
        write(h / (ACTIVE + DEPS) / 'node/node_modules/@oai/artifact-tool/node_modules/x/index.js', age=29)
        write(h / (ACTIVE + DEPS) / 'python/lib/python3.12/site-packages/pandas/__pycache__/core.cpython-312.pyc', age=active_age)
        # Superseded installs (these were correct to remove).
        write(h / OLD / 'node-runtime.tar.xz', age=40)
        write(h / OLD / 'payload/codex-primary-runtime/runtime.json', runtime('26.901.1'), 40)
        write(h / (OLD + DEPS) / 'node/bin/node', age=40)
        write(h / UNFINISHED / 'node-runtime.tar.xz', age=40)
        age_tree(h / ACTIVE, 29)
        age_tree(h / OLD, 40)
        age_tree(h / UNFINISHED, 40)
        age_tree(h / PRIMARY, 3)
        write(h / (ACTIVE + DEPS) / 'python/lib/python3.12/site-packages/pandas/__pycache__/core.cpython-312.pyc', age=active_age)

    def rows(self, s):
        return {str(Path(f.path).relative_to(self.home)): f for f in s.findings}

    def test_active_runtime_is_one_unit_never_selected(self):
        self.build()
        s = self.scan()
        rows = self.rows(s)
        self.assertIn(ACTIVE, rows, 'the install root must be one row')
        self.assertEqual(rows[ACTIVE].hint_id, 'codex-runtimes')
        for path in rows:
            self.assertFalse(path.startswith(ACTIVE + '/'), f'row inside the install: {path}')
        for root in (ACTIVE, PRIMARY):
            self.assert_never_selected_inside(s, self.home / root, strict=False)
        self.assertNotIn(PRIMARY, [r for r, f in rows.items() if f.hint_id == 'codex-runtimes'])

    def test_incident_layout_holds_every_install(self):
        # As on November 8: codex-primary-runtime is an extracted directory
        # whose version matches no install. Nothing positively identifies the
        # runtime in use, so no install is superseded (version/date/missing
        # metadata are no proof).
        self.build()
        s = self.scan()
        for root in (ACTIVE, OLD, UNFINISHED):
            self.assert_never_selected_inside(s, self.home / root, strict=False)

    def test_superseded_installs_are_still_candidates(self):
        # Positive identification: codex-primary-runtime links into L2Mqle.
        self.build()
        shutil.rmtree(self.home / PRIMARY)
        (self.home / PRIMARY).symlink_to(self.home / ACTIVE / 'payload/codex-primary-runtime')
        write(self.home / UNFINISHED / 'runtime.json', json.dumps({'bundleVersion': '26.800.1'}))
        age_tree(self.home / UNFINISHED, 40)
        s = self.scan()
        picked = {str(Path(f.path).relative_to(self.home)) for f in self.selected(s, 'balanced')}
        self.assertIn(OLD, picked)
        self.assertIn(UNFINISHED, picked)
        self.assertNotIn(ACTIVE, picked)
        self.assert_never_selected_inside(s, self.home / ACTIVE, strict=False)

    def test_old_but_current_runtime_kept_by_version_and_retention(self):
        # Even when nothing inside changed for weeks, the highest-version /
        # newest install is the current one.
        self.build(active_age=29)
        s = self.scan()
        rows = self.rows(s)
        for mode in MODES:
            self.assertFalse(rows[ACTIVE].decide(mode, s.now)[0], mode)

    def test_running_program_inside_install_holds_whole_root(self):
        self.build(active_age=40)
        age_tree(self.home / ACTIVE, 40)
        age_tree(self.home / OLD, 40)
        self.processes = [str(self.home / (OLD + DEPS) / 'node/bin/node')]
        s = self.scan()
        rows = self.rows(s)
        self.assertTrue(any(h.startswith('A running program is installed here') for h in rows[OLD].holds), rows[OLD].holds)
        self.assert_never_selected_inside(s, self.home / OLD, strict=False)

    def test_open_file_inside_install_holds_whole_root(self):
        self.build(active_age=40)
        self.open_paths = [str(self.home / (OLD + DEPS) / 'node/bin/node')]
        s = self.scan()
        self.assertIn('File open or process working in this folder', self.rows(s)[OLD].holds)
        self.assert_never_selected_inside(s, self.home / OLD, strict=False)

    def test_toolchain_rows_never_split_around_nested_hints(self):
        # A generic catch-all splits around nested hints; a toolchain never does.
        from soji_cli.engine import Catalog, generic_container
        cat = Catalog(str(self.home))
        for hint in cat.hints:
            if hint['group'] in ('Toolchains and SDKs', 'Editor extensions'):
                for pattern in hint['patterns']:
                    self.assertFalse(generic_container((hint, pattern)), hint['id'])


class InstalledSoftwareDependencyTests(FakeHome):
    """Bug 2: node_modules of installed apps/extensions taken as project deps."""

    def build(self):
        h = self.home
        for root, deps in INSTALLED.items():
            manifest = {'name': 'x', 'version': '1.0.0'}
            if 'extensions/' in root and 'raycast' not in root and 'Zed' not in root:
                manifest.update(publisher='someone', engines={'vscode': '^1.80.0'})
            if 'raycast' in root:
                manifest['$schema'] = 'https://www.raycast.com/schemas/extension.json'
            pkg = h / root / deps.rsplit('node_modules', 1)[0]
            write(pkg / 'package.json', json.dumps(manifest))
            # Lockfiles too: the install location must win over them.
            write(pkg / 'package-lock.json', '{}')
            write(h / root / deps / 'lib/index.js')
            write(h / root / deps / 'lib/other.js')
        # css-peek client/node_modules survived only because it was open.
        write(h / '.vscode/extensions/pranaygp.vscode-css-peek-4.4.3/client/package.json', '{}')
        write(h / '.vscode/extensions/pranaygp.vscode-css-peek-4.4.3/client/node_modules/lib/index.js')
        # Shipped out/ and dist/ of an extension are not build output.
        write(h / '.vscode/extensions/ms-python.python-2026.10.0-darwin-arm64/out/client/extension.js')
        write(h / '.vscode/extensions/esbenp.prettier-vscode-12.4.0/dist/extension.js')
        # An extension installed somewhere unknown: its manifest marks it.
        write(h / 'Tools/ext-install/package.json', json.dumps({'name': 'e', 'engines': {'vscode': '*'}}))
        write(h / 'Tools/ext-install/package-lock.json', '{}')
        write(h / 'Tools/ext-install/node_modules/lib/index.js')
        # App-managed tool installs under ~/Library (Zed's prettier).
        write(h / 'Library/Application Support/Zed/prettier/package.json', '{}')
        write(h / 'Library/Application Support/Zed/prettier/package-lock.json', '{}')
        write(h / 'Library/Application Support/Zed/prettier/node_modules/prettier/index.js')
        # Keep: these caches were correct to clean and must stay candidates.
        write(h / 'Library/Application Support/Code/CachedExtensionVSIXs/ms-python.python-2026.9.0', age=40)
        write(h / 'Library/Application Support/Code/CachedData/abc/chrome/js/x.code', age=40)
        write(h / 'Library/Application Support/discord/Cache/Cache_Data/f_000001', age=40)
        # A real project (Git checkout) and an extension under development.
        dev = h / 'code/my-ext'
        write(dev / 'package.json', json.dumps({'name': 'my-ext', 'publisher': 'me', 'engines': {'vscode': '*'}}))
        write(dev / 'package-lock.json', '{}')
        (dev / '.gitignore').write_text('node_modules/\n')
        git(dev, 'init', '-q', '-b', 'main'); git(dev, 'add', '.'); git(dev, 'commit', '-q', '-m', 'init')
        write(dev / 'node_modules/lib/index.js')
        # A folder that merely has a package.json (no lockfile, no VCS).
        write(h / 'code/loose/package.json', '{}')
        write(h / 'code/loose/node_modules/lib/index.js')
        age_tree(h, 40)

    def test_nothing_inside_installed_software_selected_in_any_mode(self):
        self.build()
        s = self.scan()
        for root in [*INSTALLED, 'Tools/ext-install', '.vscode/extensions/pranaygp.vscode-css-peek-4.4.3',
                     'Library/Application Support/Zed/prettier']:
            self.assert_never_selected_inside(s, self.home / root)
        for f in s.findings:
            rel = str(Path(f.path).relative_to(self.home))
            if any(rel.startswith(root + '/') for root in INSTALLED):
                self.assertNotIn(f.group, ('Project dependencies', 'Build output'), rel)
                self.assertTrue(any(h.startswith('Inside installed software') for h in f.holds), (rel, f.holds))

    def test_dependency_rule_needs_a_real_project(self):
        self.build()
        s = self.scan()
        deps = {str(Path(f.path).relative_to(self.home)) for f in s.findings if f.hint_id == 'node-modules'}
        self.assertIn('code/my-ext/node_modules', deps)
        self.assertNotIn('code/loose/node_modules', deps)
        self.assertFalse([d for d in deps if not d.startswith('code/')], deps)
        picked = {str(Path(f.path).relative_to(self.home)) for f in self.selected(s, 'balanced')}
        self.assertIn('code/my-ext/node_modules', picked)

    def test_app_caches_outside_installs_still_offered(self):
        self.build()
        s = self.scan()
        rows = {str(Path(f.path).relative_to(self.home)): f for f in s.findings}
        for rel in ('Library/Application Support/Code/CachedExtensionVSIXs',
                    'Library/Application Support/discord/Cache'):
            match = [f for r, f in rows.items() if r == rel or r.startswith(rel + '/')]
            self.assertTrue(match, rel)
            for f in match:
                self.assertTrue(f.hint_id, rel)
                self.assertFalse(any(h.startswith('Inside installed software') for h in f.holds), (rel, f.holds))


class RenamedProjectSessionTests(FakeHome):
    """Bug 3: sessions of a renamed project treated as "project gone"."""

    def session(self, folder, cwd, name, hours):
        p = self.home / '.claude/projects' / folder / (name + '.jsonl')
        line = json.dumps({'type': 'user', 'cwd': str(cwd)}) + '\n'
        write(p, line.encode().ljust(BLOB, b' '), hours / 24)
        return p

    def build(self):
        h = self.home
        # levo-terminal was renamed to soji: same folder, new sessions.
        soji = h / 'Documents/Github/soji'
        write(soji / 'README.md', 'soji\n', 0.5)
        git(soji, 'init', '-q', '-b', 'main'); git(soji, 'add', '.'); git(soji, 'commit', '-q', '-m', 'init')
        git(soji, 'remote', 'add', 'origin', 'https://github.com/me/soji.git')
        self.session('-Users-me-Documents-Github-soji', soji, 'now', 2)
        old = h / 'Documents/Github/levo-terminal'
        # Sidecars are members of the same session and must inherit the same
        # uncertainty and 24-hour protection.
        sidecar = self.home / '.claude/projects/-Users-me-Documents-Github-levo-terminal/b/subagents'
        write(sidecar / 'agent.jsonl', json.dumps({'cwd': str(old)}) + '\n', 30 / 24)
        age_tree(sidecar.parent, 30 / 24)
        self.renamed_20h = self.session('-Users-me-Documents-Github-levo-terminal', old, 'a', 20)
        self.renamed_30h = self.session('-Users-me-Documents-Github-levo-terminal', old, 'b', 30)
        # Worktree of the renamed project; its main repository is not findable.
        (h / '.t3/worktrees/levo-terminal').mkdir(parents=True)
        wt = h / '.t3/worktrees/levo-terminal/t3-0a36d5fa'
        self.worktree_3h = self.session('-Users-me--t3-worktrees-levo-terminal-t3-0a36d5fa', wt, 'w', 3.2)
        self.worktree_30h = self.session('-Users-me--t3-worktrees-levo-terminal-t3-0a36d5fa', wt, 'w2', 30)
        # Moved project whose remote still has the old name.
        app = h / 'work/app-new'
        write(app / 'README.md', 'x\n', 100)
        git(app, 'init', '-q', '-b', 'main'); git(app, 'add', '.'); git(app, 'commit', '-q', '-m', 'init')
        git(app, 'remote', 'add', 'origin', 'git@github.com:me/app-old.git')
        age_tree(app, 100)
        self.moved_30h = self.session('-Users-me-work-app-old', h / 'work/app-old', 'm', 30)
        # A surviving parent repository cannot establish a missing child's
        # historical identity or prove that the child was deleted.
        gone_repo = h / 'archive'
        write(gone_repo / 'README.md', 'fixture\n', 100)
        git(gone_repo, 'init', '-q', '-b', 'main'); git(gone_repo, 'add', '.'); git(gone_repo, 'commit', '-q', '-m', 'init')
        self.gone_30h = self.session('-Users-me-archive-deleted', gone_repo / 'deleted', 'g', 30)
        self.gone_20h = self.session('-Users-me-archive-deleted', gone_repo / 'deleted', 'g2', 20)
        os.utime(h / 'archive', (time.time() - 100 * DAY,) * 2)

    def rows(self, s):
        return {f.path: f for f in s.findings if f.hint_id == 'claude-sessions'}

    def test_renamed_project_sessions_keep_normal_policy(self):
        self.build()
        s = self.scan()
        rows = self.rows(s)
        for p in (self.renamed_20h, self.renamed_30h, self.worktree_3h, self.worktree_30h, self.moved_30h):
            f = rows[str(p)]
            self.assertNotEqual((f.levels or {}).get('reason'), 'Session project is gone; one level earlier', p)
            moved = next(e for e in f.evidence if e.get('check') == 'sessionProjectMoved')
            self.assertFalse(moved['gone'], p)
            for mode in ('careful', 'balanced'):
                self.assertFalse(f.decide(mode, s.now)[0], (p, mode, f.decide(mode, s.now)))

    def test_missing_child_of_surviving_repo_is_still_uncertain(self):
        self.build()
        s = self.scan()
        rows = self.rows(s)
        old = rows[str(self.gone_30h)]
        self.assertEqual(old.levels['reason'], 'Claude session/sidecar idle policy')
        self.assertFalse(old.decide('balanced', s.now)[0])
        young = rows[str(self.gone_20h)]
        for mode in ('careful', 'balanced'):
            ok, why = young.decide(mode, s.now)
            self.assertFalse(ok, mode)
        self.assertTrue(young.decide('aggressive', s.now)[0])

    def test_missing_non_git_and_moved_project_stays_uncertain_for_all_modes(self):
        self.build()
        s = self.scan(); rows = self.rows(s)
        for p in (self.renamed_20h, self.renamed_30h, self.worktree_3h, self.worktree_30h, self.moved_30h):
            f = rows[str(p)]
            self.assertNotEqual(f.levels['reason'], 'Session project is gone; one level earlier', p)
            for mode in ('careful', 'balanced'):
                self.assertFalse(f.decide(mode, s.now)[0], (p, mode))
        # Compound sidecar carries the parent transcript's conservative levels.
        composite = rows[str(self.renamed_30h)]
        self.assertTrue(any(m['role'] == 'subagents' for m in composite.members))
        self.assertFalse(composite.decide('balanced', s.now)[0])
        self.assertTrue(composite.decide('aggressive', s.now)[0])

    def test_session_floor_survives_any_levels(self):
        self.build()
        s = self.scan()
        f = self.rows(s)[str(self.worktree_3h)]
        f.levels = {'careful': 0, 'balanced': 0, 'aggressive': 0, 'reason': 'test override'}
        for mode in ('careful', 'balanced'):
            ok, why = f.decide(mode, s.now)
            self.assertFalse(ok)
            self.assertIn('never cleaned within 24 h', why)


class JournalTests(FakeHome):
    """Bugs 4 and 5 and the repeated Obsidian Code Cache attempt."""

    def setUp(self):
        super().setUp()
        self.state = self.home.parent / 'state'
        self.trash = self.home.parent / 'trash'
        write(self.home / '.npm/_npx/abc/blob', age=40)
        write(self.home / '.npm/_logs/debug.log', age=40)
        age_tree(self.home, 40)
        self.cleaner = Cleaner(self.state, trash_directory=self.trash)

    def apply(self, mode='balanced', open_at_apply=()):
        test = self
        opened = []

        def collect_context(scan):
            scan.processes = sorted(p.casefold() for p in test.processes)
            scan.open_paths = sorted(opened)

        with hermetic(str(self.home)):
            saved = engine.Scanner.collect_context
            engine.Scanner.collect_context = collect_context
            try:
                s = Scanner([str(self.home)], home=str(self.home), min_bytes=1)
                s.run()
                plan = create_plan(s, mode)
                self.assertTrue(plan['items'])
                opened.extend(open_at_apply)  # the app opens its cache after planning
                return plan, self.cleaner.apply(plan)
            finally:
                engine.Scanner.collect_context = saved

    def test_entries_record_mode_version_rule_threshold_and_reason(self):
        from soji_cli import __version__
        plan, result = self.apply('balanced')
        self.assertEqual(result['failed'], 0, result)
        self.assertIn('Trash is emptied', result['notice'])
        self.assertIn(result['notice'], plan['warnings'])
        for e in result['entries']:
            self.assertEqual(e['mode'], 'balanced')
            self.assertEqual(e['version'], __version__)
            self.assertTrue(e['rule'])
            policy = e['policy']
            self.assertEqual(policy['source'], 'fresh')
            self.assertEqual(policy['rule'], e['rule'])
            self.assertIn('threshold', policy)
            self.assertTrue(policy['reason'])
            self.assertIn('eligible from', policy['decision'])
        journal = [json.loads(line) for line in (self.state / 'journal.jsonl').read_text().splitlines()]
        self.assertTrue(all(j.get('mode') == 'balanced' and j.get('policy') for j in journal))

    def test_journal_marks_emptied_trash_unrecoverable(self):
        _, result = self.apply()
        first, second = result['entries'][:2]
        shutil.rmtree(first['trashedTo'])  # the user (or macOS) emptied it
        report = {e['id']: e for e in self.cleaner.report()}
        self.assertEqual(report[first['id']]['recovery'], 'unrecoverable (Trash emptied)')
        self.assertFalse(report[first['id']]['recoverable'])
        self.assertEqual(report[second['id']]['recovery'], 'recoverable while in Trash')
        self.assertTrue(report[second['id']]['recoverable'])
        with self.assertRaisesRegex(ValueError, 'Trash emptied'):
            self.cleaner.undo(first['id'])
        self.cleaner.undo(second['id'])
        self.assertEqual({e['id']: e for e in self.cleaner.report()}[second['id']]['recovery'], 'restored')

    def test_in_use_refusal_is_not_retried_until_it_passes(self):
        target = str(self.home / '.npm/_npx')
        _, first = self.apply(open_at_apply=[target + '/abc/blob'])
        refused = next(e for e in first['entries'] if e['path'] == target)
        self.assertEqual(refused['status'], 'failed')
        self.assertIn('File open', refused['error'])
        # Next run: the momentary open-file snapshot happens to be clear.
        plan, again = self.apply()
        retry = next(e for e in again['entries'] if e['path'] == target)
        self.assertEqual(retry['status'], 'failed')
        self.assertIn('skipped for 24 h', retry['error'])
        self.assertTrue(os.path.exists(target))


if __name__ == '__main__':
    unittest.main()
