# Integrated cross-review corrections — 2026-11-09

Branch: `integration/safety-sol-20261109` in the existing prepared checkout
`/Users/pierrelouis/.t3/worktrees/soji/t3-e54ebc38`.
Previous documentation head: `82da2481f6749f82a91ae8a8fb8ce3c02d89ad03`.
Current code/test head: `fc7d5eea93b930509f04694dc1e7bf945ecc4660`.
This follow-up supersedes earlier approval/status claims about the five findings
below. The earlier 437-test result does **not** validate these changes.

## Review findings and corrections

Both exact-head reviews required changes, not approval:

- Execution proof/report `2c84fb4`, preserved as
  [execution review](REVIEW_EXECUTION_82da248_2026-11-09.md).
- Classification proof/report `ecb4ecedc6f080f2e30e4a14b054e0f041c95678`, preserved as
  [classification review](INTEGRATED_CROSS_REVIEW_82da248.md).

| Finding | Correction and regression | State |
|---|---|---|
| P2 nonfinite refusal clocks bypass history | `abdfc1c`: strict JSON rejects NaN/Infinity constants; every explicit entry/member `at` and `refusalAt` must be finite numeric, excluding bool. JSON exponent overflow is checked after decoding too. Invalid history raises shared `SafetyRefusal(history-unknown)` before mutation. | Implemented, awaiting fresh review |
| P2 running uninstall refusal lacks cooldown | `abdfc1c`: shared exception moved to `safety.py`, re-exported through cleanup for compatibility; both running checks use structured active-use refusal. Existing inventory-availability requirement remains. Immediate retry/descendant overlap preserve the original clock; expired cooldown with a newly created valid plan remains usable. | Implemented, awaiting fresh review |
| P1 installed dependency exclusion stops after 12 ancestors | `fc7d5ee`: all lexical ancestors below fake/user home are considered; own VCS and lock never erase a distant explicit installation root. Partial-root scan and forged historical-plan fresh/apply test preserve the shipped payload even with cached marker assumptions. | Implemented, awaiting fresh review |
| P1 generic active marker uncertainty permits current Ruby removal | `fc7d5ee`: genuinely absent optional leaf is distinct from unreadable, malformed/empty, oversized, invalid UTF-8, dangling/looping or out-of-family symlink references. Unknown returns a family hold through the shared handler for all seven generic catalog consumers. Supported text is a bounded single numeric version token; unsupported wrappers/layouts stay held. | Implemented, awaiting fresh review |
| P1 agent judgment bypasses normal uncertain-session ages | `fc7d5ee`: catalog establishes separate per-mode minimum hours, checked by `Finding.decide` independently of agent levels. No proven-gone evidence means normal minima remain. AI retains managed catalog session units and their compound members instead of rebuilding them as transcript-only nodes. Fresh reconstructs these guards before replaying judgments. | Implemented, awaiting fresh review |

Generic consumers exercised: Ruby, Swift toolchains, Claude standalone,
Claude desktop SDK, Cursor agent, Copilot CLI and Codex standalone releases.
Existing nvm bounded aliases and Codex runtime supersession remain separate
handlers with their existing regressions. For each generic consumer the new
controls check unreadable/invalid UTF-8/oversized/malformed/empty references,
dangling/outside/looping links, readable active/inactive references, and optional
absence. Real Ruby scan and historical-plan fresh/apply preserve the fixture
runtime when its previously readable global marker becomes unreadable.

Session tests cover transcript, orphan sidecar and compound session at the
30-hour boundary, all relevant per-mode normal minima, replayed judgment input,
plan exclusion and forged historical-plan fresh/apply refusal, and preservation
of every compound member. An older 240-hour compound session still passes
judgment, plan, fresh and actual fixture Trash apply. Existing 24-hour floor,
compound membership changes, cooldown expiry, finite expired history and
real-project/dedicated-cache controls remain in the suite.

Normal session minima are currently retained for every catalog session without
positive gone evidence, including ones without parsed cwd. Positive gone
inference remains unimplemented. Agent thresholds can be stricter; they cannot
make these rows younger than normal policy. Catalog membership is rebuilt live
and never trusted from a historical plan to authorize removal.

## Independent before/after evidence

Exported `82da248` with `git archive` to disposable
`/private/tmp/soji-five-before-oogo59az` (not another worktree). Copied the two
original proof modules without adapting their assertions. Ran there:

```
python3 -m unittest tests.test_review_execution_82da248 tests.test_integrated_cross_review -q
```

**12 tests, 6 assertion failures**, 5.587 s, no errors/skips. Two failed timestamp
subtests, one uninstall retry, and three classification failures reproduce all
five findings. Mutations stay in the original proof fixtures with explicit fake
homes/state/Trash, mocked inventories and local-only isolated Git. Log:
`validation/five-review-before.txt`.

Copied meaningful proofs into normal tests. The sidecar proof now expects no
careful plan at 30 hours rather than expecting an unsafe plan followed by a
membership refusal; its content-preservation assertion is retained. Added a
separate historical-plan rejection test, not an expectation weakened to allow
removal. Execution proof also retains successful compound undo retry behavior.

