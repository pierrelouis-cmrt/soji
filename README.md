# Sōji 0.3 — consumer-build reconstruction

**Current handoff:** [NEXT_STEPS.md](NEXT_STEPS.md) records what was rushed, completed integration, validation and the ordered remaining work. It supersedes older coordinator TODOs.

A standalone macOS disk-analysis codebase built from the recoverable contracts and resources of Sōji 2026.11.14. The core is Python 3.10+ with a small Swift helper for FSEvents, native metadata, running app identities, and document versions. No pip dependencies or original Sōji executable are required.

**Start with [the reconstruction recap](RECONSTRUCTION_RECAP.md) and [FIDELITY.md](FIDELITY.md):** the 375 hint objects are exact; executable behavior is independently reconstructed, with explicit compatibility limits. This is a substantial functional port, not a proven line-for-line decompilation.

## Quick start

```sh
./soji ~/Library/Caches
./soji scan ~/Documents --mode careful --plain
./soji scan ~/Library/Caches --mode aggressive --json --output report.json
./soji --demo
```

Double-click **Launch Sōji.command** for the TUI. The single-file `soji.pyz` can be moved elsewhere and run with Python 3.10+. The included native binary is universal ARM64/x86-64, targeting macOS 13+. Build on macOS with Xcode Command Line Tools when changing its source.

The default state directory is `~/Library/Application Support/Soji`, separate from the original app. Use `--state PATH` to change it. Ordinary scans persist their index but do not delete candidate files or launch AI. `--no-index` performs a fresh non-persistent scan. `--refresh` forces index reconciliation. `--protect PATH` excludes a subtree. `--max-files`, `--max-seconds`, and `--min-mb` bound traversal/visibility. `--recent-activity-hours` sets the recency exclusion window. `--no-context` disables activity checks and leaves candidates unverified.

## Core commands

```sh
# Index and reclassification
./soji scan ~/Documents ~/Library/Caches --mode balanced
./soji watch ~/Documents --interval 5
./soji activity ~/Documents/MyProject
./soji rules node-modules
./soji processes memory

# AI: inspect the generated prompt/config before launching anything
./soji agents
./soji analyse ~/Library/Caches --agent claude --dry-run --json
./soji analyse ~/Library/Caches --agent claude --model MODEL --json
./soji analyse ~/Documents --agent codex --effort high --json
./soji analyse ~/Documents --agent custom --command 'my-agent --prompt-file {prompt_file} --mcp {mcp_config}' --json
```

`analyse` without `--dry-run` uses the selected installed CLI/account. It can incur provider usage and send disk context to that provider. Default scans do neither. Agent runs use their own report/index snapshot, local MCP tools and run folder; parsed judgments never clear local safety holds. Cached judgments are reused on subsequent scans until changed or expired.

## Review, clean, undo

```sh
# Generate an expiring plan; default method is Trash
./soji plan ~/Library/Caches --mode balanced --output plan.json
./soji clean plan.json                   # review only
./soji clean plan.json --apply           # execute verified Trash moves
./soji journal
./soji undo JOURNAL_ENTRY_ID --apply
./soji recover                           # inspect interrupted Trash moves
./soji recover --apply                   # reconcile verified moves into the journal

# Permanent cleanup is a separate explicit choice
./soji plan ~/Library/Caches --mode aggressive --method permanent --output permanent.json
./soji clean permanent.json --apply --permanent
# Official/native tool actions additionally require --execute-tools
./soji clean permanent.json --apply --permanent --execute-tools
```

The executor remeasures and rechecks the target before each action. Changed identities/contents, active files, source-control holds, protected paths, stale plans, ambiguous tool scopes and incomplete measurements are refused. Permanent cleanup cannot be undone. Cross-volume moves are refused. Inspect every plan path, particularly with agent-selected findings or app uninstall plans.

## Native catalogs and app uninstall

