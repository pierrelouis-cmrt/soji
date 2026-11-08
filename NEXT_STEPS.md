# Status and open work

## Decisions

- Terminal command only, in the style of mole. No daemon, login item, scheduled runs or notifications. `routines` and `auto` run only when invoked.
- AI is agent-driven: `soji --ai`, then `ai inspect`, `ai propose`, and finally `clean`. `analyse` (soji launching an agent) is legacy and gets no further work.
- Excluded: GUI, licensing, updater, telemetry, notifications, background/login items, and system or privileged package removal.

## Safety choices

- Retention keeps the newest rows by timestamp and also by version label, so the highest version is never removed because an older one was touched later.
- Spare simulators (no apps, same name and runtime as another device) stay on a 7-day Balanced judgement; simulators whose runtime is not installed use levels 7 d / 1 d / 1 h.
- With a per-item agent judgement, selection follows the judgement's idle levels and the rule level is ignored, but only for rows with a judged minimum.
- Selectable catch-alls (`~/Library/Caches/*`) split around nested specific hints; the remainder keeps the catch-all; roots never inherit.
- Project-root agent activity also feeds the project clock. Compressed Codex `.jsonl.zst` rollouts are read on Python 3.14+; on older Pythons each one must be listed in Codex's `state_*.sqlite`, otherwise activity is marked incomplete and project-age rules hold.
- Agents get a standalone copy of the index; writes to it and its SQLite sidecars are denied, and queries outside the scanned roots are refused.
- Uninstall lists shared leftovers (another app, Apple, another user's receipt) but never removes them.

## Regression corpus

- `tests/corpus.py` builds a fake home and scans it hermetically: processes, open files, `/Applications`, simctl/devicectl and the native helper are pinned. Git runs for real under `GIT_CEILING_DIRECTORIES`.
- `tests/test_corpus.py` diffs the scan against `tests/corpus_expected.json`. After an intended behavior change, run `SOJI_UPDATE_CORPUS=1 python3 -m unittest tests.test_corpus` and review the golden diff in the commit.
- `scripts/corpus_export.py --keep DIR` keeps the fake home; `--diff FILE` compares two normalized exports.

## Open

| Item | Where | Note |
|---|---|---|
| Worktree activity in the parent project clock | `engine.project_age` | `<project>/.claude/worktrees` counts as project use; unverified |
| Outside link to a small single-link file | `index.reconcile` | Files ≥ 1 MiB (largest 20,000) are re-checked on every incremental run; smaller ones wait for the weekly full check. Estimates only; cleanup re-measures |
| Unreadable rows in a reusable index | `index.IndexedScanner.run` | A finished walk with TCC-denied folders stays reusable (`reusable`/`walkedAt` meta). Each denied open costs a TCC check (~7 ms), so incremental runs probe 16 spread unreadable rows and re-walk all of them only if one became readable. A grant that unlocks none of the probed rows waits for the weekly full walk or `--refresh`; unreadable rows always hold their findings. `complete` still gates snapshots and `fullCheckedAt` |
| Native walk outside APFS | `SojiNative.swift` `walk` | Compressed and hard-linked entries use bulk attributes on APFS (verified equal to `lstat`); other filesystems re-read them with `fstatat`. Run `scripts/walk_parity.py` on a new filesystem type before trusting it |
| Native busy filter, settle measurement | `SojiNative.swift`, `nativeplans.py` | Any `xcodebuild`/`simctl` process holds; no free-space check after a tool command |
| Cross-volume Trash moves | `cleanup.py` | Refused |
| System receipts, uninstalled co-owners | `uninstall.py` | Excluded |

## Validation

```sh
python3 -m unittest discover -s tests -q
SOJI_TEST_NATIVE="$PWD/soji_cli/native-bin/soji-native" python3 -m unittest discover -s tests -p 'test_index_store.py' -q
python3 scripts/native_integration.py     # real FSEvents, fake agent; no model call
python3 scripts/walk_parity.py ~/Library ~/code   # native walk == Python walk, node for node (read-only)
python3 build_release.py                  # needs Xcode CLT; see README "Publishing a release"
python3 dist/soji.pyz --version
```

Destructive paths are tested only on disposable fixtures.
