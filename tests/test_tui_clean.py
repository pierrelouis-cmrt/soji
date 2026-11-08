"""TUI cleaning: target selection, Trash batch through the normal plan path, undo.
Runs on the synthetic corpus with a disposable trash folder; nothing real moves."""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402
from soji_cli import tui  # noqa: E402
from soji_cli.cleanup import Cleaner, validate_plan  # noqa: E402
from soji_cli.engine import Scanner  # noqa: E402


def row(path, selected=True, kind=None, identity=True):
    return NS(path=path, selected=selected, action={'kind': kind} if kind else {},
              identity={'inode': 1} if identity else None, size=1)


class LayoutHelpers(unittest.TestCase):
    def test_middle_truncation_keeps_the_leaf_name(self):
        path = '~/Library/Developer/Xcode/DerivedData/OldProject-abcdef'
        short = tui.middle_truncate(path, 30)
        self.assertEqual(len(short), 30)
        self.assertIn('…', short)
        self.assertTrue(short.endswith('OldProject-abcdef'))
        self.assertEqual(tui.middle_truncate('short', 30), 'short')

    def test_row_text_fits_and_strips_control_characters(self):
        text = tui.row_text('npm\x1b[2Jcache', '~/.npm/_cacache/' + 'x' * 80, 40)
        self.assertLessEqual(len(text), 40)
        self.assertNotIn('\x1b', text)

    def test_footer_always_keeps_help_and_quit(self):
        for width in (30, 80, 200):
            line = tui.footer_line(width)
            self.assertIn('? help', line)
            self.assertIn('Q quit', line)
        self.assertLessEqual(len(tui.footer_line(80)), 80)

    def test_sidebar_line_shows_size_within_width(self):
        line = tui.sidebar_line('Logs and crash reports and more', 920_000_000, 24, True)
        self.assertEqual(len(line), 24)  # Marker included in the width.
        self.assertTrue(line.startswith('› ') and line.endswith('920M'))
        self.assertEqual(tui.compact_size(18_600_000_000), '18.6G')


class TargetSelection(unittest.TestCase):
    def test_marked_rows_win_over_view_and_only_ready_rows_qualify(self):
        rows = [row('/a'), row('/b'), row('/c', selected=False), row('/d', kind='simulator-device'), row('/e', identity=False)]
        targets, skipped = tui.cleanup_targets(rows, set())
        self.assertEqual([f.path for f in targets], ['/a', '/b'])
        self.assertEqual({f.path for f, _ in skipped}, {'/c', '/d', '/e'})
        targets, skipped = tui.cleanup_targets(rows, {'/b', '/c'})
        self.assertEqual([f.path for f in targets], ['/b'])
        self.assertEqual([(f.path, why) for f, why in skipped], [('/c', 'no longer eligible in this mode')])


