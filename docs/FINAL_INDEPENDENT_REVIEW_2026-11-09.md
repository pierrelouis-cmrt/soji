# Independent residual marker review

Decision: **APPROVE**. No blocking P1/P2 found in this targeted residual review.

Exact reviewed docs target: `cb8865c73b1b219518b8aecbebbb25c4768b7e55`.
Exact implementation/test target: `e8a7237c2ea079834eebd6328e6a18b011d34d3b`.
Those trees are identical for `soji_cli`, `tests`, and `native`.
Prepared isolated checkout: `/Users/pierrelouis/.t3/worktrees/soji/t3-af2557a1`;
unique review branch: `review/residual-marker-af2557a1`.

Read `docs/MARKER_SYMLINK_FOLLOWUP_2026-11-09.md`, previous
`/private/tmp/soji-review-52967-final.md`, and original proof at
`d3f9ee018d02e8b828a21dc66556082510a42c69:review/test_final_marker_symlink.py`.
Reviewed incremental diff from `8a5418d` / `fc7d5ee`, not a fresh review of all
previously approved work. Only production change is 31 added/4 removed lines
in `soji_cli/specialized.py`.

## Findings and boundaries

The previous P1 is fixed: a resolved path somewhere in the family no longer
establishes inactivity. Recognition requires the same catalog rule, a version
identity with matching product prefix, matching filesystem unit type, and a real
directory root or executable file. A descendant must be an executable regular
file; arbitrary nested text/directories do not qualify. Unsupported layouts hold.

The unchanged original Ruby proof now passes. The supplied second proof checks
a previously valid inactive-marker plan against the changed marker at fresh and
actual fixture apply: refusal and preservation pass. No production guard mocked.

Seven-consumer supplied controls pass for in-family text, unreadable/oversized
text, unknown directories/products, version-named text, absent optional markers,
malformed/invalid UTF-8 metadata, outside/dangling/looping links, recognized roots,
executable descendants, and readable inactive text. Standalone executable-file
version units retain their positive control.

Three additional independent tests in `test_residual_marker_independent.py` pass:

- All seven catalog consumers reject two-hop chains to nested metadata or nested
  directories, wrong product prefixes, executable files when candidate units are
  directories, and wrong-family targets. Supported root/executable chains retain
  active/inactive positives.
- A cached catalog match still reads changed marker state; a candidate-only
  partial-root scan explicitly holds the unknown reference. Real fresh and apply
  refuse the historical full-scan plan, preserving the runtime.
- An incremental index scan with reused entries and no reported dirty subtrees
  rechecks a changed marker outside its indexed version-family root and holds it.

Initial independent fixture drafts expected an eligible plan with only one
version visible; that expectation failed due to conservative newest retention.
The tests now obtain the historical eligible plan from a full scan and assert
the partial scan's explicit unknown hold. No production/test-target code changed.
Snapshot decisions from an old scan are not claimed to refresh themselves.

Earlier invariants remain unchanged by production diff and pass targeted tests:
disabled worktree route, compound AI minima, finite history, unavailable inventory
holds, uninstall refusal cooldown, and exclusive staging/rollback. No request to
re-enable worktree removal or require positive project-gone inference. Normal
thresholds and conservative fallback remain intentional.

## Independent commands and results

1. Exported original proof unchanged via `git show` to
   `/private/tmp/soji-review-af2557a1-original/test_original_marker.py`.
   `PYTHONPATH="$PWD:$PWD/tests" python3 -m unittest discover -s /private/tmp/soji-review-af2557a1-original -p test_original_marker.py -v`
   **1 test OK, zero skips**, 0.414 s.
2. `PYTHONPATH="$PWD:$PWD/tests" python3 -m unittest discover -s review -p test_residual_marker_independent.py -v`
   **3 tests OK, zero skips**, 1.491 s.
3. `python3 -m unittest tests.test_final_marker_symlink tests.test_classification_safety_followup tests.test_smart_rules tests.test_review_execution_82da248 tests.test_integrated_cross_review tests.test_version_policy_context tests.test_runtime_supersession tests.test_compound_sessions tests.test_agent_mode tests.test_corpus tests.test_permanent_rollback tests.test_journal_refusal_safety tests.test_uninstall_identity tests.test_worktree_ignored -q`
   **189 tests OK, zero skips**, 85.634 s.
4. `SOJI_NATIVE_WALK_HELPER=/private/tmp/soji-native-integration-20261109/soji-native SOJI_TEST_NATIVE=/private/tmp/soji-native-integration-20261109/soji-native python3 -m unittest discover -s tests -q`
   **462 tests OK, zero skips**, 135.528 s, exit 0. Full run justified by changing
   the shared handler for seven consumers plus catalog/index interactions.
5. `git diff --check`, implementation/test/native equality between supplied heads,
   recovery-script equality against `21ce749`, native source/test equality against
   `fc7d5ee`: all exit 0.

Logs: `/private/tmp/soji-review-af2557a1-{original,independent,targeted,full-native}.log`.

## Confinement and limits

Inspected `FakeHome`, `corpus.hermetic`, native walk fixtures, NativeRecovery,
helper selection/dispatch, and targeted mutation fixtures before execution.
Supplied helper SHA256:
`f047e247a537f277ec4c1ea56724b6782ab31de5c36dec8f2869dbbec36fe397`.
Native tests use disposable walks/metadata/event-id, missing fixture version paths,
and invalid-token remove-version; no native apps/Trash. Inventories are mocked.
All test mutations use disposable homes/state/Trash/local fixture repositories.
Recovery scripts remain byte-identical and unexecuted.

No author/main/other-worktree modifications, children, network, install, release,
push, PR, reset/clean/stash, real-home scan/cleanup/Trash/repair/restore, or physical
terminal/real-TCC/installed-app claim. Only review proof/report files added here.
Git metadata access was needed to check out the exact target in this prepared
checkout. No universal certification of future marker layouts or snapshot races.
