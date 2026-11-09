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

## November 8 safety audit (2026-11-09)

- [Evidence, additional findings and staged validation](docs/audit-2026-11-08.md). TUI now warns about aggressive software/runtime/dependency damage and Trash-only undo before confirmation and after completion; confirmation/results scroll, and moved bytes are no longer called freed space.
- Historical audit snapshot: baseline runtime fragmentation, shipped dependency selection, renamed-session retention, journal policy metadata/missing-Trash classification and owner-running consistency were unresolved during the TUI audit. The later Opus patch below implements the baseline fixes; do not reimplement them from this historical bullet. Independent review of residual gaps remains necessary. Do not validate by running broad real-home cleanup.
- Keep destructive validation inside `tests/corpus.py` fake homes with disposable Trash. Review all selected paths and affected software before any later real validation; emptied Trash cannot supply undo data. Preserve user repair/restore scripts.

- Independent review adds four open P1 gates: permanent-stage rollback overwriting newly recreated user data; ignored files lost by permanent Git worktree removal; fresh cleanup checks losing project-pin scope; chained nvm default aliases left unprotected. Details and regression suggestions are in the audit. These are fixture-confirmed findings, not witnessed causes in the November 8 journal. Review newer shared-workspace engine/install changes separately before updating baseline status.

- Post-Opus overlap check: read the completed Opus result, re-ran all 15 November regression tests (OK), then re-ran the archived independent fixtures on the current checkout. All four additional P1 defects still reproduce. The next implementation scope is these four defects; baseline/TUI changes should be preserved and independently reviewed, not rebuilt. See [the updated orchestrator handoff](docs/SAFETY_ORCHESTRATOR_PROMPT.md). Opus reports a full 285-test run (OK, two skipped) and 27 native index tests; those broader runs were not repeated during this overlap check.

## Changelog: version policy context (2026-11-09)

- Project pins at cleanup time: `Cleaner.fresh` no longer judges pins from its target-scoped walk. `SpecializedRules.pins` rediscovers pin files live across the plan roots plus the home (Scanner exclusions, never from the index); a pin created after the plan refuses fresh/apply, and an unreadable folder or pin file or the 120 s / 5 M entry limit refuses as "Project pin discovery incomplete". Full scans reuse their nodes only when the walk covered the home without errors; otherwise they also discover live and hold on incomplete discovery.
- nvm aliases: `~/.nvm/alias/default` and `.nvmrc` aliases resolve through `NvmAliases` (chains, `lts/*`, `node`/`stable`, `system`, partial versions; 16-hop limit, cycle detection, confined to `alias/`, no symlinks). Uncertain resolution holds the whole nvm family.
- Regressions: `tests/test_version_policy_context.py`; corpus gained `~/.nvm/versions/node/v16.0.0` (pinned through `lts/gallium`) and its default became the `lts/*` -> `lts/iron` chain (v20.1.0 row unchanged).

## Changelog: November 8 fixes (2026-11-09)

Each item has a regression in `tests/test_nov8_regressions.py` (fake home, every mode), and the corpus gained the same paths. Golden rows were only added; none changed.

