# Sōji 0.4

A macOS disk-cleanup command line: 375 cleanup rules, three modes (careful, balanced, aggressive) and layered safety checks. Scanning never deletes anything; cleaning goes to the Trash after a confirmation and can be undone. macOS 13+, Python 3.9+ (the version included with Apple's Command Line Tools is enough), no pip dependencies. It includes a universal Swift helper for the disk walk, FSEvents, metadata, running apps and document versions. Open work: [NEXT_STEPS.md](NEXT_STEPS.md).

## Install

**With Homebrew** (recommended: Homebrew provides Python and handles updates):

```sh
brew install pierrelouis-cmrt/tap/soji
soji
```

Update with `brew upgrade soji`, remove with `brew uninstall soji`.

**Without Homebrew** (one command, no admin password, nothing outside your home folder):

```sh
curl -fsSL https://raw.githubusercontent.com/pierrelouis-cmrt/soji/main/install.sh | sh
```

Then open a new Terminal window and run `soji`.

- The script installs `soji.pyz` into `~/.local/share/soji` and a `soji` command into `~/.local/bin`, verifies the SHA-256 checksum published with the release, and adds `~/.local/bin` to your `PATH` in `~/.zshrc` if needed (`SOJI_NO_MODIFY_PATH=1` to skip that).
- It uses any Python 3.9+ already installed. If there is none, it asks you to run `xcode-select --install` (Apple's Command Line Tools, which include Python) and then run it again.
- Update by running the same command again. A specific version: `… | sh -s -- --version 0.4.0`. Uninstall: `… | sh -s -- --uninstall`.

Both methods install the same file from the same GitHub release. Neither one leaves a quarantined download behind, so macOS shows no "unidentified developer" warning.

**Updates.** When Sōji opens its interactive view, or runs a command that can delete (`clean --apply`, `auto --apply`, `routines run --apply`), it asks GitHub for the latest release (cached for 15 minutes in the state folder). If a newer version exists, the interactive view offers to update right away (`brew upgrade soji`, the install script, or `git pull` for a checkout) and restarts. If you decline, Sōji runs in scan-only mode: scanning, categorizing and planning work, but nothing can be cleaned until you update. If the check can't complete (offline, GitHub unreachable), cleaning stays available and Sōji prints a note.

Your index, plans and journal live in `~/Library/Application Support/Soji`. Uninstalling keeps them; delete that folder to remove them.

**From source:** `git clone https://github.com/pierrelouis-cmrt/soji && cd soji && ./soji`. You can also double-click `Launch Sōji.command`. The examples below write `soji`; from a checkout, use `./soji`.

## Scan

```sh
soji ~/Library/Caches                         # TUI (when interactive)
soji scan ~/code --mode careful --plain       # careful | balanced | aggressive
soji scan ~/Library/Caches --json --output report.json
soji --demo                                   # synthetic data
```

- State lives in `~/Library/Application Support/Soji` (`--state PATH` to change). Scans keep an incremental index (`--no-index` to skip it, `--refresh` to force a full walk). Scans never delete anything or call a model.
- Options: `--protect PATH`; `--max-files`, `--max-seconds` and `--min-mb` bound the scan; `--recent-activity-hours` sets the recent-use window; `--no-context` turns off process/activity checks, and rows are then held as unverified.
- The disk walk runs in the helper (parallel `getattrlistbulk`, results identical to the Python walk); without the helper, or with `SOJI_NATIVE_WALK=0`, the Python walk is used. Cleanup always re-measures targets with the Python walk. `SOJI_NATIVE_WALK_THREADS` sets the worker count (default: up to 8).
- The TUI grows the Terminal window to 124×36 at launch if it is smaller, then restores it on exit (`SOJI_NO_RESIZE=1` turns this off).

## AI mode

Run it from Claude Code, Codex or any agent with a shell:

```sh
soji --ai ~/Library/Caches ~/code      # agent instructions + rows with stable ids
soji ai inspect ROW_ID                 # largest children, evidence, same-rule rows
soji --ai ~/code --rule node-modules    # one rule at a time (large briefings print a per-rule summary)
soji ai propose verdicts.json          # {"verdicts":[{"id":"…","action":"remove|keep|review","reason":"…","unusedDays":30}]}
soji clean PLAN                        # review
soji clean PLAN --apply                # Trash; undo with `soji undo ID --apply`
soji ai skill > ~/.claude/skills/soji/SKILL.md
```

Sōji enforces:

- ids must come from a session under 6 hours old;
- only `remove` verdicts become plan items, each re-scanned and required to be unchanged;
- every local guard still applies (holds, 24 h recent-use window, personal and review-only data, active versions, Git, secrets);
- `clean` re-verifies everything before acting.

Sōji sends metadata only and calls no provider. It cannot sandbox an agent that has its own shell.

Legacy `analyse` (soji launches an agent; `agents` lists presets, and `--dry-run` shows the prompt) still works.

## Plan, clean, undo

```sh
soji plan ~/Library/Caches --mode balanced --output plan.json
soji clean plan.json                    # review only
soji clean plan.json --apply            # verified Trash moves
soji journal; soji undo ID --apply; soji recover [--apply]
soji plan … --method permanent --output p.json
soji clean p.json --apply --permanent [--execute-tools]
```

Before each action, soji re-measures the target and refuses it if any of these apply: changed identity or contents, active use, Git work, a protected path, an expired plan, an ambiguous tool scope or an incomplete measurement. Cross-volume moves are refused. `--execute-tools` is required for official cleanup commands, simulators, document versions and worktrees.

Batch cleanup re-measures each selected session (including its freshly discovered Claude sidecars) or Trash item without repeatedly scanning the rest of its catalog. Process/open-file and Codex writer-lock snapshots are shared for at most one second within a batch; activity/app/tool inventories refresh after five seconds. No target measurements or identities are reused, and caches are discarded after the batch. Every move retains the durable journal checkpoints used for recovery and undo.

## Other commands

```sh
soji versions FILE [--plan]            # document versions: keeps current, newest older, conflicts
soji runtimes [--plan]                 # simulator runtimes: keeps active and newest
soji apps; soji uninstall BUNDLE_ID  # Trash plan; shared leftovers listed, never removed
soji routines save|list|run ID [--apply]
soji auto PATH --auto-settings auto.json [--apply --permanent]
soji watch PATH; soji activity PATH; soji rules ID; soji processes [cpu|memory]
```

- Routines (daily, weekly, monthly or `everyHours`) and `auto` (low free space) cover regenerable data only and remove permanently. They run only when invoked.
- Example routine: `{"id":"nightly","enabled":true,"paths":["/Users/YOU/Library/Caches"],"groups":["App caches"],"mode":"careful","unusedForHours":168,"everyHours":24}`.
- Templates: `soji_cli/data/routine-templates.json`.

**Cleaning from the TUI:** mark rows with Space (or mark nothing to take every READY row in the current category, search and mode), press X, check the list, press Y. Items go to the Trash through the same plan and re-checks as `soji clean --apply` (plan saved under `tui-plans/` in the state folder, entries in `soji journal`); U restores the batch. Permanent deletion and tool actions (simulators, document versions, worktrees) stay terminal commands.

A quiet status bar shows disk scanning, category sorting, and cleanup progress. Scanning uses an animated bar and entry count until a total is known; sorting and cleaning show completion counts. Cleanup runs in a worker so the screen continues updating and resizing. Other actions wait until the batch finishes.

**TUI keys:**

| Key | Action |
|---|---|
| 1 / 2 / 3 | Mode |
| ↑ ↓ or J / K | Items |
| g / G (Home / End) | First / last item |
| ← → or H / L | Categories |
| Enter | Details |
| / | Search |
| A | Eligible rows only |
| Space | Mark / unmark a READY row |
| X | Clean the marked rows (or, with none marked, every READY row in view) → confirm → Trash |
| U | Put the last cleaned batch back |
| S | Sort |
| E | Export |
| C | Cancel scan |
| R | Rescan |
| ? | Help |
| Q | Quit |

## Layout

| Path | Contents |
|---|---|
| `engine.py`, `locations.py`, `levels.py`, `specialized.py` | Scan, match, modes, SmartRules |
| `activity.py`, `gitstate.py`, `apps.py` | Activity, Git, apps and tools |
| `index.py`, `walker.py`, `native/SojiNative.swift` | Index, native walk and macOS helper |
| `catalogs.py`, `nativeplans.py` | Sessions, Trash, versions, runtimes |
| `cleanup.py`, `commands.py`, `uninstall.py`, `routines.py` | Plans and actions |
| `agent.py` | `soji --ai`; `ai.py` and `mcp.py` are the legacy `analyse` path |
| `tests/` | Fixture tests, plus the regression corpus (`corpus.py`, `corpus_expected.json`) |

Validation commands: [NEXT_STEPS.md](NEXT_STEPS.md#validation).

## Publishing a release

1. Set the version in `soji_cli/__init__.py`, then run `python3 build_release.py` (needs the Xcode Command Line Tools for the universal helper). `dist/` then contains `soji.pyz`, `soji.pyz.sha256`, `Soji-VERSION.zip`, `install.sh` and `soji.rb`.
2. Create the GitHub release with the tag `vVERSION` and those files: `gh release create v0.4.0 dist/soji.pyz dist/soji.pyz.sha256 dist/Soji-0.4.0.zip dist/install.sh`. `install.sh` downloads `releases/latest`, so it picks up the new version automatically.
3. Homebrew: copy `dist/soji.rb` to `Formula/soji.rb` in the `pierrelouis-cmrt/homebrew-tap` repository and push it (the template is `packaging/homebrew/soji.rb`). `brew upgrade soji` then installs the new version.

The repository (`pierrelouis-cmrt/soji`) is set in `build_release.py` (`REPO`) and `install.sh` (`SOJI_REPO`).
