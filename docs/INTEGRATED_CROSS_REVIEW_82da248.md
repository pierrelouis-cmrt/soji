Independent cross-review: **CHANGES REQUIRED**.

Tested source SHA: `82da2481f6749f82a91ae8a8fb8ce3c02d89ad03`, base
`21ce74904430bd8293036239343de635f72b0729`. Code/test tree equals
`8d8e6cb406070343a39d9b6e88626574573b1ba0` (verified by Git diff).
Review checkout: `/Users/pierrelouis/.t3/worktrees/soji/t3-173d05cf`;
unique branch `review/independent-integrated-82da248-173d`.
No implementation authored or changed. These are residual requirement failures,
not a claim that all were introduced between the base and integrated head.

P1 — Installed dependencies bypass exclusion beyond ancestor limit

`soji_cli/installs.py:87` truncates ancestry to 12 entries;
`:173` therefore returns no containing install and `:189` accepts the immediate
owner's VCS and lockfile. Fixture:
`~/.bun/install/global/node_modules/tool/vendor/a/b/c/d/e/f/g/h/i/j/k/pkg/`
contains a real isolated committed repository, lockfile and ignored
`node_modules/dep/index.js`. The nested dependency directory is selected at
aggressive, and Cleaner.fresh accepts its exact identity. The explicit installed
global root must override these markers at every depth. This is the same shipped
software loss objective as requirement 2; it is not merely an unproven future
layout. The existing deep-extension probe has no local VCS, so tightening project
ownership hides rather than closes this case.

Proof: `DeepInstall.test_deep_installed_local_vcs_and_lock_cannot_override_install`.
Minimal fix: evaluate explicit install ancestry without this depth cutoff (or
return uncertainty on exhaustion), including partial-root/fresh paths. Keep
marker/cache invalidation and real-project/dedicated-cache positive controls.

P1 — Unreadable active-version marker permits current Ruby removal

`soji_cli/specialized.py:603-606`: generic marker read failures are swallowed as
though no marker selected a version. Fixture installs Ruby 3.1.0/3.2.0/3.3.0,
aged 180/120/90 days; `.rbenv/version` contains `3.1.0`. With readable metadata,
3.1.0 is protected. chmod 000 produces a verified PermissionError, yet the full
scan selects 3.1.0, fresh accepts it, and actual apply completes one move into
**disposable fixture Trash**, removing its original runtime path. No host runtime
or real Trash involved. This is a demonstrated unsafe current-version removal
in another atomic family, not speculative future work. A warning or documenting
uncertainty does not satisfy the unknown-must-block safety requirement.

Proof: `CrossReview.test_unreadable_global_ruby_marker_must_hold_current`.
Minimal fix: return a family hold on unreadable/malformed/oversized/unsupported
active-reference metadata and unresolved links; distinguish genuinely absent
optional markers explicitly. Apply across generic marker consumers, not only nvm
and Codex runtimes. Retain readable active/inactive positive controls.

P1 — Agent judgment bypasses normal uncertain-session thresholds

`soji_cli/ai.py:393-399` replaces catalog thresholds;
`soji_cli/cleanup.py:415-418` replays that judgment after fresh classification.
A 30-hour Claude transcript has a missing historical cwd and explicitly
`sessionProjectMoved.gone=False`. Its initial balanced threshold is 48 h, and it
is unselected. An agent remove judgment with one-hour levels makes it selected
at balanced; fresh accepts the plan. The 24-hour floor at engine.py:162 protects
only younger sessions and does not preserve the normal 48 h / 168 h policy.
This contradicts the integrated status's assertion that unknown historical
identity always retains normal thresholds. No actual session removal was needed
for this scan-to-plan-to-fresh proof.

Proof: `CrossReview.test_unknown_session_identity_agent_must_keep_normal_threshold`.
Minimal fix: retain non-overridable per-mode catalog minima for unknown historical
identity, including replayed/cached judgments; combine those with agent thresholds
and the existing hard floor. Preserve compound membership during agent handling.

A separate 30-hour orphan sidecar becomes careful-eligible after judgment, but
fresh refuses its changed compound membership. That probe is a **passing
conservative refusal**, not another proven execution bypass. The 20-hour session
agent-floor control passes. Existing targeted tests cover young composites and
normal catalog levels without agent override; those successes do not disprove
the 30-hour transcript failure.

Reviewed corrections and conservative limits

- Read safety orchestration instructions, integrated status, audit, baseline
  report, earlier `a8c46fd` proof, baseline-to-head engine/catalog/install/
  specialized/fresh diffs and relevant fixtures. No child agents.
- B/C protected-project historical-plan preservation and depth-129 regression
  pass. Independent full-walk `from_nodes` depth/mount gaps and live mount gap
  probes pass. Mounts are simulated with stat/device arguments, never mounted.
  Additional external plan root receives a new pin after planning: fresh refuses.
  Symlink pin is followed live; full-walk reuse holds conservatively. Alias chains,
  cycles, traversal, symlink aliases, changing aliases and live rediscovery pass
  in the targeted existing suite. New plans and old-plan revalidation covered.
