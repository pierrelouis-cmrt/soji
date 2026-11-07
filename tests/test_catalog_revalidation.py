"""Cleanup revalidation re-derives Codex session and Trash rows from their catalog root."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus import hermetic  # noqa: E402
from soji_cli.cleanup import Cleaner, create_plan  # noqa: E402
from soji_cli.engine import Scanner  # noqa: E402

OLD = time.time() - 30 * 86400


class CatalogRevalidation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve() / 'home'
        for rel in ['.codex/sessions/2026/10/01/rollout-a.jsonl', '.Trash/old.bin']:
            p = self.home / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'x' * 8192)
        for folder, dirs, files in os.walk(self.home, topdown=False):
            for name in files + dirs:
                os.utime(Path(folder, name), (OLD, OLD))
        self.ctx = hermetic(str(self.home)); self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)
        self.temp.cleanup()

    def plan_and_fresh(self, target, hint, tick_trash=False):
        s = Scanner([str(self.home)], home=str(self.home), min_bytes=1)
        s.tick_trash = tick_trash
        s.run()
        plan = create_plan(s, 'balanced', paths={str(target)})
        self.assertEqual([i['hint'] for i in plan['items']], [hint])
        item = plan['items'][0]
        return Cleaner(Path(self.temp.name) / 'state').fresh(item, plan), item

    def test_codex_session_revalidates(self):
        identity, item = self.plan_and_fresh(self.home / '.codex/sessions/2026/10/01/rollout-a.jsonl', 'codex-sessions')
        self.assertEqual(identity, item['identity'])

    def test_trash_item_revalidates(self):
        identity, item = self.plan_and_fresh(self.home / '.Trash/old.bin', 'trash-item', tick_trash=True)
        self.assertEqual(identity, item['identity'])


if __name__ == '__main__':
    unittest.main()
