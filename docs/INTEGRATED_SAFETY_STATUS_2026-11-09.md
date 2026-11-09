# Provisional integrated Sōji safety status — 2026-11-09

Latest code/test head: `fc7d5eea93b930509f04694dc1e7bf945ecc4660`.
See [exact-head review follow-up](INTEGRATED_REVIEW_FOLLOWUP_2026-11-09.md).
The original integration record below is preserved chronologically.

Prepared checkout: `/Users/pierrelouis/.t3/worktrees/soji/t3-e54ebc38`.
Branch: `integration/safety-sol-20261109`; base: `21ce749`.
Implementation SHA: `d26dd11`; final code/test head: `8d8e6cb406070343a39d9b6e88626574573b1ba0` (documentation follows separately).
No main update, network Git, push, PR, release, install or real cleanup.
The installed binary is unchanged. Final approval remains blocked on a fresh
independent cross-review of this integrated implementation.

## Commit provenance and conflict resolution

Applied in the exact requested order, preserving each original as a separate
cherry-picked commit:

| Scope | Original | Integration |
|---|---|---|
| D exclusive rollback | `689174e` | `2e705c2` |
| D review follow-up | `9651c55` | `a56f54c` |
| Journal/undo/refusal + shared risk groups | `16c0699` | `3341cc3` |
| A ignored-file inventory | `52bb0e5` | `c8af7ec` |
| A hidden-index/nested Git checks | `68aff51` | `ab538b9` |
| B+C pin scope and nvm aliases | `e802e92` | `7f8eb5c` |
| Baseline reference/install/session corrections | `02155a8` | `84aaa86` |
| Baseline proof and limits | `5f81022` | `7e9ff6f` |
| Independent runtime-reference finding | new | `191ec58` |
| Parent-supplied blocking reviews | new | `d26dd11` |
| AI proposal hold regression expectation | new | `8d8e6cb` |

`NEXT_STEPS.md` and audit conflicts retain both chronological sections.
`tests/corpus.py` preserves hook/signing isolation, fixture Git discovery ceiling
through the production `git_env` wrapper, successful mocked empty apps inventory,
A's local-remote worktrees, B+C's alias-chain/pin fixtures, and the baseline's
real disposable project repositories. Production exclusion precedence and all
exclusive rename/rollback, staging, refusal-history and recovery guards survive.
No arbitrary ours/theirs resolution was used.

The initial golden merge combined rows by path against `21ce749`; overlapping
changes were checked, not regenerated. Later intentional policy changes were
reviewed before `SOJI_UPDATE_CORPUS=1 python3 -m unittest tests.test_corpus -q`:
only seven existing rows changed (three agent-worktree rows and four nvm rows).
The formerly selected safe worktree loses all selections; nvm v18 loses its
aggressive selection because discovery is unknown. Remaining changes explain
holds/actions. No new selection was accepted. Project/cache positive controls
and the original install/runtime/session corpus additions remain intact.

## Original requirements, additional P1 gates and TUI

