# Independent final review — changes required

Reviewed integrated docs head `8a5418d2407095ad4f665bf96f46511779861db5`, identical implementation/tests/native to code/test head `fc7d5eea93b930509f04694dc1e7bf945ecc4660`. Inspected final diff from `82da248` and relevant interactions with original `21ce749`, follow-up, preserved reports, integrated status and orchestration prompt. Review branch: `review/final-five-52967d04` in prepared isolated worktree `t3-52967d04`. Implementation was not authored or changed by this reviewer.

## P1: text-marker symlink still permits current Ruby removal

Location: `soji_cli/specialized.py:610-616`. A symlink resolving inside the version family falls through as inactive unless its resolved path lies inside the candidate. Its target is never checked as text metadata or rejected as an unsupported layout. Thus the new uncertainty guard does not cover this symlink case.

Confined repro: three old Ruby installations, `.rbenv/version` initially a regular file containing `3.1.0\n`; scan correctly holds 3.1.0. Replace the marker with a symlink to `.rbenv/versions/selection`, a regular file with identical readable contents. The marker still reads `3.1.0\n`, yet scan selects 3.1.0, real fresh verification accepts its identity, and actual apply completes one move to explicit fixture Trash. No production guard mocked; inventories isolated by `hermetic`; every mutable path derives from TemporaryDirectory.

Proof committed as `d3f9ee018d02e8b828a21dc66556082510a42c69`, only `review/test_final_marker_symlink.py`. Command: `python3 -m unittest discover -s review -p test_final_marker_symlink.py -v`. Result: **1 test, 1 expected preservation failure**, zero skips; fresh/apply assertions preceding the failure passed. Log: `/private/tmp/soji-review-52967-symlink.txt`.

Minimal fix: distinguish supported version/executable symlink targets from text-marker targets; validate supported text targets with the same bounded parsing/readability rules, or conservatively hold unsupported targets. A target merely being somewhere inside the family cannot establish inactivity. Preserve valid links into another recognized version and regular readable inactive-marker positives. This is a residual of the generic-reference blocker, not a claim the last diff newly introduced the behavior. Existing seven-consumer tests cover links into version roots, dangling/outside/looping links, but omit links to text metadata.

## Five-blocker assessment

- Nonfinite clocks: corrected. Strict decoding rejects nonstandard JSON constants; entry/member `at` and `refusalAt` require finite numbers excluding bool/null/string/overflow. Invalid history becomes `history-unknown` before mutation. Finite integer/float expired entry/member positives pass.
- Positive-running uninstall cooldown: corrected. Shared structured refusal survives immediate retry and descendant overlap without renewing the original clock; new valid plan after finite expiry succeeds. Unavailable inventory still blocks; available empty inventory remains usable.
- Deep installed roots: corrected. Complete lexical ancestry overrides nested own VCS/lock, including partial-root classification and cached/historical-plan fresh/apply. Real project and dedicated-cache controls pass.
- Generic active references: **incomplete**, P1 above. Regular unreadable/malformed/oversized/invalid UTF-8 markers and dangling/outside/looping links now hold; optional absence and valid inactive positives remain usable. Unknown metadata is not generally interchangeable with optional absence.
- Agent session minima: corrected in reviewed paths. Live catalogs reconstruct non-overridable per-mode minima; AI preserves managed compound units/members; fresh rebuilds policy before judgment replay. Transcript/orphan/compound young cases hold; older compound plan/fresh/fixture apply succeeds. Missing cwd metadata is not treated as proven inactivity. Positive gone inference remains unimplemented and is not a blocking finding.

Disabled worktree cleanup, direct action refusal, exclusive staging/rollback, staged-copy guards, provenance and fresh pin scope remain intact by inspection and passing integrated regressions. No request to restore worktree cleanup or relax conservative holds.

## Independent commands and results

1. Original modules exported unchanged with `git show 2c84fb4:tests/test_review_execution_82da248.py` and `git show ecb4eced:review/test_integrated_cross_review.py` into `/private/tmp/soji-review-52967-original`:
   `PYTHONPATH="$PWD:$PWD/tests" python3 -m unittest discover -s /private/tmp/soji-review-52967-original -p 'test_original_*.py' -v`
   **12 tests, 11 pass, 1 failure, zero skips**, 3.403 s. The failure is the old sidecar expectation of one careful plan at 30 hours; current policy correctly emits zero. All original unsafe-boundary assertions pass. Log: `/private/tmp/soji-review-52967-original.txt`.
2. `python3 -m unittest tests.test_review_execution_82da248 tests.test_integrated_cross_review tests.test_classification_safety_followup tests.test_version_policy_context tests.test_runtime_supersession tests.test_compound_sessions tests.test_agent_mode tests.test_corpus -q`
   **95 tests OK, zero skips**, 53.802 s. Log: `/private/tmp/soji-review-52967-targeted.txt`.
3. `SOJI_NATIVE_WALK_HELPER=/private/tmp/soji-native-integration-20261109/soji-native SOJI_TEST_NATIVE=/private/tmp/soji-native-integration-20261109/soji-native python3 -m unittest discover -s tests -q`
   **458 tests OK, zero skips**, 127.695 s. Log: `/private/tmp/soji-review-52967-full-native.txt`. This discovers `tests`, not the new failing proof in `review`.
4. `git diff --check`; script equality against `21ce749`; native equality against `82da248`; implementation/test/native equality between `fc7d5ee` and `8a5418d`, and between target and proof-only review commit: all exit 0. Final checkout clean.

Full/targeted suite source is the exact target implementation/test tree. Final review commit adds only the separately run proof. Before native execution inspected NativeWalkParity, NativeRecovery, fixture inventory mocks, helper selection and native dispatch. Supplied helper SHA256 matches `f047e247a537f277ec4c1ea56724b6782ab31de5c36dec8f2869dbbec36fe397`. Native exercises only disposable walks/metadata/event-id, nonexistent fixture versions and invalid-token remove-version; no native apps/Trash. No build/install.

## Limits and confinement

No real-home scan/mutation, native apps/Trash, repair/restore scripts, network Git, push/PR/release, child agents, reset/clean/stash or other-worktree changes. Git checkout/commit metadata was written only as necessary for this isolated branch. Original scripts remain unchanged and unexecuted.

No physical-terminal, real-TCC or installed-app claim. Process/filesystem snapshots retain races outside disabled worktree cleanup; pin discovery has soft per-item budgets and conservative unknown holds; persistent journal failure cannot guarantee durable history. Tests do not certify every future marker layout or atomic family. Approval remains blocked on the demonstrated symlink case.
