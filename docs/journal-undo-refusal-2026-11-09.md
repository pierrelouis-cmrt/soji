# Journal, undo and refusal implementation evidence

Branch: `fix/journal-undo-refusal-sol-20261109`. Base: `9651c55` (includes D). The old `t3-8ba7a644` checkout had no modified/untracked files to recover. Only this prepared isolated checkout was edited. Read the safety orchestration prompt, main's untracked status handoff, audit, November changelog/tests and incident journal read-only. No children, installs, network Git, pushes, releases or real-home scans/mutations. Recovery scripts remain unchanged.

## Design and files

- `cleanup.py`: policy records include actual agent judgment, source, recommendation, confidence and reason, with planned policy retained as `planPolicy` alongside the fresh `policy`. Legacy entries are read without synthesized provenance.
- `cleanup.py`: recovery uses the recorded Trash identity, with the same ctime-only exception as restore. Missing, changed/replaced, identity-unrecorded and unreadable objects have distinct statuses. Compound reports retain each member's status and consider any surviving recoverable member undoable.
- `cleanup.py`: new refusals carry `refusalCode`; identity/content changes are explicit exceptions. Old text-only entries retain a fallback. Memory checks ancestors and descendants on component boundaries, including member refusals. Malformed/unreadable history blocks cleanup instead of dropping evidence. New refusals invalidate batch caches. Cooldown retries preserve `refusalAt` rather than indefinitely renewing the original 24 h clock.
- `apps.py`, localized `engine.py` changes: validate running-app inventory availability; unknown inventories hold `notWhileOwnerRuns` rows and produce a scan warning. Successful empty inventories and positive owner-bundle detections remain supported.
- `safety.py`, localized `engine.py`/`cleanup.py`: shared staging boundaries protect descendants even when an ancestor is outside scan roots. Catalog rows get a final overlap hold; `Finding.decide` rejects synthetic descendant rows; fresh rejects staged descendants before native/uninstall early returns and checks those directories for staged contents. Native/uninstall inventories over 100,000 entries or unreadable directories block. D's rename/rollback implementation remains unchanged.
- `safety.py`, `tui.py`, `cleanup.py`: one six-group risk set supplies plan and TUI warnings. Successful undo rows update their status; failed rows remain in `lastBatch` for retry without redoing successes.
- `tests/corpus.py`: hermetic apps inventory now returns successful `[]` rather than a mock source failure. No golden changed or regenerated. Dedicated failure tests explicitly inject unavailable/malformed native inventories.
- `tests/test_journal_refusal_safety.py`: 20 regressions/controls; existing November, rollback, corpus and TUI tests retained.

## Before/after evidence

Exported `9651c55` using `git archive` into a disposable `/tmp` directory (not another worktree), then copied only the new test and the corrected hermetic inventory fixture into it. Running `python3 -m unittest tests.test_journal_refusal_safety -v` produced:

```
Ran 20 tests in 4.714s

FAILED (failures=15, errors=4)
```

The errors are expected assertions accessing newly required provenance/refusal fields absent from the baseline. Legacy-journal compatibility passed. The regressions demonstrate target replacement/unreadability, partial-member recovery, parent/child refusal propagation with sibling controls, content/identity mutation and retry, structured/fallback memory, truncated/unreadable history, original cooldown expiry, batch invalidation, owner inventory failure/positive controls, staged descendants/catalog/native bypasses, shared risk groups and failed-undo retry.

Final implementation: `python3 -m unittest tests.test_journal_refusal_safety -q`:

```
Ran 20 tests in 8.530s

OK
```

Final full suite: `python3 -m unittest discover -s tests -q` (verbatim):

```
----------------------------------------------------------------------
Ran 320 tests in 39.574s

OK (skipped=10)
```

`git diff --check`: exit 0, no output. The final full suite includes all 20 new tests and the existing 15 permanent rollback tests. `soji-repair.sh`, `soji-restore.sh` and `tests/corpus_expected.json` have no diff from `9651c55`.

## Remaining limitations and new findings

- Independent review and integration with A/B/C/runtime/shipped-dependency/session branches remain outstanding. This branch alone does not make real cleanup safe. Concurrent source scopes were preserved: no edits to specialized.py, installs.py, catalogs.py, gitstate.py or engine.running_inside.
- Native helper not compiled in this checkout: eight walk tests and two opt-in native recovery tests skip. No software installed or native helper built. Permission/TCC failures are mocked; tests do not certify a real macOS privacy configuration. Existing exclusive-rename fixture tests exercise macOS in disposable paths.
- Curses validation uses mocks/helpers, not a physical terminal. No installed binary was rebuilt or tested.
- Recovery classification checks current Trash identity; destination conflicts, later races, parent changes and native errors can still prevent an undo. Identity-unrecorded old entries intentionally report unknown. It does not promise recovery after Trash emptying.
- Refusal history corruption blocks future cleanup until a person investigates it; no automatic repair, speculative fragment parsing or data restoration is attempted. Journal writes remain best-effort as inherited from D; a permanently broken journal cannot provide durable evidence of events it never recorded.
- Process/app inventories remain bounded-time snapshots, not a lock against future use. Staging checks likewise do not eliminate filesystem races after verification.
- Additional confirmed baseline defect: failed TUI undo cleared the retry batch. Fixed here. Additional implementation issue found during self-check: recording cooldown retries could renew the hold forever; fixed by preserving the original timestamp. No other newly demonstrated out-of-scope bugs.
