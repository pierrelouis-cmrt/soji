"""Independent safe-expectation proof; disposable home/state/Trash only."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from test_nov8_regressions import FakeHome, write, age_tree
from corpus import hermetic
from soji_cli.cleanup import Cleaner, create_plan


class MarkerSymlinkProof(FakeHome):
    def test_symlink_to_text_marker_cannot_make_current_ruby_inactive(self):
        for version, days in [('3.1.0', 180), ('3.2.0', 120), ('3.3.0', 90)]:
            write(self.home / '.rbenv/versions' / version / 'bin/ruby', age=days)
            age_tree(self.home / '.rbenv/versions' / version, days)
        target = self.home / '.rbenv/versions/3.1.0'
        marker = write(self.home / '.rbenv/version', '3.1.0\n', 200)
        self.assertEqual(create_plan(self.scan(), 'aggressive', paths={str(target)})['items'], [])
        # Equivalent readable text via a symlink, confined to the version family.
        selection = write(self.home / '.rbenv/versions/selection', '3.1.0\n', 200)
        marker.unlink()
        marker.symlink_to(selection)
        self.assertEqual(marker.read_text(), '3.1.0\n')
        plan = create_plan(self.scan(), 'aggressive', paths={str(target)})
        if plan['items']:
            with hermetic(str(self.home)):
                cleaner = Cleaner(self.home.parent / 'state', trash_directory=self.home.parent / 'trash')
                self.assertEqual(cleaner.fresh(plan['items'][0], plan), plan['items'][0]['identity'])
                result = cleaner.apply(plan)
                self.assertEqual(result['completed'], 1, result)
                self.assertFalse(target.exists())
                self.assertTrue(any((self.home.parent / 'trash').iterdir()))
        self.assertFalse(plan['items'], 'Current Ruby selected, fresh accepted, and moved to fixture Trash via text-marker symlink')

    def test_old_plan_refuses_after_inactive_marker_becomes_text_symlink(self):
        for version,days in [('3.1.0',180),('3.2.0',120),('3.3.0',90)]:
            write(self.home/'.rbenv/versions'/version/'bin/ruby',age=days)
            age_tree(self.home/'.rbenv/versions'/version,days)
        target=self.home/'.rbenv/versions/3.1.0'
        marker=write(self.home/'.rbenv/version','3.2.0\n',200)
        plan=create_plan(self.scan(),'aggressive',paths={str(target)})
        self.assertEqual(len(plan['items']),1)
        selection=write(self.home/'.rbenv/versions/selection','3.1.0\n',200)
        marker.unlink();marker.symlink_to(selection)
        with hermetic(str(self.home)):
            cleaner=Cleaner(self.home.parent/'state',trash_directory=self.home.parent/'trash')
            with self.assertRaisesRegex(ValueError,'reference unknown'):cleaner.fresh(plan['items'][0],plan)
            result=cleaner.apply(plan)
        self.assertEqual(result['completed'],0,result)
        self.assertTrue(target.exists())


if __name__ == '__main__':
    unittest.main()
