"""TUI cleaning: target selection, Trash batch through the normal plan path, undo.
Runs on the synthetic corpus with a disposable trash folder; nothing real moves."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402
from soji_cli import tui  # noqa: E402
from soji_cli.cleanup import Cleaner, validate_plan  # noqa: E402
from soji_cli.engine import Scanner  # noqa: E402


def row(path, selected=True, kind=None, identity=True):
    return NS(path=path, selected=selected, action={'kind': kind} if kind else {},
              identity={'inode': 1} if identity else None, size=1)


class TargetSelection(unittest.TestCase):
    def test_marked_rows_win_over_view_and_only_ready_rows_qualify(self):
        rows = [row('/a'), row('/b'), row('/c', selected=False), row('/d', kind='simulator-device'), row('/e', identity=False)]
        targets, skipped = tui.cleanup_targets(rows, set())
        self.assertEqual([f.path for f in targets], ['/a', '/b'])
        self.assertEqual({f.path for f, _ in skipped}, {'/c', '/d', '/e'})
        targets, skipped = tui.cleanup_targets(rows, {'/b', '/c'})
        self.assertEqual([f.path for f in targets], ['/b'])
        self.assertEqual([(f.path, why) for f, why in skipped], [('/c', 'no longer eligible in this mode')])


@unittest.skipUnless(sys.platform == 'darwin', 'corpus assumes APFS allocation')
class TrashBatch(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name).resolve()
        self.home = base / 'home'; self.home.mkdir()
        self.state = base / 'state'; self.trash = base / 'trash'; self.trash.mkdir()
        corpus.build_corpus(self.home)
        self.ctx = corpus.hermetic(str(self.home)); self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)
        self.temp.cleanup()

    def test_clean_view_then_undo(self):
        s = Scanner([str(self.home)], home=str(self.home), min_bytes=corpus.MIN_BYTES, protected=[str(self.state)])
        s.run()
        rows = s.decisions('balanced')
        targets, skipped = tui.cleanup_targets(rows, set())
        self.assertTrue(targets)
        self.assertFalse(any(f.holds for f in targets))
        cleaner = Cleaner(self.state, trash_directory=self.trash)
        result = tui.clean_targets(s, 'balanced', targets, self.state, cleaner=cleaner)
        self.assertEqual(result['failed'], 0, [e.get('error') for e in result['entries']])
        self.assertEqual(result['completed'], len(targets))
        self.assertEqual(result['freed'], sum(f.size for f in targets))
        for f in targets:
            self.assertFalse(Path(f.path).exists())
        plan = json.loads(Path(result['plan']).read_text())
        validate_plan(plan)
        self.assertEqual(plan['method'], 'trash')
        self.assertEqual({i['path'] for i in plan['items']}, {f.path for f in targets})
        # Journal entries are the same ones `soji journal` lists.
        self.assertEqual({e['id'] for e in result['entries']} - {e['id'] for e in cleaner.entries()}, set())
        restored, errors = tui.undo_entries(result['entries'], self.state, cleaner=cleaner)
        self.assertEqual((restored, errors), (len(targets), []))
        for f in targets:
            self.assertTrue(Path(f.path).exists())

    def test_changed_item_is_refused_not_moved(self):
        s = Scanner([str(self.home)], home=str(self.home), min_bytes=corpus.MIN_BYTES, protected=[str(self.state)])
        s.run()
        targets, _ = tui.cleanup_targets(s.decisions('balanced'), set())
        victim = next(f for f in targets if Path(f.path).is_dir())
        (Path(victim.path) / 'new-file').write_bytes(b'z' * corpus.PAYLOAD)
        result = tui.clean_targets(s, 'balanced', [victim], self.state,
                                   cleaner=Cleaner(self.state, trash_directory=self.trash))
        self.assertEqual((result['completed'], result['failed']), (0, 1))
        self.assertTrue(Path(victim.path).exists())


if __name__ == '__main__':
    unittest.main()
