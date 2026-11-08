#!/usr/bin/env python3
"""Compare the native bulk walk with Scanner.visit on real directories.

Read-only. Every node field, node order, children order and scanner counter
must match. Usage: python3 scripts/walk_parity.py [--helper PATH] DIR...
Exit status 1 on any difference. Live trees can change between the two walks;
rerun, or point it at a quiet tree, before treating a difference as a bug.
"""
import argparse
import dataclasses
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from soji_cli.engine import Node, Scanner  # noqa: E402
from soji_cli import walker  # noqa: E402

FIELDS = [f.name for f in dataclasses.fields(Node)]
COUNTERS = ('visited', 'bytes', 'unreadable', 'skipped', 'limited')


def measure(roots, native, **kw):
    s = Scanner(roots, min_bytes=0, context=False, max_seconds=3600, **kw)
    s.started = time.monotonic()
    t = time.perf_counter()
    items = [(r, 0, None, False) for r in s.roots]
    if native:
        if not walker.walk(s, items):
            raise SystemExit('native walk failed or helper unavailable')
    else:
        for path, depth, device, _ in items:
            if not s.budget():
                break
            s.visit(path, depth, device)
    return s, time.perf_counter() - t


def unstable(a, b):
    """Paths that changed between two Python walks, plus their ancestors."""
    moving = set(a.nodes).symmetric_difference(b.nodes)
    moving |= {p for p, x in a.nodes.items() if p in b.nodes and
               any(getattr(x, f) != getattr(b.nodes[p], f) for f in FIELDS if f != 'children')}
    out = set()
    for p in moving:
        while p not in out:
            out.add(p)
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
    return out


def compare(a, b, limit=20, ignore=frozenset()):
    problems = []
    if [p for p in a.nodes if p not in ignore] != [p for p in b.nodes if p not in ignore]:
        only_a = [p for p in a.nodes if p not in b.nodes]
        only_b = [p for p in b.nodes if p not in a.nodes]
        problems.append(f'node order/set differs: {len(only_a)} python-only, {len(only_b)} native-only'
                        + (f' e.g. {only_a[:2]} {only_b[:2]}' if only_a or only_b else ' (order only)'))
    for path, x in a.nodes.items():
        y = b.nodes.get(path)
        if y is None or path in ignore:
            continue
        for field in FIELDS:
            if getattr(x, field) != getattr(y, field):
                problems.append(f'{path}: {field} python={getattr(x, field)!r} native={getattr(y, field)!r}')
                break
        if len(problems) >= limit:
            break
    for counter in COUNTERS if not ignore else ():
        if getattr(a, counter) != getattr(b, counter):
            problems.append(f'{counter}: python={getattr(a, counter)} native={getattr(b, counter)}')
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('roots', nargs='+')
    parser.add_argument('--helper')
    parser.add_argument('--max-files', type=int, default=2_000_000)
    args = parser.parse_args()
    if args.helper:
        os.environ['SOJI_NATIVE_WALK_HELPER'] = args.helper
    roots = [os.path.expanduser(r) for r in args.roots]
    before, _ = measure(roots, False, max_files=args.max_files)
    native, native_time = measure(roots, True, max_files=args.max_files)
    python, python_time = measure(roots, False, max_files=args.max_files)
    # Entries that changed while walking are excluded (and listed by count).
    moving = unstable(before, python)
    problems = compare(python, native, ignore=moving)
    print(f'{len(python.nodes):,} nodes · python {python_time:.2f}s · native {native_time:.2f}s'
          + (f' · {len(moving)} changing paths ignored' if moving else ''))
    for line in problems:
        print('  ' + line)
    print('MATCH' if not problems else f'{len(problems)} difference(s)')
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