Expanded timestamp regressions include NaN, +Infinity, -Infinity, true/false,
null, string, and JSON `1e999` overflow for top-level/member clock fields.
Finite integer/float expired clocks remain usable for both entry and member
records. Uninstall expiry creates a new plan after time advances; the one-hour
plan-expiry protection was preserved rather than bypassed for the test.

Golden review: only three explanatory decision strings changed in two existing
session rows (`-code-old-name/renamed.jsonl` careful/balanced and
`-code-py-agent/session.jsonl` careful). All existing selected booleans, byte
counts, holds, rows and actions are unchanged. These strings were edited only
after inspecting the failed corpus diff; no regeneration was used.

## Actual validation

```
python3 -m unittest tests.test_classification_safety_followup tests.test_integrated_cross_review tests.test_review_execution_82da248 tests.test_smart_rules tests.test_compound_sessions tests.test_corpus -q
```

**57 tests, OK**, 18.913 s, zero skips. Log:
`validation/five-review-followup.txt`.

The original 12 review tests first passed as 16 expanded proof tests (11.854 s)
before the additional generic/session/partial-root controls. An intermediate
new-test import-path error and partial-root test assuming a held row appears in
the frontier were corrected: the latter now classifies the real measured node
and explicitly checks its containing installation root. An initial expiry test
correctly hit the plan-expiry guard; it now creates a fresh plan. These were test
setup corrections, not relaxed filesystem guards.

Native/helper confinement was re-inspected before the full suite: native source
and `test_native_walk.py` / NativeRecovery code are unchanged from the earlier
inspected build. The existing helper is executable, SHA-256:
`f047e247a537f277ec4c1ea56724b6782ab31de5c36dec8f2869dbbec36fe397`.
No rebuild or install was performed in this follow-up. Test operations are
fixture-only walk/metadata/event-id, missing-path versions and invalid-token
remove-version. Native apps and trash are not used as validation.

Broader targeted and full native results are appended below. Their
logs are copied verbatim; final code/test SHA is listed above. `git diff --check`
and the recovery-script equality check run again at handback.

## Remaining limits and decision

Worktree cleanup remains unconditionally disabled; none of these fixes restores
Git removal or claims ignored content/races safe. The original six requirements,
A–D and TUI provenance remain in the integrated status. Full-home unknown pin
scope still holds affected families; its per-item 120 s / 5 million entry walk
has soft loop budgets, not a hard wall-clock/peak-memory guarantee. No unsafe
cache or privacy bypass was introduced to regain availability.

The proven generic-marker uncertainty defect is now addressed, not deferred as
harmless. This does not certify active-reference semantics of every atomic
version family, optional-absence policy, future layouts or concurrent marker
changes after verification. Unknown generic formats are intentionally held.
Positive project gone inference is still absent; normal thresholds are retained.
Process/filesystem verification remains snapshot-based outside the disabled
worktree route. Persistent journal failure cannot guarantee durable records.

Only this prepared checkout and disposable test directories were written.
Original/main/other agent worktrees and installed binary are unchanged. No
real-home scan, real cleanup/Trash/repair/restore, installs, network Git, push,
PR, release or child agents. User repair/restore scripts were neither modified
nor executed. No physical-terminal, installed-binary or real-TCC validation.
Fresh independent review of the final code/test head remains required before
any main integration. No real cleanup is proposed or authorized by this report.


Broader targeted command on `fc7d5ee`:

```
python3 -m unittest tests.test_review_execution_82da248 tests.test_integrated_cross_review tests.test_classification_safety_followup tests.test_journal_refusal_safety tests.test_uninstall_identity tests.test_version_policy_context tests.test_runtime_supersession tests.test_baseline_review_probes tests.test_compound_sessions tests.test_agent_mode tests.test_corpus -q > /private/tmp/soji-five-targeted.txt 2>&1
```

**141 tests, OK, zero skips**, 67.158 s. Verbatim log:
`validation/five-review-targeted.txt`.


## Final full validation and checkout

Exact command on `fc7d5eea93b930509f04694dc1e7bf945ecc4660`:

```
SOJI_NATIVE_WALK_HELPER=/private/tmp/soji-native-integration-20261109/soji-native SOJI_TEST_NATIVE=/private/tmp/soji-native-integration-20261109/soji-native python3 -m unittest discover -s tests -q > /private/tmp/soji-five-full-native.txt 2>&1
```

**458 tests, OK, zero skips**, 133.406 s. Exit 0; verbatim log:
`validation/five-review-full-native.txt`. This validates the five corrections,
including all previous native walk/recovery and disabled-worktree regressions.
It does not grant independent approval or certify installed software.

Final `git diff --check`: exit 0. Final
`git diff --exit-code 21ce749 -- soji-repair.sh soji-restore.sh`: exit 0.
`git diff --exit-code 82da248 -- native/SojiNative.swift`: exit 0.
No new binary was compiled or installed in this follow-up.

Code/test commits: `abdfc1c` (execution) then `fc7d5ee` (classification).
Only documentation and verbatim proof/validation logs remained dirty after those
commits; they are committed separately for handback. The final documentation
head is supplied with the final reply; code/test SHA remains the exact full-suite
head above. Main has not been merged or updated. Fresh independent review must
use this code/test head, not the superseded `82da248` verdict or 437-test run.
