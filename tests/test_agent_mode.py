"""soji --ai: briefing, inspect and guarded proposals on the synthetic corpus."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402
from soji_cli import agent  # noqa: E402
from soji_cli.engine import Scanner  # noqa: E402


@unittest.skipUnless(sys.platform == 'darwin', 'corpus assumes APFS allocation')
class AgentModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name).resolve()
        self.home = base / 'home'; self.home.mkdir()
        self.state = base / 'state'
        corpus.build_corpus(self.home)
        self.ctx = corpus.hermetic(str(self.home)); self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)
        self.temp.cleanup()

    def scanner(self, data=None):
        roots = data['roots'] if data else [str(self.home)]
        return Scanner(roots, home=str(self.home), min_bytes=corpus.MIN_BYTES, protected=[str(self.state)])

    def brief(self, mode='balanced'):
        s = self.scanner(); s.run()
        b = agent.brief(s, self.state, mode, limit=500)
        return b, {r['path']: r['id'] for r in b['rows']}

    def propose(self, b, verdicts):
        return agent.propose(self.state, b['session'], {'verdicts': verdicts}, self.scanner,
                             output=Path(self.temp.name) / 'plan.json')

    def test_render_puts_rules_before_data(self):
        b, _ = self.brief()
        text = agent.render(b)
        self.assertLess(text.index('Never delete'), text.index('```jsonl'))
        rows = [json.loads(l) for l in text.split('```jsonl\n')[1].split('\n```')[0].splitlines()]
        self.assertEqual(len(rows), b['totalRows'])
        self.assertTrue(all(r['path'].startswith('~/') for r in rows))

    def test_guards_on_proposals(self):
        b, ids = self.brief('balanced')
        verdicts = [
            {'id': ids['~/Library/Caches/com.example.Known'], 'action': 'remove', 'reason': 'app cache'},
            {'id': ids['~/.nvm/versions/node/v18.0.0'], 'action': 'remove', 'reason': 'unused old node'},
            {'id': ids['~/code/dirty-web/node_modules'], 'action': 'remove', 'reason': 'try held'},
            {'id': ids['~/Documents/report.pdf'], 'action': 'remove', 'reason': 'try personal'},
            {'id': ids['~/.nvm/versions/node/v20.1.0'], 'action': 'remove', 'reason': 'try active'},
            {'id': 'deadbeef00', 'action': 'remove', 'reason': 'invented'},
            {'id': ids['~/Downloads/photos.zip'], 'action': 'review', 'reason': 'ask'},
            {'id': ids['~/Library/Caches/com.example.Known'], 'action': 'keep', 'reason': 'dup'},
        ]
        r = self.propose(b, verdicts)
        accepted = {a['path'] for a in r['accepted']}
        self.assertEqual(accepted, {'~/Library/Caches/com.example.Known', '~/.nvm/versions/node/v18.0.0'})
        reasons = {x['id']: x['reason'] for x in r['rejected']}
        self.assertIn('Uncommitted', reasons[ids['~/code/dirty-web/node_modules']])
        self.assertIn('Listed for review', reasons[ids['~/Documents/report.pdf']])
        self.assertIn('Active version', reasons[ids['~/.nvm/versions/node/v20.1.0']])
        self.assertIn('Unknown id', reasons['deadbeef00'])
        self.assertEqual(reasons[ids['~/Library/Caches/com.example.Known']], 'Duplicate verdict')
        plan = json.loads(Path(r['plan']).read_text())
        self.assertEqual(len(plan['items']), 2)
        # The plan revalidates through the normal cleanup path, agent judgment included.
        from soji_cli.cleanup import Cleaner
        cleaner = Cleaner(self.state)
        for item in plan['items']:
            self.assertEqual(cleaner.fresh(item, plan), item['identity'])

    def test_changed_since_briefing_is_rejected(self):
        b, ids = self.brief()
        target = self.home / 'Library/Caches/com.example.Known/blob'
        target.write_bytes(b'y' * corpus.PAYLOAD * 2)
        old = time.time() - 10 * 86400
        os.utime(target, (old, old))
        r = self.propose(b, [{'id': ids['~/Library/Caches/com.example.Known'], 'action': 'remove', 'reason': 'x'}])
        self.assertFalse(r['accepted'])
        self.assertIn('Changed', r['rejected'][0]['reason'])

    def test_inspect_and_session_checks(self):
        b, ids = self.brief()
        d = agent.inspect(self.state, b['session'], ids['~/code/old-web/node_modules'])
        self.assertEqual(d['largestChildren'][0]['name'], 'lib')
        self.assertTrue(any(s['path'] == '~/code/clean-web/node_modules' for s in d['sameRule']))
        with self.assertRaises(ValueError):
            agent.inspect(self.state, b['session'], 'nope')
        with self.assertRaises(ValueError):
            agent.load_session(self.state, '../../etc')
        with self.assertRaises(ValueError):
            agent.propose(self.state, b['session'], {'verdicts': {}}, self.scanner)


if __name__ == '__main__':
    unittest.main()
