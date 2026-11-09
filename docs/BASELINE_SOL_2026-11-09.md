# Sol baseline safety implementation, 2026-11-09

Branch: `fix/sol-baseline-20261109-4471`, based on `21ce749`.

## Scope and recovery

Read the safety orchestration prompt and status (status from main's docs).
Recovered tracked diffs by reading `t3-776629f0` (runtime) and `t3-8d8050cc`
(session), and copied the runtime's untracked test file. Applied only to this
prepared checkout. No original checkout was changed; no children, network Git,
installs, scans of the real home, or real cleanup occurred. User repair/restore
scripts were neither executed nor changed/staged. No push or PR.

## Runtime behavior

A primary directory's version, maximum version, newest timestamp, and missing
metadata never establish supersession. Only a primary symlink resolving into a
different install, with consistent readable bundle metadata at the install and
reference target, permits normal cleanup policy to consider a candidate.
Missing, malformed, conflicting, symlinked metadata or an unknown sibling blocks
the inventory. Running executable paths and candidate paths are realpath-resolved;
the existing open-file guard remains. Activity on a descendant holds the root.
Fresh rebuilds the reference/process/open-file checks; interior rows remain held.

Recovered code needed additional fixes: it still allowed a metadata-less
candidate under a valid reference and accepted arbitrary reference descendants.
Both cases now have regression tests, as does contradictory bundle metadata.

## Installed dependencies

Known global prefixes and plugin installations override local locks and VCS.
Added npm, pnpm, bun, yarn, Volta, fnm/asdf/mise installations and Deno bin;
these hold executable tool payloads rather than user development source.
Added Neovim lazy/site-pack/plugged/Mason, Vim plugged/pack, coc, Sublime and
JetBrains plugin trees; plugin managers commonly install Git clones and locks.
Dedicated download/application caches remain classified by their cache rules.

A dependency's immediate owning directory needs its own VCS marker and lockfile.
Parent ancestry never cancels an extension manifest. A nested dotfiles project
with its own Git root, package manifest and lockfile remains eligible outside
known install locations. Non-VCS projects and monorepo packages with only an
ancestor lock/root are intentionally held. Existing positive test fixtures were
upgraded to real disposable repositories, rather than weakening this guard.

## Session behavior — incomplete requirement

Missing cwd never establishes deletion. Existing activity records carry cwd/time,
not the historical root commit or a guarantee that all project history was
observed. A surviving parent Git repository cannot supply a missing child's
identity. The recovered draft attempted exactly that inference and walked loose
Git objects without a bound; that part was not retained.

The safe fallback now always preserves normal thresholds for missing projects,
including composites and orphan sidecars. The 24-hour careful/balanced floor is
unchanged; aggressive retains its normal policy. Registered-worktree and cwd
successor checks remain diagnostic evidence, not positive deletion proof.

**Still open:** root-commit provenance and a complete historical inventory must
be represented before the provably-gone optimization can safely return true.
No positive gone case is claimed or fabricated. The former "truly gone" fixture
only created an absent directory; it did not prove deletion and now tests
uncertainty even with a surviving Git parent. This branch fixes the demonstrated
unsafe downgrade but does not fully satisfy the requested identity-based positive
optimization. It requires further implementation/review before that requirement
can be marked complete.

## Other atomic version families reviewed

`keepNewest` is still a retention heuristic, not identification of in-use
versions, in fnm/Volta/pyenv/JVM/fvm/ghcup/asdf-mise/browser families. Several
have no active-version reference; others (nvm/rbenv/Swift/Claude/Cursor/Copilot/
Codex standalone) have separate marker rules. This is a residual safety concern,
not evidence those versions are unused. Their reference formats differ, so no
blanket Codex-specific policy was applied. The separate pins/alias task is not
integrated here. Other four P1 gates in the status document remain out of scope.

## Corpus review

Golden updated intentionally using `SOJI_UPDATE_CORPUS=1 python3 -m unittest
 tests.test_corpus` after inspecting the diff. Two existing runtime rows now
remain held; the older metadata-less install loses balanced/aggressive selection.
Five new global/plugin fixtures yield unselected rows. Five positive project
fixtures now own real repositories, adding five zero-byte private `.git` rows.
Dirty/clean project fixtures gained root lockfiles. Existing real-project
selections and dedicated-cache selections remain covered. No new selection was
accepted to mask a guard failure. Session corpus keeps renamed-project normal
threshold coverage; absent historical identity is covered in focused tests.

## Evidence and limitations

See `docs/validation/` for baseline and final outputs. Baseline runs load source
from `21ce749` into a disposable archive (no additional worktree), with the new
regression tests copied into it. All external inventories in these cases are
mocked by `corpus.hermetic`; Git fixtures disable hooks and use no network.
Native helper tests remain skipped as documented in the safety status. No live
macOS cleanup, installed-app repair, physical-terminal validation or independent
review is claimed. Passing Python tests does not clear the other safety gates.

Final commands/results:

- `python3 -m unittest tests.test_runtime_supersession tests.test_baseline_review_probes tests.test_nov8_regressions -q`: 55 tests, OK (17.738s).
- `python3 -m unittest tests.test_corpus -q`: 5 tests, OK (0.929s).
- `git diff --check`: exit 0, no output.
- Same final 38 reviewer/runtime probes on `21ce749`: 23 failures; see
  `validation/final-probes-on-21ce749.txt`. Final focused run includes these
  probes plus the recovered November 8 tests. Baseline failures include some
  deliberately changed positive-reference expectations, so 23 is not a count
  of distinct defects. Each p1a–p1d, p2a/b/c/g and p3a/b failed individually.

Full-suite command: `python3 -m unittest discover -s tests -q`

```text
----------------------------------------------------------------------
Ran 325 tests in 48.096s

OK (skipped=10)
```

Skips: eight native-walk tests (helper uncompiled) and two NativeRecovery tests
(`SOJI_TEST_NATIVE` absent). No native build/install was attempted.

New findings, separate from reviewer defects: recovered runtime draft allowed
missing candidate metadata even with a valid primary link, conflicting metadata
was not compared, and a reference into an arbitrary descendant could be mistaken
for a runtime reference. Corrected with explicit regression cases. Recovered
session identity inference from a surviving parent was unsupported; removed.
No claim these additional findings caused the incident.

Implementation commit: `02155a8` (`fix(safety): require positive install evidence`).
Documentation/evidence is committed separately immediately after it.
