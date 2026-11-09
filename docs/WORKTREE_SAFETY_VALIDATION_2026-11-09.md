# Worktree safety follow-up validation — 2026-11-09

Branch: `fix/worktree-data-safety-sol-20261109`, starting at `52bb0e5`.
Replacement implementation checkout: `/Users/pierrelouis/.t3/worktrees/soji/t3-d5fe2431`.

Recovered only the inspected tracked changes to `soji_cli/cleanup.py`,
`soji_cli/gitstate.py`, and `soji_cli/util.py` from `t3-3536dd77` by applying its
read-only Git diff here. That checkout had no untracked files. Original files
were not modified. The recovered patch was tightened (strict environment
sanitization, conservative cache shapes, malformed-output handling); its optional
cache expansion was removed. All existing tests from `52bb0e5` are preserved.
Reviewer tests were read from `f1e9315` and copied, adding only a fake HOME.
The four supplied probe scripts were read, not executed; their relevant cases
became assertions in `tests/test_worktree_ignored.py`, including scanner holds
in careful/balanced/aggressive and real guarded removal of disposable fixtures.

## Executed validation

- Before implementation, `python3 -m unittest tests.test_review_worktree_gaps -q`
  on `52bb0e5`: **7 tests, 5 failures, 2 passing controls**. The five unique-data
  deletion repros all failed exactly as the reviewer reported.
- Expanded tests against an exported `52bb0e5` package in a temporary directory:
  `python3 -m unittest tests.test_worktree_ignored tests.test_review_worktree_gaps -q`:
  **33 tests, 19 failures (including subtests), 3 errors**. Errors include missing
  new helpers and uncaught decoding failure; this was an intentional baseline
  comparison, not a passing validation.
- Final targeted command above on the implementation: **33 tests, OK**
  (24.358 seconds, no skips).
- `python3 -m unittest tests.test_corpus -q`: **5 tests, OK**, no golden updates.
- Initial full run: **317 tests, 1 failure, 10 skipped**. Environment sanitization
  removed the corpus fixture's Git discovery boundary, exposing the enclosing
  checkout. Fixed the hermetic harness to set its boundary explicitly after
  sanitization; did not alter production sanitization or golden expectations.
- Final `python3 -m unittest discover -s tests -q`: **318 tests, OK (skipped=10)**,
  73.775 seconds; 308 passed, 10 skipped. The additional test checks malformed,
  absent, and unreadable tracked-index entries.
- `git diff --check`: **clean**.
- `git diff 52bb0e5 -- soji-repair.sh soji-restore.sh`: **empty**.

All destructive tool tests used disposable repositories/local bare remotes and
fake homes. Scanner external inventories were mocked with the corpus harness;
tool-only tests disable context. No network Git, installs, push, release,
reset/clean/stash, real-user cleanup, real Trash operations, repair or restore occurred.

## Remaining limits

- Inspection and removal are not atomic. Concurrent writes or directory
  substitution during walking or between reinspection and removal remain races.
  Staging with `git worktree move` is deferred: it mutates metadata, requires
  journal/action/rollback support for a new path, does not support worktrees with
  submodules, and does not prevent writes through retained descriptors. It is
  not a simple complete fix.
- `node_modules` still assumes non-Git contents are regenerable when the directory
  itself is ignored. Arbitrary manually saved files inside it are not recognized
  as unique data. The other caches use conservative filename/structure checks,
  not provenance or content authentication.
- Bounded traversal intentionally holds large/slow/unreadable caches. Symlinks
  inside node_modules are not followed; external target survival is tested.
- Invalid UTF-8 filenames cannot be created on this macOS filesystem; the
  decoding regression injects invalid bytes at the inventory subprocess boundary
  and exercises the real `util.command` decoder and tool refusal.
- Eight native-walker tests skip because the native helper is not compiled; two
  native recovery tests skip because `SOJI_TEST_NATIVE` is absent. No native
  helper was built/installed. No installed binary or real home was validated.
- Independent review and integration with other safety branches are outstanding.
  This branch alone does not resolve the other safety findings in the status doc.
