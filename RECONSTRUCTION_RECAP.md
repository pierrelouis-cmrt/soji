# Version 0.3 update

**Current handoff:** [NEXT_STEPS.md](NEXT_STEPS.md) records what was rushed, completed integration, validation and the ordered remaining work. It supersedes older coordinator TODOs.

The parallel recovery pass improves the working terminal implementation with executable-derived base modes, per-mode rule clocks and retention, bounded activity readers, Codex live-session guards, daily snapshots/full-check scheduling, richer native metadata, AI cache/submission behavior and cleanup failure recovery. Consumer-build evidence and remaining gaps are in [research/README.md](research/README.md).

Still incomplete: early specialized outcomes, grouped Claude sidecars, exact prompt packing and background scheduling, signing/receipt attribution, exact reclaim estimates and complete provider validation. No numeric similarity percentage is justified. The core algorithms are materially closer, while whole-app equivalence remains unproven.

The recap below records the earlier baseline; use FIDELITY.md and recovery reports for current behavior.

# Sōji: fidelity and remaining work

Assessment of reconstruction 0.2.0, based on the installed Sōji 2026.11.14 consumer build. The original repository was not accessed. This document separates three questions: what was recovered, which fidelity questions require observing Sōji, and which engineering work can proceed independently. It also records the concrete original-product issue found during the assessment.

## How close is it?

The static catalog is exact. The architecture and many contracts are recognizable. The running algorithms are an independent reconstruction, with incomplete evidence of behavioral equivalence. A percentage would obscure those differences.

### Exact or directly recoverable

- All 375 shipped hints and 28 category definitions, with provenance hashes.
- All 11 shipped agent presets, including the custom preset.
- The ten MCP input schemas, tool names, and discovery contracts.
- Careful / Balanced / Aggressive vocabulary, per-level hour judgments, submission markers, and portions of tier/recency selection logic confirmed in ARM64 disassembly.
- The instruction portion of an existing disk-analysis prompt. Its personal indexed context was removed and its current-mode sentence generalized.
- The original index schemas, activity-source identities, numerous SQL statements, function names, and model fields as research evidence. The new index uses its own schema.

### Implemented, with working tests

The port has a scanner and matcher; handlers for all 17 recovered SmartRule fields; activity readers for Claude, Codex, T3 and editor workspaces; Git and installed-tool checks; SQLite/FSEvents indexing; AI verdict caching; independent MCP and agent orchestration; native metadata and cleanup catalogs; plans, fresh verification, Trash/permanent operations, journal recovery and undo; official command policies; worktree removal; explicit app uninstall; routines and auto-mode policy.

The evidence includes 68 tests, real FSEvents reuse/update checks, a real read-only npm-cache scan, and a packaged fake-agent/MCP round trip. Destructive tests used disposable fixtures. No live model call or deletion of personal data was used for validation.

**That establishes a functional implementation, not that all those subsystems produce the same answers as Sōji.** Field-handler coverage is not exhaustive branch coverage. See FIDELITY.md for the detailed limits.

## Work that still needs evidence from Sōji

This is reverse-engineering or differential-testing work, rather than ordinary feature implementation:

1. **Specialized selection semantics.** Compare exact version/build ordering, retention families, archive upload markers, active aliases, pinned versions, connected-device and simulator exceptions, and interactions between default rules and AI judgments. Some are currently interpreted from schemas, strings and descriptions rather than fully traced executable branches.
2. **AI input preparation and scheduling.** Reconstruct precisely which rows are sent first, batching, context packing, invalidation, retries, background cadence and power/idle policies. The port's input cap, daily budget, some fallback ages and maintenance intervals are implementation choices.
3. **Activity semantics.** Confirm how Sōji interprets archived sessions, source timestamps, editor state, nested projects, missing workspaces, live sessions, incomplete sources and source-specific freshness limits.
4. **Storage accounting.** Compare APFS clone sharing, compressed/purgeable storage, package rollups, date-added behavior, unreadable subtrees and physical reclaim estimates on the same corpus.
5. **Cleanup behavior.** Compare action choice, Trash bypasses, per-part cleanup, native-tool scopes, late revalidation and recovery outcomes on disposable copies. Cross-volume and privileged/receipt-based removal are not implemented in this port.
6. **Contradictory artifacts.** Resolve differences such as prose versus numeric ages, or the Codex session hint versus generic prompt guidance, by testing what the app actually does.

