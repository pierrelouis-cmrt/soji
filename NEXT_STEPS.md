# Sōji 0.3 handoff — 7 November 2026

This is the current implementation handoff. Read this before the older recap or individual thread handoffs. The user requested that we stop exhaustive tracing and prioritize a working version to conserve usage. No new investigation should be launched automatically from this checklist.

## Delivered and integrated

| Area | Current code | What works now |
| --- | --- | --- |
| Base modes | `soji_cli/levels.py`, `engine.py` | Careful/Balanced/Aggressive; translated age/risk/effective functions; cumulative judgments; minimum recency; separate managed catalog path. |
| Specialized rules | `specialized.py`, `engine.py` | Timestamp ranking, grouping, per-mode keep counts, literal active markers/pins, archive upload identities, per-mode file/project clocks. |
| Activity | `activity.py`, `catalogs.py`, `gitstate.py`, `apps.py` | Bounded metadata reads, local-date Codex scan window, T3 live/archive timestamps, Git default-branch precedence, tool config adapters, Codex writer-lock/process holds. |
| Index | `index.py`, `engine.py` | First complete daily snapshot; independent weekly full-check clock; event/volume/history recovery; hardlink allocated-byte shares and surviving-link refresh. |
| AI | `ai.py`, `mcp.py`, `cadence.py`, `index.py` | Partial/marker submission recovery, preset MCP extras, cancellation, failure patterns, 24-run default, migrated raw cache and ordinary/backlog reuse with stable identity guard. Cadence is a callable policy, not a daemon. |
| Cleanup | `cleanup.py`, `commands.py`, `nativeplans.py`, `routines.py`, `uninstall.py` | Expiring/revalidated plans, hint-scoped commands, recovered permanent-action gate, uncertain/partial failure reporting, automatic permit fix, stronger native/uninstall checks. |
| Native | `native/SojiNative.swift` | Rebuilt universal helper, richer filesystem metadata, explicit version failures, re-enumeration/retention/removal inside one coordinator write, stable version-unit selectors passed through plans. |

The shipped catalogs/presets remain the original recovered resources. Source reconstruction is standalone and does not invoke Sōji. Private source was never consulted. The original app remained read-only; cleanup tests used disposable fixtures. No live provider/model call was made.

## What was rushed or deliberately deferred

- **Integration breadth:** independent workers edited assigned modules, then the coordinator connected them. Fixture and native smoke coverage exists; there has not been a systematic final architecture/security review of the combined diff. The Git repository still has no initial commit; files are untracked. No branch switching, remote, push or PR was performed.
- **Early rules:** missing workspace emits `rule_early_reason`, but its original caller has not been fully traced. The port conservatively keeps normal eligibility guards. Device-build supersession and simulator-twin branches are incomplete; do not claim full specialized-rule parity.
- **Rule/AI precedence:** explicit judgments bypass default rule age maps; this is a reconstruction choice consistent with traced separate paths, not a proof for every original caller. Existing worktree/simulator judgment shortcuts also need a dedicated comparison corpus.
- **AI packing and accounting:** largest 200 pending rows is a port choice. Recovered `listedPerRun=40` refers to grouped listed findings and is not a proven universal cap. Dynamic prompt packing, run charging for manual/automatic/failure cases, process-verdict caches and full launch environment parity remain incomplete.
- **Negative cache:** one-day retry policy exists as a helper, but the current run does not persist omitted findings as negative judgments. Omission must not be treated as an explicit negative claim. New raw records use recovered size/expiry tolerances plus stable inode/path identity; legacy rows keep strict hash/seven-day reuse.
- **Scheduling:** cadence/backoff constants and policy are implemented/tested. No automatic analysis daemon, login item, notification pipeline or timer-driven retry orchestration is installed. CLI analysis is explicit.
- **Activity/session coverage:** grouped Claude transcript-plus-sidecar actions and `.jsonl.zst` session catalog coverage remain incomplete. Activity lookup defaults to descendants; conservative ancestor lookup is opt-in. External schemas may drift.
- **Index performance/row shape:** recomputation re-stats cached regular files to refresh hardlink shares, including paths outside dirty subtrees. This favors correctness over incremental speed. Original rolled-folder/package row selection, folder-cache invalidation, relaxed scheduling and complete dataless/exclusion parity are not implemented. Native metadata availability is not the same as exact freeable-byte accounting.
- **Native cleanup:** runtime busy filtering conservatively holds any `xcodebuild`/`simctl` process; argument-level filtering and settle/free-space accounting are deferred. Version removal code is coordinated, but no real document version was deleted. Simulator/runtime removals and official cleanup commands were not run on personal data.
- **Uninstall:** signing/team/app-group and shared receipt attribution are incomplete. Keep the existing narrow ownership scope until those are implemented.
- **Tests/tooling:** two opt-in native tests are separate from the default suite. A Python 3.15 unclosed-SQLite `ResourceWarning` appeared in fixtures; it did not fail tests and remains minor cleanup work. Full provider compatibility is untested. No differential run of both apps over an identical comprehensive corpus was performed.

## Next work, in order

### 1. Establish a stable baseline and cheap regression corpus

