# Status and open work

## Decisions

- Terminal command only, in the style of mole. No daemon, login item, scheduled runs or notifications. `routines` and `auto` run only when invoked.
- AI is agent-driven: `soji --ai`, then `ai inspect`, `ai propose`, and finally `clean`. `analyse` (soji launching an agent) is legacy and gets no further parity work.
- The original-app comparison (corpus run, early-rule confirmation) is owner-run.

## Regression corpus

- `tests/corpus.py` builds a fake home and scans it hermetically: processes, open files, `/Applications`, simctl/devicectl and the native helper are pinned. Git runs for real under `GIT_CEILING_DIRECTORIES`.
- `tests/test_corpus.py` diffs the scan against `tests/corpus_expected.json`. After an intended behavior change, run `SOJI_UPDATE_CORPUS=1 python3 -m unittest tests.test_corpus` and review the golden diff in the commit.
- `scripts/corpus_export.py --keep DIR` keeps the fake home for an original-app run; `--diff FILE` compares a normalized export.

## Open

| Item | Where | Note |
|---|---|---|
| Original-app corpus run | owner | No safe fake-home entry point found in the original (research/consumer-observation.md) |
| Costly-tier verifier adjustment | `levels.combine_rule_level` | Flag source unresolved; omitted. Simulators are the costly rows it matters for: the hint text says spare twins go "from Balanced", which needs the flag, so the port keeps its stricter 7-day judgement for twins |
| Worktree activity in the parent project clock | `engine.project_age` | `<project>/.claude/worktrees` counts as project use; unverified |
| Outside link to a small single-link file | `index.reconcile` | Files ≥ 1 MiB (largest 20,000) are re-checked on every incremental run; smaller ones wait for the weekly full check. Estimates only |
| Unreadable rows in a reusable index | `index.IndexedScanner.run` | Port choice: a finished walk with TCC-denied folders stays reusable (`reusable`/`walkedAt` meta). Each denied open costs a TCC check (~7 ms), so incremental runs probe 16 spread unreadable rows and re-walk all of them only if one became readable. A grant that unlocks none of the probed rows waits for the weekly full walk or `--refresh`; unreadable rows always hold their findings. `complete` still gates snapshots and `fullCheckedAt` |
| Native walk parity outside APFS | `SojiNative.swift` `walk` | Compressed and hard-linked entries use bulk attributes on APFS (verified equal to `lstat`); other filesystems re-read them with `fstatat`. Run `scripts/walk_parity.py` on a new filesystem type before trusting it |
| Native busy filter, settle measurement | `SojiNative.swift`, `nativeplans.py` | Conservative holds |
| System receipts, uninstalled co-owners | `uninstall.py` | Excluded |

## Validation

```sh
python3 -m unittest discover -s tests -q
SOJI_TEST_NATIVE="$PWD/soji_cli/native-bin/soji-native" python3 -m unittest discover -s tests -p 'test_index_recovery.py' -q
python3 scripts/native_integration.py     # real FSEvents, fake agent; no model call
python3 scripts/walk_parity.py ~/Library ~/code   # native walk == Python walk, node for node (read-only)
python3 build_release.py                  # needs Xcode CLT; universal helper
python3 dist/soji.pyz --version
```

Destructive paths are tested only on disposable fixtures.
