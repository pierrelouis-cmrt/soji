"""Agent worktrees holding ignored data are never removed (audit 2026-11-08 P1).

`git worktree remove` (no --force) deletes ignored files silently, so Git
cleanliness is not filesystem safety. Every fixture is a throwaway local
repository with a local bare remote inside a temporary fake home; Git runs with
hooks disabled and no global or system configuration. `tool_action` runs for
real against those disposable worktrees only.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402
from soji_cli import gitstate  # noqa: E402
from soji_cli.cleanup import Cleaner  # noqa: E402
from soji_cli.engine import Scanner  # noqa: E402
from soji_cli.gitstate import GitInspector  # noqa: E402

MODES = ('careful', 'balanced', 'aggressive')
GIT_ENV = {'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
           'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'}


def git(repo, *args):
    subprocess.run(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false',
                    '-C', str(repo), *args], check=True, capture_output=True, env=dict(os.environ, **GIT_ENV))


class IgnoredWorktreeData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='soji-worktree-ignored-')
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, GIT_ENV)
        env.start()
        self.addCleanup(env.stop)
        root = Path(self.tmp.name).resolve()
        fake_home = root / 'fake-home'
        fake_home.mkdir()
        home_env = patch.dict(os.environ, {'HOME': str(fake_home)})
        home_env.start()
        self.addCleanup(home_env.stop)
        self.home = root / 'home'
        self.state = root / 'state'
        self.repo = self.home / 'code/app'
        self.repo.mkdir(parents=True)
        (self.repo / 'README.md').write_text('fixture\n')
        (self.repo / '.gitignore').write_text(
            'node_modules/\n__pycache__/\n.DS_Store\n*.sqlite\n*.ipynb\nexports/\nlocal-data/\ngenerated/\nnotes/\n')
        git(self.repo, 'init', '-q', '-b', 'main')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-q', '-m', 'init')
        remote = root / 'remote.git'
        git(root, 'init', '-q', '--bare', str(remote))
        git(self.repo, 'remote', 'add', 'origin', str(remote))
        git(self.repo, 'push', '-q', '-u', 'origin', 'main')

    def worktree(self, name, files=()):
        work = self.home / '.codex/worktrees' / name
        work.parent.mkdir(parents=True, exist_ok=True)
        git(self.repo, 'worktree', 'add', '-q', '--detach', str(work))
        made = []
        for rel in files:
            p = work / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('only copy of ' + rel)
            made.append(p)
        stamp = time.time() - 30 * 86400
        for folder, dirs, names in os.walk(self.home, topdown=False):
            for n in [*names, *dirs]:
                os.utime(Path(folder, n), (stamp, stamp), follow_symlinks=False)
        return work, made

    def scan(self, work):
        home = str(self.home)
        with corpus.hermetic(home):
            s = Scanner([home], home=home, min_bytes=0, context=True)
            s.run()
        self.assertFalse(s.error)
        rows = {}
        for mode in MODES:
            rows[mode] = next(f for f in s.report(mode)['findings'] if f['path'] == str(work))
        return rows

    def remove(self, work):
        Cleaner(self.state, context=False).tool_action(
            {'kind': 'git-worktree', 'repository': str(self.repo), 'path': str(work)})

    def assertBlocked(self, work, files, reason='not known to be disposable'):
        rows = self.scan(work)
        for mode, row in rows.items():
            self.assertFalse(row['selected'], (mode, row['decision']))
            self.assertTrue(any(reason in h for h in row['holds']), (mode, row['holds']))
            self.assertFalse((row.get('action') or {}).get('kind'), mode)
        with self.assertRaisesRegex(ValueError, 'cleanup disabled'):
            self.remove(work)
        self.assertTrue(work.exists())
        for p in files:
            self.assertEqual(p.read_text(), 'only copy of ' + str(p.relative_to(work)))

    # Unique ignored data blocks in every mode and at the tool boundary.
    def test_ignored_database_blocks(self):
        self.assertBlocked(*self.worktree('db', ['app.sqlite']))

    def test_ignored_notebook_blocks(self):
        self.assertBlocked(*self.worktree('nb', ['analysis.ipynb']))

    def test_ignored_export_blocks(self):
        self.assertBlocked(*self.worktree('export', ['exports/report.csv']))

    def test_nested_ignored_directory_blocks(self):
        self.assertBlocked(*self.worktree('nested', ['src/generated/deep/data.bin']))

    def test_disposable_name_inside_ignored_data_does_not_excuse_it(self):
        self.assertBlocked(*self.worktree('inner', ['local-data/node_modules/pkg/index.js']))

    def test_disposable_output_does_not_excuse_other_ignored_data(self):
        self.assertBlocked(*self.worktree('mixed', ['node_modules/pkg/index.js', 'notes/todo.md']))

    def test_untracked_folder_of_only_caches_is_not_assumed_disposable(self):
        # Git reports the whole untracked folder (`pkg/`), so its contents are
        # not individually classified; refusing is the conservative outcome.
        self.assertBlocked(*self.worktree('collapsed', ['pkg/__pycache__/m.pyc']))

    def test_untracked_file_blocks(self):
        self.assertBlocked(*self.worktree('untracked', ['draft.txt']), reason='Uncommitted or untracked')

    def test_data_added_after_scan_blocks_at_execution(self):
        work, _ = self.worktree('late')
        self.assertFalse(any(r['selected'] for r in self.scan(work).values()))
        late = work / 'local-data/new.txt'
        late.parent.mkdir()
        late.write_text('only copy')
        with self.assertRaisesRegex(ValueError, 'cleanup disabled'):
            self.remove(work)
        self.assertEqual(late.read_text(), 'only copy')

    # Incomplete inspection fails closed.
    def failing_inventory(self, result):
        real = gitstate.command

        def command(argv, timeout=8, env=None):
            return result if 'ls-files' in argv else real(argv, timeout=timeout, env=env)
        return patch.object(gitstate, 'command', command)

    def test_inventory_failure_blocks(self):
        work, _ = self.worktree('fail')
        for result in [(-1, '', 'timed out after 20 seconds'), (128, '', 'fatal'),
                       (0, 'local-data/', ''),  # unterminated: unparseable
                       (0, 'x' * getattr(gitstate, 'INVENTORY_LIMIT', 15_000_000), '')]:  # possibly truncated
            with self.subTest(result=result[:1] + (result[1][:12],)), self.failing_inventory(result):
                state = GitInspector().inspect(str(work), worktree=True)
                self.assertFalse(state['verified'])
                self.assertIn('cannot be inventoried', state['reason'])
                rows = self.scan(work)
                self.assertFalse(any(r['selected'] for r in rows.values()))
                with self.assertRaises(ValueError):
                    self.remove(work)
                self.assertTrue(work.exists())

    def test_subdirectory_is_not_a_worktree_root(self):
        work, _ = self.worktree('sub', ['docs/readme.md'])
        state = GitInspector().inspect(str(work / 'docs'), worktree=True)
        self.assertFalse(state['verified'])
        self.assertFalse(state['contentsVerified'])

    # Inventory controls remain useful; removal is disabled even when verified.
    def test_clean_merged_pushed_worktree_is_preserved(self):
        work, _ = self.worktree('clean')
        rows = self.scan(work)
        for mode, row in rows.items():
            self.assertFalse(row['selected'], (mode, row['holds']))
            self.assertFalse(row['action'])
        with self.assertRaisesRegex(ValueError, 'cleanup disabled'):
            self.remove(work)
        self.assertTrue(work.exists())

    def test_only_regenerable_ignored_output_is_preserved(self):
        work, _ = self.worktree('regen', ['node_modules/pkg/index.js', '__pycache__/m.cpython-312.pyc', '.DS_Store'])
        state = GitInspector().inspect(str(work), worktree=True)
        self.assertTrue(state['contentsVerified'], state)
        self.assertCountEqual(state['ignored'], ['.DS_Store', 'node_modules/', '__pycache__/'])
        self.assertFalse(any(r['selected'] for r in self.scan(work).values()))
        with self.assertRaisesRegex(ValueError, 'cleanup disabled'):
            self.remove(work)
        self.assertTrue(work.exists())


    def update_ignore(self, text):
        (self.repo / '.gitignore').write_text(text)
        git(self.repo, 'commit', '-qam', 'fixture ignore rules')
        git(self.repo, 'push', '-q')

    def test_collapsed_directories_block_in_every_mode(self):
        self.update_ignore('*.pyc\n*.db\n.env\n*.sqlite\n')
        for folder, files in [('__pycache__', ['__pycache__/important.db', '__pycache__/x.pyc']),
                              ('node_modules', ['node_modules/.env', 'node_modules/app.sqlite'])]:
            with self.subTest(folder=folder):
                self.assertBlocked(*self.worktree('collapse-'+folder, files))

    def test_nested_git_directory_or_file_blocks_in_every_mode(self):
        for rel in ('node_modules/.git', 'node_modules/linked/.git'):
            with self.subTest(rel=rel):
                self.assertBlocked(*self.worktree('gitfile-'+str(len(rel)), [rel, 'node_modules/unique.txt']))
        work, made = self.worktree('nested-repo', ['node_modules/linked/fix.js'])
        nested = work / 'node_modules/linked'
        git(nested, 'init', '-q', '-b', 'main')
        git(nested, 'add', '.')
        git(nested, 'commit', '-qm', 'unpushed fix')
        self.assertBlocked(work, made)

    def test_hidden_index_edits_block_in_every_mode(self):
        for flag in ('--assume-unchanged', '--skip-worktree'):
            with self.subTest(flag=flag):
                work, _ = self.worktree(flag[2:])
                git(work, 'update-index', flag, 'README.md')
                readme = work / 'README.md'
                readme.write_text('only copy of README.md')
                self.assertBlocked(work, [readme], reason=flag[2:])

    def test_ignore_stat_blocks_in_every_mode(self):
        work, _ = self.worktree('ignore-stat')
        git(work, 'config', 'core.ignoreStat', 'true')
        self.assertBlocked(work, [], reason='core.ignoreStat')

    def test_cache_content_shapes(self):
        self.update_ignore('__pycache__/\n.pytest_cache/\n.mypy_cache/\n.ruff_cache/\n')
        for folder in ('__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache'):
            with self.subTest(folder=folder):
                self.assertBlocked(*self.worktree('unsafe-'+folder, [folder+'/important.db']))
        work, _ = self.worktree('valid-caches', ['__pycache__/x.pyc', '.pytest_cache/v/cache/nodeids',
                                               '.mypy_cache/3.12/a.data.json', '.ruff_cache/0.14.1/1234'])
        self.assertTrue(GitInspector().inspect(str(work), worktree=True)['contentsVerified'])
        with self.assertRaisesRegex(ValueError, 'cleanup disabled'):
            self.remove(work)
        self.assertTrue(work.exists())

    def test_walk_limits_and_errors_fail_closed(self):
        work, made = self.worktree('bounded', ['node_modules/pkg/index.js'])
        for guard in (patch.object(gitstate, 'WALK_ENTRIES', 0),
                      patch.object(gitstate, 'WALK_SECONDS', -1),
                      patch.object(gitstate.os, 'scandir', side_effect=PermissionError('fixture denial'))):
            with guard:
                state = GitInspector().inspect(str(work), worktree=True)
                self.assertFalse(state['verified'], state)
                with self.assertRaises(ValueError):
                    self.remove(work)
        self.assertTrue(all(p.exists() for p in made))

    def test_internal_symlink_is_not_followed(self):
        work, _ = self.worktree('symlink', ['node_modules/pkg/index.js'])
        outside = self.home / 'outside'
        outside.mkdir()
        unique = outside / 'unique.txt'
        unique.write_text('only copy')
        (outside / '.git').mkdir()
        (work / 'node_modules/link').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'cleanup disabled'):
            self.remove(work)
        self.assertEqual(unique.read_text(), 'only copy')

    def test_inherited_git_environment_cannot_redirect_inspect_or_remove(self):
        work, _ = self.worktree('env-safe')
        poisoned = {'GIT_DIR': str(self.repo / '.git'), 'GIT_WORK_TREE': str(self.repo),
                    'GIT_INDEX_FILE': str(self.home / 'wrong-index'), 'GIT_CONFIG_COUNT': '1',
                    'GIT_CONFIG_KEY_0': 'core.ignoreStat', 'GIT_CONFIG_VALUE_0': 'true',
                    'GIT_CONFIG_PARAMETERS': "'core.ignoreStat=true'"}
        with patch.dict(os.environ, poisoned):
            state = GitInspector().inspect(str(work), worktree=True)
            self.assertEqual(state['root'], str(work))
            self.assertTrue(state['contentsVerified'], state)
            with self.assertRaisesRegex(ValueError, 'cleanup disabled'):
                self.remove(work)
        self.assertTrue(work.exists())
        self.assertEqual((self.repo / 'README.md').read_text(), 'fixture\n')

    def test_undecodable_inventory_blocks(self):
        work, _ = self.worktree('bad-bytes')
        # macOS refuses invalid UTF-8 filenames, so inject undecodable bytes at
        # the inventory subprocess boundary. The real command decoder runs.
        real = gitstate.command
        def command(argv, **kwargs):
            if 'ls-files' in argv and '--others' in argv:
                return real([sys.executable, '-c', 'import os; os.write(1, bytes([255]))'])
            return real(argv, **kwargs)
        with patch.object(gitstate, 'command', command):
            state = GitInspector().inspect(str(work), worktree=True)
            self.assertFalse(state['verified'], state)
            with self.assertRaises(ValueError):
                self.remove(work)
        self.assertTrue(work.exists())

    def test_ignore_check_failure_blocks(self):
        work, made = self.worktree('ignore-check', ['node_modules/pkg/index.js'])
        real = gitstate.command
        def command(argv, **kwargs):
            return (-1, '', 'fixture failure') if 'check-ignore' in argv else real(argv, **kwargs)
        with patch.object(gitstate, 'command', command):
            state = GitInspector().inspect(str(work), worktree=True)
            self.assertFalse(state['verified'], state)
            with self.assertRaises(ValueError):
                self.remove(work)
        self.assertTrue(all(p.exists() for p in made))


class InventoryParsing(unittest.TestCase):
    def test_classification(self):
        for entry in ('node_modules/', 'a/b/node_modules/', '__pycache__/', 'x/.pytest_cache/', '.DS_Store', 'm.pyc'):
            self.assertTrue(gitstate.disposable_ignored(entry), entry)
        for entry in ('local-data/', 'app.sqlite', 'a.ipynb', 'exports/', 'build/', 'dist/', '.env',
                      'node_modules', 'node_modules.sqlite', '.venv/', 'node_modules/x.db'):
            self.assertFalse(gitstate.disposable_ignored(entry), entry)

    def test_tracked_flags_fail_closed(self):
        root = '/disposable-fixture-not-created'
        for bad in ('H file', 'H ../escape\0', 'bad\0', 'H /abs\0'):
            self.assertIs(gitstate.tracked_flags(bad, root), False)
        self.assertIn('assume-unchanged', gitstate.tracked_flags('h file\0', root))
        with patch.object(gitstate.os, 'lstat', side_effect=FileNotFoundError):
            self.assertIsNone(gitstate.tracked_flags('S absent\0', root))
        with patch.object(gitstate.os, 'lstat', side_effect=PermissionError):
            self.assertIs(gitstate.tracked_flags('S unreadable\0', root), False)

    def test_parsing(self):
        self.assertEqual(gitstate.ignored_inventory(''), [])
        self.assertEqual(gitstate.ignored_inventory('a b/\0c\0'), ['a b/', 'c'])
        for bad in ('a', 'a\0\0', '/abs\0', '../x\0', 'a/../b\0', 'line\nbreak\0'):
            self.assertIsNone(gitstate.ignored_inventory(bad), repr(bad))


if __name__ == '__main__':
    unittest.main()