Files: `tests/`, `scripts/native_integration.py`, `research/`.

1. Read the validation section below and rerun only the checks affected by any new edit.
2. Review the current source and create an initial Git commit once accepted. Do not stage `dist/`, native binary, fixtures or personal state (ignored paths already exist).
3. Build a small synthetic comparison corpus with known timestamps, version families, missing/present workspaces, session locks and project activity. Export normalized rows from both apps: hint ID, allocated bytes, retained rank, mode, hold and action type. Record differences before changing more algorithms.

Done when the current release can be reproduced and a short list of observed differences replaces guesses. This is the best next step for measuring similarity; a percentage is not justified today.

### 2. Close the specialized-rule gaps that affect selection

Files: `specialized.py`, `levels.py`, `engine.py`; evidence: `research/rules-recovery.md`, `mode-recovery.md`.

Trace the caller consuming SmartRules' early Outcome, then implement missing-workspace/device-build/simulator behavior with fixtures. Verify rule/AI precedence using explicit judgments and both project/file clocks. Add boundary cases for early outcomes and retained archives. Keep local activity/identity guards during testing.

Done when each remaining early branch has either an evidenced implementation or an explicit unsupported result, with expected per-mode selections on the corpus.

### 3. Finish compound session catalogs and activity compatibility

Files: `catalogs.py`, `activity.py`, `cleanup.py`; evidence: `research/activity-recovery.md`.

Represent a Claude transcript and its associated sidecar folders as explicit member paths. Measure each once, preserve memory folders and revalidate every member before execution. Add bounded compressed-rollout metadata support if needed. Compare descendant versus ancestor project activity intentionally; do not silently change the recovered default.

Done when compound fixtures clean only the intended members, retain active sessions and report partial failures accurately.

### 4. Complete AI selection/scheduling only after the core corpus is stable

Files: `ai.py`, `cadence.py`, `index.py`, `__main__.py`; evidence: `research/ai-recovery.md`.

Replace the flat 200-row packing choice with evidenced grouping/budgets. Model explicit negative verdicts separately from omitted rows. Decide manual/automatic/failed run accounting, then wire cadence, persistent run state and retry backoff. Test with a fake agent first. Real provider runs should be a small, explicit opt-in validation step using a fixed corpus/model/settings.

Done when packing, ordinary/backlog/negative cache selection and accounting are deterministic in tests, and scheduling survives restarts without duplicate runs.

### 5. Improve indexing/accounting and native action confidence

Files: `index.py`, `engine.py`, `native/SojiNative.swift`, `nativeplans.py`.

Avoid whole-index regular-file re-stat by tracking affected hardlink identities, retaining the surviving-link regression. Add package/rolled-row and clone/purgeable/freeable comparison fixtures. Refine runtime argument filtering and post-command settle measurement. Validate real version/runtime operations only on intentionally disposable OS-managed assets.

Done when incremental work is bounded by dirty areas plus affected identities, and displayed byte estimates distinguish measured allocation from expected reclaimed space.

### 6. Broaden uninstall ownership last

Files: `apps.py`, `uninstall.py`, native helper.

Add code-signing/team/group ownership and shared receipt attribution, with shared-owner fixtures. Expand removal scope only after attribution is reproducible. System/privileged package removal remains outside the current implementation.

## Validation and reproduction

From the repository root, with Python 3.10+ and macOS 13+:

```sh
python3 -m unittest discover -s tests -q
SOJI_TEST_NATIVE="$PWD/soji_cli/native-bin/soji-native" \
  python3 -m unittest discover -s tests -p 'test_index_recovery.py' -q
python3 scripts/native_integration.py
python3 build_release.py
python3 dist/soji.pyz --version
```

`build_release.py` requires Swift/Xcode Command Line Tools and builds ARM64 + x86-64. The integration script uses temporary fixtures, actual local FSEvents and a fake local agent/MCP subprocess; it makes no model call. Do not interpret these checks as destructive-service or provider equivalence validation.

Latest completed checks before this handoff: default suite **167 tests, passed, 2 opt-in native tests skipped**; cleanup selector integration **22 focused tests passed**; rebuilt helper and real FSEvents/fake-agent integration passed (full → unchanged incremental → changed subtree → unchanged incremental); portable app reports version **0.3.0**. Native opt-in result is recorded in `research/validation-0.3.md`.

Releases: `dist/Soji-0.3.0.zip`, `dist/Soji.zip`, `dist/soji.pyz`. Research extraction scripts expect the external original evidence paths noted in each report; bounded evidence slices are included in the release. Tests alone do not demonstrate equality with Sōji's private source.

## Superseded worker handoff items

These are already connected; do not reimplement them from an older report:

- Engine: declared rule age maps and early-reason fields; mode clocks; configured recent activity; managed catalogs; hardlink proration.
- Index/AI: raw-content schema migration, reusable-verdict bridge and pre-apply baseline snapshots.
- Activity: Codex process/writer-lock holds; explicit native failure states.
- Native: coordinated version operation, stable-unit selector through native plans and rebuilt binary.

Outstanding items above remain work; old reports retain their original evidence and chronology for traceability.
