# Independent execution/mutation boundary cross-review

Verdict: **changes required** — two proven P2 refusal-history gaps below. No new P1 demonstrated in this scope. The worktree feature must remain disabled.

Exact reviewed/tested integrated SHA: `82da2481f6749f82a91ae8a8fb8ce3c02d89ad03`; base `21ce749`. Confirmed no code/test difference between integrated head and `8d8e6cb`. Prepared isolated checkout: `/Users/pierrelouis/.t3/worktrees/soji/t3-80ba31bf`; unique local branch `review/execution-integrated-82da248-20261109`. Only this report and the independent proof test are added. No implementation changes.

Read the orchestration prompt, integrated safety status, audit, journal implementation evidence, baseline-to-head boundary changes and relevant fixtures. Rechecked adapted proof `1fe232c` and D/native proofs `10aa59e` / `8dcf712` against the integrated corrections instead of treating earlier author reports as approval. Runtime/project/pin/session policy review belongs to the other reviewer; compound session mutation and undo are covered here.

## P2: corrupt nonfinite refusal timestamps silently permit cleanup

Location: `soji_cli/cleanup.py:645-647` and `:286-288`.

Strict journal reading accepts any Python float for `at`, and does not validate `refusalAt`. Python's JSON reader accepts `NaN`. A structured active-use refusal with either timestamp set to NaN passes strict history reading, but `now - at < LIVE_USE_HOLD` is false. The refusal disappears from policy and cleanup proceeds instead of treating the history as unknown. This contradicts the fail-closed corruption guarantee.

Confined proof: `ExecutionBoundaryProofs.test_nonfinite_refusal_timestamp_blocks_mutation`, subtests `at` and `refusalAt`. Each creates a separate disposable fake home/state/Trash via JournalSafety, plans a real eligible npx cache, writes a corrupt structured refusal, and calls real `Cleaner.apply`. Each preservation assertion fails: result `completed=1`, `status=done`, with the cache moved to fixture Trash. No filesystem guard is mocked. Host process, apps, metadata and tool inventories are isolated by `corpus.hermetic`.

Minimal fix: strict validation must require finite numeric timestamps (excluding booleans), including explicit `refusalAt` and member timestamps used for cooldown. Reject invalid numeric constants during JSON decoding or validate with `math.isfinite` before arithmetic. Raise `SafetyRefusal(..., 'history-unknown')` rather than dropping an uncertain refusal. Keep legitimate finite expired-history controls.

## P2: running-app uninstall refusal bypasses the 24-hour cooldown

Location: `soji_cli/uninstall.py:96`; fallback classification at `soji_cli/cleanup.py:19-30,37-40`.

Fresh uninstall raises plain `ValueError('App is running')`. This wording matches none of the live-use reasons, so the recorded failed entry has no `refusalCode` and is not recognized by later history reads. An immediate retry with a successful empty running-app snapshot moves the application to Trash. The common cooldown logic executes before the uninstall verifier but has no classified refusal to enforce. Unknown-inventory blocking is fixed; this is a distinct positive-running refusal history omission.

Confined proof: `ExecutionBoundaryProofs.test_running_uninstall_refusal_blocks_immediate_retry`. A disposable app bundle is planned against a mocked successful empty inventory. First apply observes the app in a mocked running inventory and refuses with `App is running`; same-plan immediate retry observes an empty snapshot and reports `completed=1`, moving the fake app to fixture Trash. Code-signing and receipt inputs are mocked. No real app is inventoried or moved. The proof establishes a missing cooldown, not that the fake app remained running after the snapshot changed.

Minimal fix: raise a structured active-use `SafetyRefusal` from the fresh running-app rejection; preserve timestamp and overlapping-path cooldown behavior. Add an expired-hold positive control. Do not weaken the new `running_available` requirement.

## Corrections verified and intentional conservative behavior