| Requirement | Current implementation/evidence | State / limitation |
|---|---|---|
| 1 Runtime fragmentation/activity/supersession | Atomic roots/interior fresh refusal; positive primary reference + consistent metadata; process realpath; runtime/November tests | Demonstrated Codex gaps corrected; unknown metadata holds. Other atomic version families still need distinct positive active-reference policies. |
| 2 Shipped dependencies vs projects | Explicit install roots override VCS/locks; immediate project owner needs own VCS and lock; shipped/plugin/global fixtures, real-project and dedicated-cache controls | Corrected for reviewed layouts. Non-VCS/ancestor-only monorepos intentionally held. |
| 3 Renamed/missing-cwd sessions | Missing historical identity always retains normal mode thresholds, including composites/sidecars; hard 24 h careful/balanced floor | Safe fallback implemented. Positive gone inference remains unimplemented; no claim of proven deletion. |
| 4 Journal decision provenance | Mode/version, agent reason, planned/fresh policy; native/uninstall verifier evidence; strict checkpoint `journalError` | Corrected demonstrated omissions. Best-effort writes cannot guarantee durable history during persistent storage failure. |
| 5 Trash-dependent undo | Identity-aware unknown/replaced/missing/partial member reporting; staged copies preserved for review | No recovery promise after emptied Trash; identity checks are snapshots. |
| 6 Stable live-use refusals | Structured overlapping-path cooldown, original timestamp, corrupt history fail-closed; unavailable owner-app source holds; explicit uninstall blocks unknown source | Tested with mocks; no lock prevents an app starting after verification. |
| A Ignored worktree data | Engine/classification/decisions hold; no git action; direct `tool_action` refuses; fresh refuses old/forged/actionless plans and recognized descendants | Feature **disabled**. GitInspector is diagnostic, not proof of disposability. Preservation proofs cover notes, bare Git repo and unreachable writer/removal boundary. |
| B Fresh pin context | Live scope includes plan roots + home; new pins rediscovered; excluded/private/depth/mount gaps mark unknown in live traversal and full-scan reuse | Conservative correctness costs availability; per-item budget up to 120 s / 5 million entries. No cross-item unsafe pin cache. |
| C nvm alias chains | Bounded confined chains/LTS aliases, cycles/missing/unreadable/traversal/symlink uncertainty held | Ordinary alias/pin controls retained; unknown scope can hold entire pin-dependent families. |
| D Permanent rollback overwrite | Exclusive stage and rollback, no replacing fallback; conflict preserves both objects and records staging; transient checkpoint errors exposed | Original invariants preserved; native rename tests use disposable files/directories. |
| TUI risk warnings | Shared six-group warning set, mode/confirm/done damage and Trash limitations | Source/tests preserved; no physical-terminal claim. |
| TUI full path review | Scrollable confirmation and long-path coverage | Preserved. |
| TUI results/undo | Bytes moved rather than space reclaimed, U instructions, retry failed undo without repeating successes | Preserved. |

## Independent baseline verdict

Reviewed `02155a8` + `5f81022` against `21ce749`, including reports and original
proof sources at `4c39f2d`. In a disposable `git archive` of `5f81022`, ran:

`python3 -m unittest tests.test_runtime_supersession tests.test_baseline_review_probes tests.test_nov8_regressions -q`

55 tests passed (16.798 s). Coverage includes missing/malformed/unknown metadata,
positive supersession references, symlink process attribution, install exclusion
precedence, actual project/cache positive controls and session normal thresholds.
An additional deep nested install/project probe passed (no demonstrated bypass).

Verdict on the original baseline: **changes required**, not approved unchanged.
An arbitrary primary-reference descendant with matching runtime metadata was
accepted as a runtime root. Independent scan-only fake-home reproduction failed
preservation: the older install became balanced-eligible. The exploratory module
ran 46 tests (inherited helper tests included), with exactly this one failure.
`191ec58` restricts the reference to the install root or its recognized
`payload/codex-primary-runtime` root, and adds a focused regression. Original
commits remain preserved. Later unknown layouts hold rather than infer reuse.

The missing-cwd fallback satisfies the conservative safety objective but not the
requested positive repository-identity gone optimization. Historical root-commit
provenance and complete history are absent; no positive gone result is claimed.

## Blocking independent review findings supplied during integration

A review proof `1fe232cee97548108fd6384c68cb1f88febdcdd7` established permissive
ignored `node_modules` notes (known content-classification residual), a new nested
bare-repository variant lacking `.git`, and the previously acknowledged race
reproduced with a deterministic writer after final inspection. All P1. Disabling
worktree cleanup blocks their execution instead of extending inspection/staging
heuristics. Useful standalone GitInspector tests remain; formerly successful
removal controls now explicitly require disabled/refused/preserved behavior.
`tests/test_review_68aff51_residuals.py` adapts the proof's unsafe-selection setup
into safe holds, adds old/actionless and metadata-stripped descendant plans, and
asserts the removal command boundary is unreachable while fixture bytes survive.