- **Toolchains are whole units.** Groups `Toolchains and SDKs` and `Editor extensions` (`installs.ATOMIC_GROUPS`) are never split around nested hints or descended for review, so a runtime is selected whole or not at all. The split of `codex-runtime-install-L2Mqle` into ~50 rows caused the damage. Every row is now held while a running process's executable lives inside it, on top of the open-file and newest-change guards that already applied to the whole subtree.
- **Codex runtimes.** `codex-runtimes` matches only `codex-runtime-install-*` and keeps the newest install by time and version. The new `checkCodexRuntime` holds the install matching `codex-primary-runtime`, the highest bundle version and any unreadable one. Superseded installs stay candidates.
- **Installed software is not a project.** Rows inside `installs.INSTALL_LOCATIONS` (editor/Raycast/Zed extensions, Electron `app-*`, `~/.t3/tools`, Codex runtimes and releases), inside an atomic-rule match, or under a folder with an extension/app manifest (not counting a VCS checkout) are held in every mode. `Project dependencies` and `Build output` `**/` rules never match there or anywhere under `~/Library`, and dependency rules need a lockfile or a VCS checkout.
- **Renamed projects.** A missing session cwd is "gone" only with no rename/move signal: parent present, no Git remote of that name, no registered worktree, main repository found for a worktree, no sibling project whose use began as this one stopped, and complete activity history. Sessions changed within 24 h are never taken at Careful/Balanced, whatever levels or judgement apply (`Finding.decide`).
- **Journal.** Entries record `mode`, `version`, `planCreatedAt`, `rule` and `policy` (rule, threshold applied, reason, decision; from the fresh check). `soji journal` adds `recovery`/`recoverable` and reports `unrecoverable (Trash emptied)`. `soji undo` says so instead of failing obscurely. Plans and apply results carry the Trash-only undo notice, and plans warn about high-risk groups.
- **In-use refusals stick.** A fresh-guard refusal for live use (open files, owner app running, running program, agent activity) refuses the same path for 24 h, rather than retrying until a momentary snapshot passes (the Obsidian `Code Cache` case).
- **Permanent-stage rollback never replaces.** If a permanent removal fails after staging `.soji-removing-*` but before removal starts, `Cleaner.rollback_staged` restores only with `platform.rename_exclusive` (`renameatx_np` + `RENAME_EXCL`, files and directories). A recreated original (file, empty or non-empty directory), a changed staged identity, an unsupported file system or any rename error keeps both objects, records `rollback`/`stagedPath` (best-effort journal) and says so in the error; `soji recover` lists them as `rollbackKept` and `soji journal` labels them `staged copy kept for manual review: <path>`; nothing acts on them. Staging itself is exclusive too (unavailable → nothing moves), rollback runs only once staging succeeded, a different object staged by an app's atomic save is put back (`restored-other-identity`), and a persistently failing journal no longer aborts `apply` (entries/result carry `journalError`). The scanner holds every `.soji-removing-*` object and any row containing one, in all modes. No replacing-rename fallback. Regressions: `tests/test_permanent_rollback.py`.
- **Ignored worktree data.** Agent worktrees are removed only when every ignored entry is known regenerable output (`gitstate.DISPOSABLE_IGNORED_*`); other ignored data, or an incomplete inventory, holds the worktree in every mode and refuses `tool_action` at execution time. Regressions in `tests/test_worktree_ignored.py`; corpus gained two `~/.codex/worktrees` rows.
- Open: `checkCodexRuntime` relies on Codex's current folder layout. Rename detection has no stored repo identity (root commit) yet; Sōji could record path → root commit for active projects to tell renames apart from deletions.

## Journal/undo/refusal follow-up (2026-11-09, isolated branch)

`fix/journal-undo-refusal-sol-20261109` builds on `9651c55` without altering its exclusive staging/rollback implementation. It records agent provenance plus planned/fresh policy, checks Trash identity and unreadability, derives partial recovery from members, stores structured refusal codes with overlapping-path memory and a non-renewing 24 h timestamp, and blocks cleanup on malformed/unreadable refusal history. Missing running-app inventories hold owner-dependent rules and surface a scan warning. Shared risk groups drive plan/TUI warnings; failed TUI restores remain retryable. Staged objects, ancestors and descendants are held, including catalog rows and fresh native/uninstall early returns. Tests and remaining limits: `docs/journal-undo-refusal-2026-11-09.md`. This is an isolated implementation, not an integration/review or permission for real cleanup.

### Worktree second-review follow-up (2026-11-09)

On the replacement branch based on `52bb0e5`, P1-1/2/3 now have guards for
itself-ignored directories, bounded content walks with no nested `.git`, and
hidden index edits/core.ignoreStat. Inspection and removal sanitize inherited
Git environment; decoding failure is unverified. Original tests and reviewer
proof tests are preserved; optional cache expansion was omitted. See
`docs/WORKTREE_SAFETY_VALIDATION_2026-11-09.md` for exact validation and the audit
for the unresolved concurrent-mutation race. This work is local and still needs
independent review/integration; it does not certify the installed application.