The best next artifact is a shared fixture corpus and normalized exports from both apps: matched hint ID, group, size, timestamps, hold reasons, retained version family, per-mode judgment, and chosen action. Use the same provider/model/settings when comparing AI runs. Model variability should be measured separately from deterministic differences.

This does not require access to the private repository, but representative app observations or further binary analysis are necessary to claim equivalence. Private-source access would make that validation much faster if you choose to use it later.

## Work that can proceed independently

These are engineering and product tasks. Waiting for more Sōji reverse engineering is unnecessary:

- **Build the comparison harness.** Create versioned filesystem, Git, session, simulator-response and archive fixtures; normalize output; classify differences as matching, measuring, activity, policy, AI or execution differences.
- **Production hardening.** Expand adversarial race and failure tests, crash recovery, concurrent-index access, locks, schema migrations, permission errors, configuration validation and journaling durability. A successful fixture suite does not establish production safety.
- **Scale and performance.** Profile large home directories, metadata memory usage, database writes, event bursts and cancellation. The current index loads node records into memory and rewrites its stored node set; further database-level incremental optimization is possible.
- **Provider compatibility.** Exercise actual supported CLI versions and real agent runs on an explicitly selected test corpus. Preset preparation and a fake agent have been tested; each provider's live behavior has not.
- **Adapter robustness.** Maintain schema-version fixtures, parse diagnostics and compatibility handling for evolving agent/editor/device tools. Clearly distinguish unavailable evidence from confirmed inactivity.
- **Missing macOS capabilities.** Implement and validate cross-volume Trash, receipt/system-leftover handling, fuller storage accounting and optional GPU/process monitoring if these belong in the terminal product.
- **Distribution and maintenance.** CI, reproducible releases, supported Python/macOS testing, signing/notarization decisions, installation, versioning and release documentation.
- **CLI/TUI polish.** Better help/discovery, configuration, progress, filtering and structured errors. The current TUI is primarily a test surface.

Original UI, payment enforcement, updater, telemetry, notifications, and background login-item installation are deliberate exclusions, not reverse-engineering blockers for a disk-analysis terminal product.

## What needs work in the original Sōji product

One issue was experimentally established: the agent sandbox allowed writes to the live SQLite index's WAL sidecar while denying writes to the main database. A disposable reproduction changed what the shipped MCP helper read while the main database hash stayed unchanged.

**Fix priority:** treat the database and sidecars as one integrity boundary. Use a trusted query service or an isolated consistent snapshot, and retain independent filesystem verification at cleanup time. The port uses a standalone backup and denies agent writes to that snapshot and its sidecars, as well as the report and sandbox profile.

Other observations are protection opportunities, not proven exploits:

- Extensive shipped Swift symbols/reflection metadata reduce reconstruction effort. Audit the distributed release artifact, keeping private symbols for crash analysis.
- The classification catalog, prompts, schemas and presets are observable client assets. Obfuscation can add effort but cannot make locally executed behavior permanently secret from the machine owner.
- Out-of-root metadata queries were possible in the original MCP fixture test. Decide whether roots are an intended read boundary and enforce that policy consistently.

No license bypass, arbitrary personal-file deletion, backend compromise or original signing defect was demonstrated.

## Recommended next milestone

Build the deterministic comparison harness first. It turns “how close is this?” into a list of reproducible differences and prevents independent improvements from being mistaken for faithful behavior. Then resolve the highest-impact differences in selection and cleanup before making the executor a daily-use product.