- Full-home private/protected/.git exclusions intentionally hold entire pin
  families. This costs availability, including ordinary project-containing homes;
  it is not a blocking defect and must not be bypassed to regain selections.
  The 120 s / 5 million entries policy budget is per item; a batch repeats the
  live dependency walk. These are soft loop budgets, not a hard wall-clock or
  peak-memory guarantee: one scandir materializes entries before the next check.
  No full-home performance benchmark or real-home scan was performed. A future
  explicit dependency-scope design must preserve unknown holds.
- Codex runtime positive supersession, arbitrary-descendant rejection, unknown
  metadata/inventory, atomic interior refusal, realpath process descendants,
  activity and fresh rechecks pass. Neither maximum version nor timestamps are
  accepted alone as positive supersession. Other untested atomic families are
  not universally certified; the Ruby failure above is sufficient to block.
- Global/editor exclusion and real project/cache positive controls pass for the
  existing reviewed layouts; the deeper local-VCS case above exposes a remaining
  limit. Catalog marker-dependent matches are not persisted as pure path matches;
  fresh clears mutable marker and match caches. Index tests passed, but this is
  not proof of all possible filesystem/event races.
- Baseline-to-head corpus: 55 -> 68 rows, 13 additions, zero removals. Existing
  selection changes: wDayCH loses balanced/aggressive; nvm v18 loses aggressive.
  No existing false->true selections. Reviewed added real fixture repositories,
  lockfiles, global/plugin trees, nvm alias chain and local-remote worktrees;
  no golden regeneration by this reviewer. Corpus passes. Unknown pin scope means
  some corpus alias/pin rows are held by incompleteness; focused pin tests retain
  independent positive/negative controls rather than relying on that golden.
- Help-only commands describe worktree removal as disabled, consistent with the
  final engine. Current docs correctly describe B/C conservative availability,
  but the normal-session guarantee is too broad and other-family uncertainty is
  demonstrably unsafe in the Ruby case. Historical audit sections are historical.
- Mutation/rollback/journal/undo/native/worktree execution are another reviewer's
  scope; no independent verdict on those here. Existing targeted compound-session
  tests use disposable Trash. Recovery scripts unchanged and never executed.

Commands and actual results on exact source head

```
python3 -m unittest tests.test_version_policy_context tests.test_independent_bc tests.test_runtime_supersession tests.test_baseline_review_probes tests.test_nov8_regressions tests.test_catalog_revalidation tests.test_compound_sessions tests.test_agent_mode tests.test_corpus -q
```
111 tests, OK, zero skips, 48.046 s.

```
SOJI_NATIVE_WALK_HELPER=/private/tmp/soji-native-integration-20261109/soji-native SOJI_TEST_NATIVE=/private/tmp/soji-native-integration-20261109/soji-native python3 -m unittest tests.test_native_walk tests.test_index_store -q
```
35 tests, OK, zero skips, 3.172 s. Inspected native dispatch, walk confinement,
NativeRecovery and index fixtures before execution. Uses supplied helper, no
build/install. Native operations: fake-root walk/metadata/event-id, nonexistent
fixture versions and invalid-token remove-version; no native apps or trash.
Helper SHA-256: `f047e247a537f277ec4c1ea56724b6782ab31de5c36dec8f2869dbbec36fe397`.
No claim of independently rebuilding or validating the installed binary.

```
python3 -m unittest discover -s review -p test_integrated_cross_review.py -v
```
Final proof run: 9 tests, 6 pass, 3 intentional safe-expectation failures,
zero errors/skips, 2.897 s. Captured output in
`review/integrated-cross-review-results.txt`. The earlier exploratory sidecar
expectation exposed a conservative fresh refusal; final probe asserts that
refusal. An intermediate indentation error was corrected before the final run.
Tests intentionally fail until the three findings are fixed; do not regenerate
expectations to hide them.

```
python3 -m soji_cli --help
python3 -m soji_cli clean --help
git diff --check
git diff --exit-code 21ce749 -- soji-repair.sh soji-restore.sh
git diff --exit-code 8d8e6cb 82da248 -- soji_cli tests
```
All exit 0. The full 437-test suite was not independently rerun; integrated-status
full-suite results belong to the implementer. No physical-terminal, real-TCC,
installed-binary, release, real-home scan or real-data cleanup claim.

Confinement: all new proof paths derive from TemporaryDirectory fake home, state,
and Trash. chmod only fake marker; cleanup restores that mode. Nested Git fixture
uses real local Git with global/system config isolated and hooks disabled, no
remote/network. Processes, open files, apps, native, system roots and tool
inventories are mocked via hermetic. Only the Ruby proof calls apply, with explicit
fake Trash; no native trash fallback. No original worktree/main modification,
reset/clean/stash, installs/releases, push or PR. Commit contains proof/report/log
only. This exact integrated source head does not meet the requested safety goal.
