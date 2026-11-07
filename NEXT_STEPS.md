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
| Costly-tier verifier adjustment | `levels.combine_rule_level` | Flag source unresolved; omitted |
| Device-build supersession, simulator twins | `specialized.py` | Unported early branches |
| `.jsonl.zst` Codex rollouts | `catalogs.py`, `activity.py` | No metadata read |
| Worktree activity in the parent project clock | `engine.project_age` | `<project>/.claude/worktrees` counts as project use; unverified |
| Outside link to a single-link file | `index.reconcile` | Caught by the weekly full check; estimates only |
| Native busy filter, settle measurement | `SojiNative.swift`, `nativeplans.py` | Conservative holds |
| System receipts, uninstalled co-owners | `uninstall.py` | Excluded |
| `soji --ai` refinements | `agent.py` | Per-row idle thresholds; grouping for very large briefings |
| Hermetic uninstall tests | `tests/` | Older tests call real `codesign`/`pkgutil` on fake apps |

## Validation

```sh
python3 -m unittest discover -s tests -q
SOJI_TEST_NATIVE="$PWD/soji_cli/native-bin/soji-native" python3 -m unittest discover -s tests -p 'test_index_recovery.py' -q
python3 scripts/native_integration.py     # real FSEvents, fake agent; no model call
python3 build_release.py                  # needs Xcode CLT; universal helper
python3 dist/soji.pyz --version
```

Destructive paths are tested only on disposable fixtures.