D/journal proofs `10aa59e` + `8dcf712` and B+C proof `a8c46fd` required five changes:

1. Protected/private/depth/mount discovery gaps mark pins unknown in live and
   reused full walks. Protected project's new pin and depth-129 proofs retained.
2. Uninstall creation and fresh verification require `running_available`; both
   routes tested, plus a successful available-inventory control.
3. Staging descendant enumeration is directory-only; regular document identity
   and staged-ancestor guards remain. Positive document-version test passes.
4. Native/uninstall verifiers return structured evidence; success records fresh
   verifier-specific policy alongside plan policy, with null age threshold when
   inapplicable. No fabricated age rule.
5. Strict checkpoints mark `journalError` before rethrow, even if the next append
   succeeds; actual mutation/rollback outcome is retained.

Adapted proofs are normal tests (`test_independent_d.py`, `test_independent_bc.py`).
The protected-scope test now expects no new plan and separately constructs an
old plan from a previously unprotected scope; its fresh/apply preservation
assertion remains. Reviewer reports for earlier heads remain **changes required**;
this implementer's fixes are not independent approval.

## Validation and confinement

All mutation fixtures are disposable fake homes, repositories/local bare remotes,
state folders and Trash. No real-home scan, cleanup, repair, restore or real Trash
operation was invoked. No broad host inventory was used as validation. The
focused safety fixtures mock process/open-file/app/native inventories and remove
system app/agent roots. Git fixture hooks/signing and global/system config are
isolated; remotes are local. The full suite also includes nonmutating command
policy tests using real-home path strings, with execution mocked.

Inspected `native/SojiNative.swift`, `tests/test_native_walk.py`,
`tests/test_index_store.py` NativeRecovery, and walker helper selection before
compiling/running. Native operations exercised are fixture `walk`, `metadata`,
`event-id`, missing-file `versions`, and invalid-token `remove-version`; no
native `apps` or `trash` invocation. Build artifacts/module cache stay in
`/private/tmp/soji-native-integration-20261109`; no binary committed or installed.

Actual build command (exit 0):

```
mkdir -p /private/tmp/soji-native-integration-20261109/module-cache
swiftc -module-cache-path /private/tmp/soji-native-integration-20261109/module-cache native/SojiNative.swift -o /private/tmp/soji-native-integration-20261109/soji-native
```

Actual native-focused command: 10 tests, OK, zero skips (0.935 s):

```
SOJI_NATIVE_WALK_HELPER=/private/tmp/soji-native-integration-20261109/soji-native SOJI_TEST_NATIVE=/private/tmp/soji-native-integration-20261109/soji-native python3 -m unittest tests.test_native_walk tests.test_index_store.NativeRecovery -q
```

Focused final commands:

- `python3 -m unittest tests.test_independent_d tests.test_independent_bc tests.test_journal_refusal_safety tests.test_corpus tests.test_version_policy_context -q`: 60 tests, OK (19.888 s).
- `python3 -m unittest tests.test_independent_d tests.test_independent_bc tests.test_review_68aff51_residuals tests.test_worktree_ignored tests.test_review_worktree_gaps -q`: 47 tests, OK (21.033 s).
- `SOJI_UPDATE_CORPUS=1 python3 -m unittest tests.test_corpus -q`: 5 tests, OK (1.288 s), reviewed changes above.
- `git diff --check`: exit 0.
- `git diff --exit-code 21ce749 -- soji-repair.sh soji-restore.sh`: exit 0; scripts neither executed nor modified.

Full final results are recorded below. Earlier provisional runs before
review steering: plain suite 421 tests OK, 10 skips; native-enabled suite 422 OK,
zero skips. These are historical results, not validation of the final fixes.
Intermediate proof/adaptation runs exposed expected changed goldens, old controls
expecting removal, missing explicit mock inventory availability, malformed
hand-built plan digests, and a mechanical indentation error; corrected before
final validation. No failing golden was accepted without inspecting its changes.

## Remaining decision