- Worktree selection is held across careful/balanced/aggressive, proposals are rechecked by `Scanner.decisions`, fresh refuses old/forged/actionless plans and recognized metadata-stripped descendants before filesystem fallback, and direct `tool_action(git-worktree)` always refuses. The adapted residuals preserve unique ignored notes, bare-repository-only commits, symlink targets and concurrent-writer fixture bytes; the Git remove boundary is unreachable. Diagnostic `contentsVerified` remains insufficient evidence of disposability; disabling is intentional, not a request to restore removal.
- Permanent staging and rollback use atomic exclusive rename with no replacing fallback. File/empty-directory/nonempty-directory conflicts retain both objects; replacement before staging is returned safely and reported as another identity. Unavailable primitive and rollback I/O failure preserve staging. Recovery inspection does not auto-restore kept conflicts.
- Staged roots/interiors are held even when the staged ancestor is outside scan roots. Measured containers and synthetic catalog rows receive holds. Native/uninstall early returns check directory descendants, budgets and errors; ordinary document-version files are not incorrectly walked as directories.
- Strict checkpoint failures retain `journalError` even when a later append succeeds. Final best-effort append failure retains the actual completed mutation status. Pre-removal checkpoint failure prevents removal and triggers exclusive rollback; interrupted removal retains uncertainty/partial-deletion metadata.
- Fresh native/uninstall success contains verifier evidence, null inapplicable age threshold, fresh source and separate planned policy. Legacy journal entries are not retroactively assigned a mode. Ordinary document-version positive control succeeds. Unavailable running inventory blocks both uninstall plan creation and fresh apply; successful empty inventory remains usable.
- Existing finite refusal overlap, sibling separation, original-clock expiry and batch invalidation tests pass. Compound cleanup/undo and partial failure tests pass. A new real fixture proof fails one sidecar restore after transcript restoration, retries undo and confirms the transcript restore ran once, the failed sidecar twice, and remaining content restored. TUI failed-undo retry tests pass.
- Incomplete inventories/staging measurements and unavailable native primitives remain conservative refusals. Persistent journal failure cannot supply durable missing records. Snapshot-to-mutation races outside the disabled worktree route remain limitations, not claims eliminated by these tests.

## Actual validation

Commands run at the exact integrated implementation, with only independent review tests added:

```
python3 -m unittest tests.test_independent_d tests.test_journal_refusal_safety tests.test_permanent_rollback tests.test_review_68aff51_residuals tests.test_worktree_ignored tests.test_review_worktree_gaps tests.test_tui_clean tests.test_cleanup_safety tests.test_cleanup_batch tests.test_uninstall_identity -q
```

139 tests, OK, zero skips, 38.533 s. Output: `/private/tmp/soji-execution-crossreview-tests.txt`.

```
SOJI_NATIVE_WALK_HELPER=/private/tmp/soji-native-integration-20261109/soji-native SOJI_TEST_NATIVE=/private/tmp/soji-native-integration-20261109/soji-native python3 -m unittest tests.test_native_walk tests.test_index_store.NativeRecovery -q
```

10 tests, OK, zero skips, 0.639 s. Output: `/private/tmp/soji-execution-crossreview-native.txt`. Inspected native walk/metadata/event-id/version removal dispatch and test confinement first. Used supplied helper, no build/install; exercised only disposable walks, metadata, event-id, missing-file versions and invalid-token remove-version. No native apps or Trash calls.

```
python3 -m unittest tests.test_compound_sessions tests.test_review_execution_82da248.ExecutionBoundaryProofs.test_compound_undo_retry_keeps_prior_successes -q
```

13 tests, OK, zero skips, 1.678 s. Output: `/private/tmp/soji-execution-crossreview-compound.txt`.

```
python3 -m unittest tests.test_review_execution_82da248.ExecutionBoundaryProofs -v
```

Three test methods: compound retry passes; two safety methods intentionally fail with three assertion failures (two timestamp subtests and uninstall retry). These are preservation assertions exposing the two findings, not an approved green regression suite. Output: `/private/tmp/soji-execution-crossreview-proofs-final.txt`.

`git diff --check`: exit 0. `git diff --exit-code 21ce749 -- soji-repair.sh soji-restore.sh`: exit 0. Recovery scripts were neither executed nor changed.

No full-suite rerun, physical-terminal validation, real-TCC experiment, installed-binary claim, real-home scan, cleanup/Trash/repair/restore, network Git, push, PR, install or release. All destructive experiments used disposable fake homes/state/Trash/repos; real-home paths in historical documentation were read as text only. Original/main/other worktrees were not modified. No children were started.
