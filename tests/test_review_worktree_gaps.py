"""Review proof tests for 52bb0e5: worktree data that the ignored-file inventory misses.

Each test builds a throwaway repo + local bare remote + merged/pushed detached
worktree in a temp dir (no global/system Git config, hooks off), then calls the
real guarded `Cleaner.tool_action`. A passing test means the unique data survives.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from soji_cli.cleanup import Cleaner
from soji_cli.gitstate import GitInspector

GIT_ENV = {'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
           'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'}


def git(repo, *args):
    subprocess.run(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false',
                    '-C', str(repo), *args], check=True, capture_output=True, env=dict(os.environ, **GIT_ENV))


class WorktreeInventoryGaps(unittest.TestCase):
    def fixture(self, gitignore):
        tmp = tempfile.TemporaryDirectory(prefix='soji-review-gaps-')
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, GIT_ENV)
        env.start()
        self.addCleanup(env.stop)
        root = Path(tmp.name).resolve()
        fake_home = root / 'fake-home'
        fake_home.mkdir()
        home_env = patch.dict(os.environ, {'HOME': str(fake_home)})
        home_env.start()
        self.addCleanup(home_env.stop)
        repo = root / 'repo'
        repo.mkdir()
        (repo / 'README.md').write_text('fixture\n')
        (repo / '.gitignore').write_text(gitignore)
        git(repo, 'init', '-q', '-b', 'main')
        git(repo, 'add', '.')
        git(repo, 'commit', '-q', '-m', 'init')
        git(root, 'init', '-q', '--bare', 'remote.git')
        git(repo, 'remote', 'add', 'origin', str(root / 'remote.git'))
        git(repo, 'push', '-q', '-u', 'origin', 'main')
        work = root / 'wt'
        git(repo, 'worktree', 'add', '-q', '--detach', str(work))
        self.root, self.repo, self.work = root, repo, work
        return work

    def write(self, rel, text='only copy'):
        p = self.work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def attempt_removal(self):
        state = GitInspector().inspect(str(self.work), worktree=True)
        try:
            Cleaner(self.root / 'state', context=False).tool_action(
                {'kind': 'git-worktree', 'repository': state.get('mainWorktree') or str(self.repo), 'path': str(self.work)})
        except (ValueError, OSError):
            pass
        return state

    def test_unignored_pycache_dir_whose_contents_are_ignored_elsewhere(self):
        # `__pycache__` itself is not ignored; `ls-files --directory` still collapses it
        # to `__pycache__/` because every file inside matches *.pyc or *.db.
        self.fixture('*.pyc\n*.db\n')
        db = self.write('__pycache__/important.db')
        self.write('__pycache__/a.cpython-312.pyc', 'x')
        self.attempt_removal()
        self.assertTrue(db.exists(), '__pycache__/important.db was deleted by git worktree remove')

    def test_unignored_node_modules_dir_holding_only_ignored_secrets(self):
        self.fixture('.env\n*.sqlite\n')
        env = self.write('node_modules/.env', 'SECRET=1')
        db = self.write('node_modules/app.sqlite')
        self.attempt_removal()
        self.assertTrue(env.exists() and db.exists(), 'node_modules/.env and app.sqlite were deleted')

    def test_nested_repository_inside_ignored_node_modules(self):
        # npm link / git dependency / patch work with its own unpushed commit.
        self.fixture('node_modules/\n')
        nested = self.work / 'node_modules/linked'
        nested.mkdir(parents=True)
        git(nested, 'init', '-q', '-b', 'main')
        f = self.write('node_modules/linked/fix.js', 'local fix')
        git(nested, 'add', '.')
        git(nested, 'commit', '-q', '-m', 'unpushed')
        self.attempt_removal()
        self.assertTrue(f.exists(), 'nested repo with an unpushed commit inside node_modules was deleted')

    def test_assume_unchanged_local_edit(self):
        self.fixture('node_modules/\n')
        git(self.work, 'update-index', '--assume-unchanged', 'README.md')
        readme = self.write('README.md', 'LOCAL EDIT, only copy')
        self.attempt_removal()
        self.assertTrue(readme.exists(), 'assume-unchanged local edit was deleted')

    def test_skip_worktree_local_edit(self):
        self.fixture('node_modules/\n')
        git(self.work, 'update-index', '--skip-worktree', 'README.md')
        readme = self.write('README.md', 'LOCAL EDIT, only copy')
        self.attempt_removal()
        self.assertTrue(readme.exists(), 'skip-worktree local edit was deleted')

    # Controls: these must keep passing after any fix.
    def test_control_ignored_node_modules_is_removed(self):
        self.fixture('node_modules/\n')
        self.write('node_modules/pkg/index.js', 'regenerable')
        self.attempt_removal()
        self.assertFalse(self.work.exists())

    def test_control_symlinked_node_modules_target_survives(self):
        self.fixture('node_modules\n')
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'precious.txt').write_text('elsewhere')
        os.symlink(outside, self.work / 'node_modules')
        state = self.attempt_removal()
        self.assertIn('node_modules', state.get('reason', ''))
        self.assertTrue((outside / 'precious.txt').exists())


if __name__ == '__main__':
    unittest.main()
