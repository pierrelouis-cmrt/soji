"""Independent safety proofs for 68aff51; every mutation is in a disposable home.

Preservation assertions deliberately fail when the real guarded Git removal
deletes unique fixture data. No implementation guards are mocked. Race tests
inject a writer only at a deterministic command boundary, then run real Git.
"""
import os
from pathlib import Path
import subprocess
import time
import unittest
from unittest.mock import patch

from tests import test_worktree_ignored as fixture
from soji_cli import cleanup, gitstate
from soji_cli.cleanup import Cleaner, create_plan, file_identity, digest
from soji_cli.engine import Scanner


class ResidualSafety(unittest.TestCase):
    setUp = fixture.IgnoredWorktreeData.setUp
    worktree = fixture.IgnoredWorktreeData.worktree
    scan = fixture.IgnoredWorktreeData.scan
    remove = fixture.IgnoredWorktreeData.remove

    def test_unique_ignored_node_modules_survives_scan_fresh_and_tool(self):
        work, made = self.worktree('unique', ['node_modules/local-notes.txt'])
        # Verify all modes, including actual fresh-plan validation.
        with fixture.corpus.hermetic(str(self.home)):
            scan = Scanner([str(self.home)], home=str(self.home), min_bytes=0)
            scan.run()
            for mode in fixture.MODES:
                plan = create_plan(scan, mode, paths=[str(work)], method='permanent')
                self.assertEqual(len(plan['items']), 0, mode)
        with self.assertRaisesRegex(ValueError, 'cleanup disabled'):
            self.remove(work)
        self.assertTrue(made[0].exists(), 'unique ignored notes permanently deleted')

    def test_nested_bare_repository_survives(self):
        work, _ = self.worktree('bare')
        nested = work / 'node_modules/only-copy.git'
        nested.parent.mkdir()
        fixture.git(work, 'clone', '-q', '--bare', str(self.repo), str(nested))
        # A commit exists only in this bare repository. No .git sentinel exists
        # inside a bare repository root.
        commit = subprocess.run(
            ['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-C', str(nested),
             'commit-tree', 'HEAD^{tree}', '-p', 'HEAD', '-m', 'UNIQUE LOCAL COMMIT'],
            env=dict(os.environ, **fixture.GIT_ENV), capture_output=True, text=True, check=True).stdout.strip()
        fixture.git(nested, 'update-ref', 'refs/heads/unique', commit)
        fixture.git(nested, 'config', 'review.unique', 'only copy of local metadata')
        stamp = time.time() - 30 * 86400
        for folder, dirs, files in os.walk(work, topdown=False):
            for name in [*dirs, *files]:
                os.utime(Path(folder, name), (stamp, stamp), follow_symlinks=False)
            os.utime(folder, (stamp, stamp))
        self.assertFalse(any(row['selected'] for row in self.scan(work).values()))
        self.assertTrue(gitstate.GitInspector().inspect(str(work), worktree=True)['contentsVerified'])
        with self.assertRaisesRegex(ValueError, 'cleanup disabled'):
            self.remove(work)
        self.assertTrue((nested / 'refs/heads/unique').exists(), 'nested bare repository and unique commit deleted')

    def test_write_after_final_inspection_survives(self):
        work, _ = self.worktree('writer')
        self.assertFalse(any(row['selected'] for row in self.scan(work).values()))
        unique = work / 'local-data/late.txt'
        unique.parent.mkdir();unique.write_text('ONLY COPY: concurrent writer')
        real = cleanup.command
        reached=[]

        def write_then_execute(argv, **kwargs):
            if 'worktree' in argv and 'remove' in argv:
                reached.append(True)
                unique.write_text('ONLY COPY: concurrent writer after check')
            return real(argv, **kwargs)

        with patch.object(cleanup, 'command', write_then_execute):
            with self.assertRaisesRegex(ValueError, 'cleanup disabled'):
                self.remove(work)
        self.assertFalse(reached)
        self.assertTrue(unique.exists(), 'late ignored write permanently deleted')

    def test_cache_root_symlink_is_held_and_target_survives(self):
        work, _ = self.worktree('root-link')
        outside = self.home / 'external-cache'
        outside.mkdir()
        unique = outside / 'unique.txt'
        unique.write_text('only copy')
        (work / 'node_modules').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'cleanup disabled'):
            self.remove(work)
        self.assertEqual(unique.read_text(), 'only copy')

    def test_nested_dotgit_symlink_is_held(self):
        work, _ = self.worktree('git-link', ['node_modules/pkg/index.js'])
        (work / 'node_modules/pkg/.git').symlink_to(self.repo / '.git', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'cleanup disabled'):
            self.remove(work)
        self.assertTrue(work.exists())

    def test_harness_boundary_prevents_enclosing_repository_discovery(self):
        home = self.repo / 'fixture-home'
        project = home / 'not-a-repository'
        project.mkdir(parents=True)
        with fixture.corpus.hermetic(str(home)):
            self.assertFalse(gitstate.GitInspector().inspect(str(project))['repository'])

    def test_new_unique_ignored_data_blocks_fresh_in_every_mode(self):
        work, _ = self.worktree('late-before-fresh')
        with fixture.corpus.hermetic(str(self.home)):
            scan = Scanner([str(self.home)], home=str(self.home), min_bytes=0)
            scan.run()
            plans = [create_plan(scan, mode, paths=[str(work)], method='permanent') for mode in fixture.MODES]
            # Any change since planning must hold, whichever fresh guard catches it.
            unique = work / 'local-data/new.txt'
            unique.parent.mkdir()
            unique.write_text('only copy')
            for plan in plans:
                self.assertEqual(len(plan['items']), 0)
        self.assertEqual(unique.read_text(), 'only copy')

    def test_old_and_actionless_plans_refused_before_mutation(self):
        work, made = self.worktree('old-plan', ['node_modules/local-notes.txt'])
        with fixture.corpus.hermetic(str(self.home)):
            scan=Scanner([str(self.home)],home=str(self.home),min_bytes=0);scan.run()
            plan=create_plan(scan,'aggressive',method='permanent')
            for action in ({'kind':'git-worktree','repository':str(self.repo),'path':str(work)}, {}):
                item={'path':str(work),'identity':file_identity(work),'size':0,'newest':0,'files':0,
                      'hint':'codex-worktrees','group':'Agent worktrees','action':action,'method':'permanent','finding':{}}
                plan['items']=[item];plan.pop('digest',None);plan['digest']=digest(plan)
                cleaner=Cleaner(self.state,trash_directory=self.home.parent/'trash')
                with self.assertRaisesRegex(ValueError,'cleanup disabled'):cleaner.fresh(item,plan)
                result=cleaner.apply(plan,permanent=True,execute_tools=True)
                self.assertEqual(result['completed'],0,result)
                self.assertIn('cleanup disabled',result['entries'][0]['error'])
                # Also strip agent metadata: recognized path still refuses fallback.
                item.update(group='Other folders',hint=None);item['path']=str(made[0]);item['identity']=file_identity(made[0]);plan.pop('digest',None);plan['digest']=digest(plan)
                with self.assertRaisesRegex(ValueError,'cleanup disabled'):cleaner.fresh(item,plan)
        self.assertTrue(made[0].exists())


if __name__ == '__main__':
    unittest.main()
