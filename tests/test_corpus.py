"""Golden regression over the synthetic corpus (see tests/corpus.py).

Regenerate after an intentional behavior change and review the diff:
    SOJI_UPDATE_CORPUS=1 python3 -m unittest tests.test_corpus
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402

EXPECTED = Path(__file__).resolve().parent / 'corpus_expected.json'


@unittest.skipUnless(sys.platform == 'darwin', 'corpus byte counts assume APFS allocation')
class CorpusRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='tmp-corpus-', dir=Path(__file__).resolve().parent)
        home = Path(cls.temp.name) / 'home'
        home.mkdir()
        corpus.build_corpus(home)
        cls.rows = corpus.scan_corpus(home)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_matches_golden(self):
        if os.environ.get('SOJI_UPDATE_CORPUS'):
            EXPECTED.write_text(json.dumps(self.rows, indent=1, sort_keys=True) + '\n')
        expected = json.loads(EXPECTED.read_text())
        diff = corpus.diff_rows(expected, self.rows)
        self.assertFalse(diff, 'Corpus rows changed (SOJI_UPDATE_CORPUS=1 to accept):\n' + '\n'.join(diff))

    def test_modes_are_cumulative(self):
        for row in self.rows:
            picks = [row[m]['selected'] for m in corpus.MODES]
            self.assertEqual(picks, sorted(picks), row['path'])

    def test_installed_software_and_active_runtime_never_selected(self):
        # November 8: shipped code and the runtime in use, in every mode.
        never = ('~/.vscode/extensions/', '~/.config/raycast/extensions/', '~/Library/Application Support/Zed/',
                 '~/Library/Application Support/discord/app-', '~/.t3/tools/', '~/.cache/codex-runtimes/codex-primary-runtime',
                 '~/.cache/codex-runtimes/codex-runtime-install-L2Mqle', '~/code/loose-web/')
        for row in self.rows:
            if row['path'].startswith(never):
                self.assertFalse(any(row[m]['selected'] for m in corpus.MODES), row['path'])
                self.assertNotIn(row['group'], ('Project dependencies', 'Build output'), row['path'])
        # The corpus keeps the November 8 layout: codex-primary-runtime is an
        # extracted directory, so nothing positively identifies the install in
        # use and the older one is held too (positive supersession through a
        # primary link is covered by tests/test_runtime_supersession.py).
        superseded = next(r for r in self.rows if r['path'].endswith('codex-runtime-install-wDayCH'))
        self.assertFalse(any(superseded[m]['selected'] for m in corpus.MODES), superseded)

    def test_renamed_project_sessions_not_downgraded(self):
        row = next(r for r in self.rows if r['path'].endswith('-code-old-name/renamed.jsonl'))
        self.assertFalse(row['balanced']['selected'], row)

    def test_held_rows_never_selected(self):
        for row in self.rows:
            if row['holds']:
                self.assertFalse(any(row[m]['selected'] for m in corpus.MODES), row['path'])


if __name__ == '__main__':
    unittest.main()
