# Final generic marker symlink correction — 2026-11-09

Branch: `integration/safety-sol-20261109`, prepared checkout
`/Users/pierrelouis/.t3/worktrees/soji/t3-e54ebc38`.
Code/test commit: `e8a7237c2ea079834eebd6328e6a18b011d34d3b`.
Previous docs/code heads: `8a5418d` / `fc7d5ee`.

The final independent review still required changes for one residual P1.
The other four earlier blockers passed that review, including its independent
458-test native-enabled run and 95-test targeted run; those earlier numbers
are not validation of this correction. Original review preserved at
[final independent report](REVIEW_FINAL_MARKER_SYMLINK_2026-11-09.md).
Proof provenance: `d3f9ee018d02e8b828a21dc66556082510a42c69`,
`review/test_final_marker_symlink.py`.

## Residual and narrow correction

A generic marker symlink resolving somewhere inside a version family was
considered inactive unless it pointed inside the candidate. That was insufficient:
`.rbenv/version` linked to `.rbenv/versions/selection`, readable text `3.1.0`,
made the active Ruby 3.1.0 eligible, fresh-verifiable and movable to fixture Trash.

The shared handler now requires a recognized version identity before a linked
reference can establish inactivity. The target's first family-relative unit must:

- Match the same catalog rule as the candidate, with `keepVersionPointedToBy`.
- Have a version-like identity and matching product prefix.
- Be a real unit of the same filesystem type as the candidate, not a symlink.
- Be either a directory unit, an executable regular-file unit, or an executable
  regular-file descendant inside that directory unit. Arbitrary descendant
  directories cannot stand in for a runtime root.

In-family text metadata targets and unsupported linked layouts are held as
unknown, rather than parsed speculatively or treated as optional absence. This
chooses the conservative unsupported-layout option in the review request.
A merely family-relative path, or a broad catalog pattern alone, is insufficient.
Valid recognized different-version roots/executables and regular readable
inactive markers retain positive controls. The bounded regular-text parser,
unknown-marker holds and truly absent optional-marker policy are preserved.
No nvm alias or Codex runtime policy was replaced by this generic handler.

The original proof is copied into `tests/test_final_marker_symlink.py` with its
preservation assertion unchanged. A second test first creates a valid historical
plan with an inactive regular marker, changes it to the problematic text symlink,
then verifies fresh and actual fixture apply both refuse and preserve the runtime.

Seven-consumer controls now use actual catalog paths (rather than substituted
unrecognized family paths): Ruby, Swift toolchains, Claude standalone, Claude
desktop SDK, Cursor agent, Copilot CLI and Codex standalone releases. Each tests
in-family text links, unreadable text, oversized text, unrecognized directory,
unrecognized product directory and version-named non-executable text; all hold.
Each retains valid recognized different-root, executable-descendant and regular
inactive text positives. A standalone executable-file version unit has its own
positive control. Existing optional-absence, invalid UTF-8, malformed, dangling,
outside-family and looping-link controls remain.

The helper-level relative-symlink test now uses a real catalog Ruby path and an
executable fixture, with canonical `/private/var` paths consistent with Scanner.
It no longer assumes an arbitrary directory below a synthetic family is a valid
executable reference. An intermediate `/var` vs `/private/var` fixture mismatch
correctly produced an unknown hold; canonicalizing that test did not weaken the
production identity check.

## Before/after validation

Archived `8a5418d` into disposable
`/private/tmp/soji-marker-before-ldd7j1zq` using `git archive` (no new worktree).
Copied the original proof unchanged and ran:

```
python3 -m unittest tests.test_final_marker_symlink -q
```

**1 test, 1 preservation failure**, zero skips, 0.767 s. Its scan, fresh and
actual fake-Trash move preceded the final safe-expectation failure. No production
guard was mocked. Verbatim output: `validation/marker-symlink-before.txt`.

Same original proof on the correction initially passed: 1 test, zero skips,
0.528 s. Expanded focused command:

```
python3 -m unittest tests.test_final_marker_symlink tests.test_classification_safety_followup tests.test_smart_rules -q > /private/tmp/soji-marker-followup.txt 2>&1
```

**28 tests OK, zero skips**, 5.447 s. Verbatim output:
`validation/marker-symlink-followup.txt`.

Targeted/full results follow below, on the exact code/test SHA
above. No golden changes were made. All earlier five-finding, compound/session,
worktree-disable, scope, exclusive rollback, refusal-clock and recovery guards
remain in the full suite.

## Confinement and limits

Every new test path derives from a disposable fake home/state/Trash. Inventories
are isolated by `corpus.hermetic`; chmod/symlinks/executables affect fixtures
only. No fixture executable is launched. The original before-proof uses actual
fixture moves to an explicit disposable Trash, never native or real Trash.

Rechecked unchanged native source/test confinement and helper before the full
run. Existing helper:
`/private/tmp/soji-native-integration-20261109/soji-native`, SHA-256
`f047e247a537f277ec4c1ea56724b6782ab31de5c36dec8f2869dbbec36fe397`.
No compilation or install in this pass. Native tests exercise only disposable
walk/metadata/event-id, missing-path versions and invalid-token remove-version;
no native apps or Trash call. Module cache/helper remain under `/private/tmp`.

Only this prepared checkout and disposable tests were changed. Main, original
and other worktrees, installed binary and user repair/restore scripts remain
unchanged. No children, real-home scans/cleanup/Trash/repair/restore, installs,
network Git, push, PR or release. No physical-terminal or real-TCC claim.

Fresh targeted independent review must use `e8a7237` and its final docs head.
Unknown formats intentionally cost availability. Future marker layouts and all
atomic families are not universally certified; optional absence is not positive
supersession. Snapshot races outside the disabled worktree route, soft per-item
pin-discovery budgets, persistent journal failure and unimplemented positive
project-gone inference remain documented limitations. Worktree removal stays
disabled. No main update or real cleanup is authorized by these test results.


Broader targeted validation on `e8a7237`:

```
python3 -m unittest tests.test_final_marker_symlink tests.test_classification_safety_followup tests.test_review_execution_82da248 tests.test_integrated_cross_review tests.test_version_policy_context tests.test_runtime_supersession tests.test_compound_sessions tests.test_agent_mode tests.test_corpus -q > /private/tmp/soji-marker-targeted.txt 2>&1
```

**99 tests OK, zero skips**, 57.798 s. Verbatim log:
`validation/marker-symlink-targeted.txt`.


## Final full validation and handback

Exact full command on `e8a7237c2ea079834eebd6328e6a18b011d34d3b`:

```
SOJI_NATIVE_WALK_HELPER=/private/tmp/soji-native-integration-20261109/soji-native SOJI_TEST_NATIVE=/private/tmp/soji-native-integration-20261109/soji-native python3 -m unittest discover -s tests -q > /private/tmp/soji-marker-full-native.txt 2>&1
```

**462 tests OK, zero skips**, 135.225 s. Exit 0. Verbatim log:
`validation/marker-symlink-full-native.txt`.

`git diff --check`: exit 0. Script equality against `21ce749`: exit 0.
Native source and native tests remain unchanged against the inspected earlier
build; helper SHA-256 verified above. No binary is committed or installed.
Only documentation/review copies and validation logs remain after the code/test
commit and are committed separately. The final documentation head is supplied
in the handback. Fresh independent targeted review remains required; no main
merge, push or real cleanup is performed or proposed.
