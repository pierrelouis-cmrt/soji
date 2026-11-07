#!/usr/bin/env python3
"""Build the synthetic corpus, scan it hermetically and print normalized rows.

    python3 scripts/corpus_export.py                    # rows as JSON
    python3 scripts/corpus_export.py --keep DIR         # also keep the corpus home
    python3 scripts/corpus_export.py --diff OTHER.json  # compare with another row export

`--keep` leaves a fake home that another implementation can be pointed at; its
results must be normalized to the same row shape before `--diff`.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import corpus  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--keep', type=Path, help='build the corpus here (must not exist) and keep it')
    ap.add_argument('--diff', type=Path, help='row export to compare against; exit 1 on differences')
    ap.add_argument('--output', type=Path, help='write rows here instead of stdout')
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix='soji-corpus-') as tmp:
        home = args.keep or Path(tmp) / 'home'
        home.mkdir(parents=True, exist_ok=False)
        corpus.build_corpus(home)
        rows = corpus.scan_corpus(home)
    text = json.dumps(rows, indent=1, sort_keys=True) + '\n'
    if args.output:
        args.output.write_text(text)
    elif not args.diff:
        sys.stdout.write(text)
    if args.diff:
        diff = corpus.diff_rows(json.loads(args.diff.read_text()), rows)
        print('\n'.join(diff) if diff else 'No differences.')
        return 1 if diff else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