Do not use these results to authorize real cleanup in any mode. Main and the
installed app remain unchanged. Cross-review of the exact integrated head comes
next, then any native mutation validation in a disposable account/VM with no
valuable shared paths, then read-only plan review. A real cleanup proposal would
require separate explicit authorization and independently verified recovery.
Unknown holds require investigation or a future explicit usable dependency-scope
policy; no automatic bypass/repair is proposed. Other atomic-family active refs,
positive project gone inference, filesystem/process races outside the disabled
worktree feature, persistent journal failure and real TCC/terminal behavior remain
limitations. The original incident journal is historical evidence, not a backup
or proof these additional fixture bugs caused the incident.


The original journal was re-read without modification: JSON list, 2,160 entries,
SHA-256 `581cb802b0f4085eb3edb0db561270a58835dc5f01d31861817741ca08b497aa`,
matching the handoff. Main's untracked status was copied read-only to
`SAFETY_STATUS_MAIN_HANDOFF_2026-11-09.md`; it is preserved historical context,
not a claim its earlier "in progress" or "open on main" rows describe this branch.

The first post-correction full runs each ran 437 tests with one failure in
`test_agent_mode.AgentModeTests.test_guards_on_proposals`: the legacy control
expected AI to bypass the newly unknown pin scope. `8d8e6cb` requires explicit
`Project pin discovery incomplete` rejection and one accepted app-cache item.
The focused rerun passed (1 test, 1.977 s). No engine guard was weakened.


## Final validation on code/test head `8d8e6cb`

Exact commands (output redirected to disposable `/private/tmp` logs, then copied
verbatim to `docs/validation/integration-full-{python,native}.txt`):

```
python3 -m unittest discover -s tests -q > /private/tmp/soji-integration-full-python-final.txt 2>&1
SOJI_NATIVE_WALK_HELPER=/private/tmp/soji-native-integration-20261109/soji-native SOJI_TEST_NATIVE=/private/tmp/soji-native-integration-20261109/soji-native python3 -m unittest discover -s tests -q > /private/tmp/soji-integration-full-native-final.txt 2>&1
```

- Plain suite: **437 tests, OK, 10 skipped**, 103.803 s. Skips are eight
  native-walk tests (no bundled helper) and two NativeRecovery tests without the
  opt-in `SOJI_TEST_NATIVE` environment variable.
- Native-enabled suite: **437 tests, OK, zero skipped**, 108.656 s.
- `git diff --check`: exit 0; scripts unchanged against `21ce749` (exit 0).
- `python3 -m soji_cli --help | rg 'worktree|method'` and
  `python3 -m soji_cli clean --help | rg 'worktree|execute'`: exit 0; disabled
  feature appears in help. These help-only commands perform no scan.

Final code/test tree was clean before the targeted documentation commit; only
NEXT_STEPS, the audit, this status, copied main handoff and validation logs were
pending. The final integration head is reported in the handback after committing
these documentation files. No physical-terminal or installed-binary validation.


## Exact-head cross-review corrections — 2026-11-09

Reviews of `82da248` required two P2 execution corrections and three P1
classification corrections. Implemented locally in `abdfc1c` and `fc7d5ee`:
finite entry/member refusal timestamps excluding booleans; structured running-app
uninstall cooldown; complete explicit-install ancestry; generic active-reference
uncertainty holds; non-overridable normal session minima and intact compound
membership under agent judgments. The proven Ruby uncertainty and judgment
bypasses are corrected claims pending fresh review, not deferred limitations.

See [five-finding follow-up](INTEGRATED_REVIEW_FOLLOWUP_2026-11-09.md) for proof provenance, exact
code/test SHA, before/after validation and remaining limitations. The earlier
437-test run does not validate these new changes. Worktree removal remains
disabled, main and installed binary unchanged, and final approval waits for a
fresh independent review. No real cleanup is authorized.

Final follow-up validation on `fc7d5ee`: **458 tests OK, zero skips** with the
disposable native helper (133.406 s); broader targeted run **141 OK**.
Exact commands/logs are in the five-finding follow-up. Independent approval is
still pending; main and installed binary remain unchanged.