class ProgressFeedback(unittest.TestCase):
    def test_scan_has_activity_without_an_invented_percentage(self):
        progress = {"phase": "scan", "completed": 1234, "total": None}
        first = tui.progress_line(progress, width=12, tick=0)
        second = tui.progress_line(progress, width=12, tick=0.2)
        self.assertIn("Scanning disk", first)
        self.assertIn("1,234 entries", first)
        self.assertNotIn("%", first)
        self.assertNotEqual(first, second)
        self.assertEqual(len(first), len(second))

    def test_category_and_cleanup_bars_show_measured_progress(self):
        for phase, label in (("categorize", "Sorting categories"), ("clean", "Cleaning")):
            line = tui.progress_line({"phase": phase, "completed": 25, "total": 100}, width=8)
            self.assertEqual(line, f"{label}  ━━──────  25/100 · 25%")

    def test_cleanup_job_publishes_progress_without_blocking_the_ui(self):
        entered = threading.Event()
        release = threading.Event()
        result = {"entries": [], "completed": 0, "failed": 0}

        def work(scanner, mode, targets, state_dir, progress):
            snapshot = {"phase": "clean", "completed": 1, "total": 2, "path": "/fixture"}
            progress(snapshot)
            snapshot["completed"] = 999  # Callback snapshots must not alias mutable input.
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test worker timed out")
            return result

        with patch.object(tui, "clean_targets", side_effect=work):
            job = tui.CleanupJob(None, "careful", [None, None], "/unused")
            try:
                self.assertTrue(entered.wait(5))
                self.assertFalse(job.done.is_set())
                self.assertEqual(job.progress["completed"], 1)
            finally:
                release.set()
                job.thread.join(5)
        self.assertTrue(job.done.is_set())
        self.assertIs(job.result, result)
        self.assertIsNone(job.error)

    def test_cleanup_worker_errors_return_to_the_ui(self):
        with patch.object(tui, "clean_targets", side_effect=ValueError("plan refused")):
            job = tui.CleanupJob(None, "careful", [], "/unused")
            job.thread.join(5)
        self.assertTrue(job.done.is_set())
        self.assertEqual(job.error, "plan refused")
        self.assertIsNone(job.result)

    def test_tui_keeps_repainting_and_finishes_batch_before_exit(self):
        class FakeScanner:
            initializations = 0
            decision_calls = 0
            def __init__(self, roots=None, **options):
                type(self).initializations += 1
                self.home = "/fixture"
                self.roots = roots or [self.home]
                self.protected = []
                self.max_files, self.max_seconds, self.min_bytes = 100, 10, 0
                self.context, self.recent_activity_hours = False, 0
                self.done, self.limited = True, False
                self.cancel = threading.Event()
                self.bytes, self.visited, self.unreadable, self.skipped = 10, 2, 0, 0
                self.error, self.current, self.now = "", "", 123
                self.findings = [NS(path="/fixture/item", group="Caches", size=10,
                                    selected=True, holds=[], label="Item", decision="Ready",
                                    action={}, identity={"inode": 1})]
            def run(self):
                pass
            def decisions(self, mode):
                type(self).decision_calls += 1
                return self.findings

        done = threading.Event()
        job = NS(done=done, error=None,
                 progress={"phase": "clean", "completed": 1, "total": 2, "path": "/fixture/item"},
                 thread=NS(join=lambda: None),
                 result={"entries": [], "completed": 1, "failed": 0, "freed": 10, "plan": "/fixture/plan"})
        class Screen:
            def __init__(self):
                self.frames, self.frame, self.reads = [], [], 0
            def getmaxyx(self):
                return 30, 120
            def addnstr(self, y, x, text, n, attr):
                self.frame.append(text[:n])
            def erase(self):
                self.frame = []
            def refresh(self):
                self.frames.append("\n".join(self.frame))
            def keypad(self, enabled):
                pass
            def timeout(self, value):
                pass
            def getch(self):
                self.reads += 1
                if self.reads == 4:
                    done.set()
                if self.reads > 6:
                    raise AssertionError("TUI failed to exit")
                return {1: ord("x"), 2: ord("y"), 3: ord("q"),
                        4: ord("r"), 5: 27, 6: ord("q")}[self.reads]

        screen = Screen()
        with patch.object(tui.curses, "wrapper", side_effect=lambda fn: fn(screen)), \
             patch.object(tui.curses, "curs_set"), \
             patch.object(tui.curses, "use_default_colors"), \
             patch.object(tui.curses, "init_pair"), \
             patch.object(tui.curses, "color_pair", return_value=0), \
             patch.object(tui, "CleanupJob", return_value=job):
            tui.run_tui(FakeScanner(), state_dir="/unused")
        self.assertEqual(screen.reads, 6)
        self.assertEqual(FakeScanner.initializations, 2)  # Initial scan + one post-batch rescan.
        self.assertEqual(FakeScanner.decision_calls, 2)  # Repaints reuse the stable analysis.
        self.assertTrue(any("Cleaning  " in frame and "1/2 · 50%" in frame for frame in screen.frames))
        self.assertTrue(any("CLEAN — DONE" in frame for frame in screen.frames))

    def test_saved_plan_passes_progress_to_cleaner(self):
        progress = lambda value: None
        plan = {"id": "fixture", "items": []}
        class FakeCleaner:
            def apply(self, actual, **kwargs):
                self.actual = actual
                self.progress = kwargs.get("progress")
                return {"entries": [], "completed": 0, "failed": 0}
        cleaner = FakeCleaner()
        with tempfile.TemporaryDirectory() as state:
            with patch("soji_cli.cleanup.create_plan", return_value=plan):
                result = tui.clean_targets(None, "careful", [], state, cleaner, progress)
            self.assertEqual(json.loads(Path(result["plan"]).read_text()), plan)
        self.assertIs(cleaner.progress, progress)
        self.assertIs(cleaner.actual, plan)


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