```sh
./soji versions ~/Documents/report.pages
./soji versions ~/Documents/report.pages --plan --output versions-plan.json
./soji runtimes
./soji runtimes --plan --output runtimes-plan.json
./soji clean versions-plan.json --apply --permanent --execute-tools

./soji apps
./soji uninstall co.example.App --output uninstall-plan.json
./soji clean uninstall-plan.json --apply
```

Document-version plans keep the document, newest older version and conflicts. Runtime plans preserve active and newest runtime builds and revalidate against current simctl state. App uninstall requires an explicitly chosen non-Apple app, refuses a running app, lists attributable user-library data, and moves each listed item to Trash. Privileged/system package leftovers are excluded.

## Routines and low-space policy

```sh
./soji routines save routine.json
./soji routines list
./soji routines run nightly                 # inspect proposal
./soji routines run nightly --apply         # permanent routine cleanup
./soji auto ~/Library/Caches --auto-settings auto.json
./soji auto ~/Library/Caches --auto-settings auto.json --apply --permanent
```

Example `routine.json`:

```json
{"id":"nightly","enabled":true,"paths":["/Users/YOU/Library/Caches"],"groups":["App caches"],"mode":"careful","unusedForHours":168,"everyHours":24}
```

Example `auto.json`:

```json
{"enabled":true,"freeBelowPercent":5,"minGainBytes":1000000000,"minHoursBetweenRuns":6,"groups":["Package caches"]}
```

Schedules may use daily, weekly, or monthly calendar rules (month-end days are clamped), or an `everyHours` interval. The eight shipped templates are included in `data/routine-templates.json`. Calendar weekdays use Sunday=1 through Saturday=7. These policies allow only eligible regenerable data. They install no background job and run only when invoked. Routines and auto mode remove permanently, as the original product describes; their proposal commands make no cleanup changes.

## TUI

**1/2/3** Careful/Balanced/Aggressive; **↑↓** or **J/K** items; **←→** or **H/L** categories; **Enter** details (scroll with ↑↓); **/** search; **A** eligible only; **S** sort; **E** export; **C** cancel; **R** rescan; **?** help; **Q** quit. Cleanup stays in the explicit CLI workflow. Minimum terminal size: 82×18. `--demo` is synthetic and clearly labeled.

## Source layout

- `engine.py`, `locations.py`: scanning, matching, measurements, modes and configured roots.
- `specialized.py`: all 17 recovered rule fields, retention and pins.
- `activity.py`, `gitstate.py`, `apps.py`: local activity and dependencies.
- `index.py`, `native/SojiNative.swift`: persistent indexing and macOS integration.
- `ai.py`, `mcp.py`: prompts, presets, isolated runs, schemas, cache and verification.
- `catalogs.py`, `nativeplans.py`: session parts, Trash, document/runtime catalogs.
- `cleanup.py`, `commands.py`, `uninstall.py`, `routines.py`: plans and actions.
- `tests/`: fixture-based verification; `scripts/native_integration.py`: real FSEvents and a fake-agent/MCP round trip, with no model call or personal cleanup.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/native_integration.py
python3 build_release.py
```

The native integration check must run outside a parent sandbox that blocks FSEvents or nested `sandbox-exec`. It creates and removes only its own fixtures under `tests/`. Model-provider compatibility and real simulator/device/archive varieties need additional comparison on representative test machines; see the fidelity document.

## Version 0.3 recovery pass

Modes now use recovered executable policies, including cumulative judgments and separate per-mode file/project clocks. Retention ranks by timestamps with mode-dependent counts. Activity readers, Codex live-session holds, index snapshot/reconciliation behavior, AI submission handling/cache policies, and cleanup recovery have been improved. See [research reports](research/README.md) for evidence and remaining gaps.

Automated AI cadence is available as a tested policy module; it is not installed as a background service. Device-build early outcomes, grouped Claude sidecars, exact prompt packing, signing/receipt attribution and reclaimed-space prediction remain incomplete.
