# Sōji data files

Static data that ships inside the `soji_cli` package. Nothing here runs code.
The Python modules named below load these files and give them meaning.

| File | Loaded by | What it holds |
| --- | --- | --- |
| `hints.json` | `engine.Catalog`, `commands.CommandPolicy` | The catalog: which paths Sōji recognises and when each may be cleaned |
| `groups.json` | `engine.Catalog` (TUI detail pane) | One plain-language explanation per group |
| `agents.json` | `ai.PRESETS` | How to find and launch each coding agent CLI for an AI analysis |
| `mcp-tools.json` | `mcp.TOOLS` | The MCP tools the agent may call, with their input schemas |
| `disk-prompt.txt` | `ai.AIAnalyzer.prompt` | The instructions sent to the agent for a disk analysis |
| `routine-templates.json` | not loaded yet | Suggested routines, in the `routines.json` format |

## Shared vocabulary

- **idle**: time since the newest change inside an item, or since a coding agent's last activity in it if that is later. Every age threshold counts idle time.
- **level**: the cleanup level the user picks, `careful` < `balanced` < `aggressive`. Levels are cumulative: anything careful takes, balanced and aggressive take too.
- **takes / ticks**: a level *takes* an item when it is eligible at that level, and the item is then *ticked* (pre-selected).
- **hold**: a reason that blocks an item at every level (running app, open file, secret inside, …). A rule can add holds but never lifts one.
- **review only**: listed so the user can decide, never ticked automatically.

## `hints.json`

An array of hints. **Order matters: the first hint whose pattern matches a path
wins**, with exact-name patterns tried before wildcard ones. Many entries overlap
(for example `~/Library/Caches/*` and a specific cache inside it), so the file is
not sorted by group. Put a new specific hint before the generic one it refines.

Fields, in the order they appear:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable identifier. Code, tests and saved indexes refer to it |
| `label` | yes | Name the user sees for a matched folder |
| `group` | yes | One of the names in `groups.json` |
| `patterns` | yes | Globs. `~` is the home folder, `*` stays inside one path segment, `**` spans any number of segments |
| `onlyIfContains` | no | The matched folder must contain one of these names (globs; a name with `/` is a relative path) |
| `unlessContains` | no | The matched folder must contain none of these names |
| `onlyIfAncestorContains` | no | One of the four folders above the match must contain one of these names (project markers such as `package.json`) |
| `tier` | yes | What losing it costs: `regenerable` (cheap to get back; from Careful, or from Balanced when it `downloads`), `costly` (slow or effortful to get back; Aggressive only), `userData` (the user's own data; never ticked), `never` (never ticked). Anything with `comesBack: gone` is never ticked |
| `comesBack` | yes | What happens after removal: `rebuilds` (made again locally), `downloads` (fetched again), `gone` (lost) |
| `reviewOnly` | no | `true`: list for review, never tick. Absent means `false` |
| `ruleSummary` | no | One plain line describing `rule`, shown in the TUI. Describe it at Balanced |
| `rule` | no | Machine conditions, see below |
| `cleanCommand` | no | The tool's official clean command, as argv. It is only allowed to run when its argv matches this exactly |
| `reference` | no | Where the paths and behaviour were checked (docs, source file, date) |

### `rule`

Every condition is optional. Unknown keys put a hold on the item, so a typo
never makes Sōji more aggressive. `specialized.py` implements them.

**Age.** Each level scales these values:

| Key | Meaning | Careful | Balanced | Aggressive |
| --- | --- | --- | --- | --- |
| `minIdleDays` | The item must have been idle this many days | ×2 | ×1 | ×0.5, at least 1 day |
| `minProjectIdleDays` | The project the item belongs to must have been idle this many days | ×4 | ×1 | ×0.25, at least 1 day |
| `sameIdleAtEveryLevel` | Agent worktrees only: once git shows a worktree is clean, merged and pushed, every level uses `minIdleDays` unscaled | | | |

**Retention.** Applies to sibling folders that are versions of one thing:

| Key | Meaning |
| --- | --- |
| `keepNewest` | Keep this many of the newest. An item counts as newest by its latest change *or* by the highest version in its name. Careful keeps one more and Aggressive one fewer (at least 1) |
| `keepNewestPer` | How siblings are grouped before `keepNewest` applies: `folder` (all siblings, the default), `product` (the name before the version), `majorVersion` (product plus major version), `minorVersion` (product plus major.minor), `device` (device model, for device support), `app` (bundle id, for Xcode archives) |
| `newestGoesAtAggressiveAfterDays` | At Aggressive, a newest copy loses `keepNewest` protection once idle this many days |
| `keepVersionPointedToBy` | Paths (symlinks or version files) that name the active version. That version is held. An nvm `alias/<name>` marker is resolved like nvm does (alias chains such as `lts/*` -> `lts/<codename>` -> version, `node`/`stable` = newest installed, partial versions match every installed version they cover), at most 16 hops, confined to `alias/` with no symlinks. A cycle, missing, unreadable or out-of-tree alias holds every version in the family |
| `keepProjectPinnedVersions` | `node`, `ruby` or `android`: hold any version a project on this Mac pins. Pin files are found across the scan roots plus the home (same exclusions as a scan), and rediscovered live on every cleanup check. `.nvmrc`/`.node-version` aliases resolve through nvm. An unreadable folder or pin file, or a time/size limit, holds the family |

**Holds.** Each one adds a hold when its condition fails:

| Key | Meaning |
| --- | --- |
| `notWhileRunning` | Process names. Held while any of them runs |
| `notWhileOwnerRuns` | Held while the installed app that owns the path runs. Held as well when no owner is found and `notWhileRunning` is not set |
| `onlyIfOwnerInstalled` | Held unless an installed app owns the path |
| `onlyIfOwnerNotInstalled` | Held while an installed app owns the path (for leftovers) |
| `notIfAppleOwned` | Held when the path belongs to an Apple app (`com.apple.*`) |
| `minSizeBytes` | Held when the item is smaller than this |

**Specialised checks.** Each one turns on custom logic for a single kind of item:

| Key | Meaning |
| --- | --- |
| `checkWorkspaceExists` | Xcode DerivedData: when the project's workspace is gone, Careful takes it and its age and retention gates are skipped |
| `checkCodexRuntime` | Codex runtime installs: holds the install whose `payload/*/runtime.json` bundle matches `codex-primary-runtime`, the highest bundle version among installs, and any with unreadable metadata |
| `checkDeviceBuilds` | Device support: held while a connected device runs that build. When a newer prepared build of the same device and version exists, Careful takes it |
| `checkSimulatorDevice` | Simulators: held unless shut down. When its runtime is gone, the levels take it after 7 days (Careful), 1 day (Balanced) or 1 hour (Aggressive) idle. A spare twin with no apps goes from Balanced after 7 idle days. Removed with `simctl delete` |

A hint with `keepNewest` or a specialised check is one cleanup unit: Sōji never
splits it around nested hints.

## `groups.json`

One entry per group. A hint's `group` must name one.

| Field | Meaning |
| --- | --- |
| `name` | The group name, as used in `hints.json` and the prompt |
| `whatItIs` | One plain line on what the group holds |
| `isItSafe` | One plain line on whether removing it loses anything, and when Sōji refuses to tick it |
| `howItComesBack` | One plain line on how it comes back. Absent when it doesn't |

## `agents.json`

One preset per agent CLI. Argument lists are argv tokens. Placeholders are
replaced when Sōji launches the agent: `{prompt}`, `{prompt_file}`,
`{mcp_config}`, `{mcp_inline}`, `{model}`, `{effort}` and `{max_turns}`.
`{flags}` expands to `readOnlyArguments`, then `maxTurnsArguments`,
`modelArguments` and `effortArguments`, each included only when that option is set.

| Field | Meaning |
| --- | --- |
| `id`, `name` | Identifier and display name. `codex` and `custom` have special launch code |
| `showInPicker` | `false` hides the preset from the agent picker. Absent means shown |
| `verified` | The preset has been tested end to end |
| `docsUrl`, `helpAnchor` | The CLI's reference docs, and the anchor of Sōji's help section |
| `binaries`, `searchPaths` | Executable names, looked up on `PATH` and then in these folders |
| `desktopApps` | Bundle ids of the vendor's desktop apps |
| `versionArguments` | Prints the CLI version |
| `runArguments` | One non-interactive analysis run |
| `readOnlyArguments` | Restrict the agent to reading and Sōji's tools |
| `modelArguments`, `effortArguments`, `maxTurnsArguments` | Added through `{flags}` when that option is set |
| `chatArguments`, `resumeArguments` | Start or resume an interactive session |
| `environment` | Extra environment variables for the run. Placeholders are expanded; `{mcp_config}` names the `configFile` config when there is one |
| `mcpAttach` | How Sōji's MCP server is attached: `flag` (a config path on the command line), `configFile` (a file written into the run's work folder) or `inlineConfig` (inline on the command line) |
| `mcpFormat` | Format of that config: `mcpServers`, `toml`, `opencode` or `codexInline` |
| `mcpConfigFile` | Where the config goes, relative to the work folder for `configFile` |
| `mcpServerFields` | Extra fields merged into Sōji's server entry |
| `mcpConfigFields` | Extra top-level fields (tool excludes, permission denials) merged into the `configFile` config |
| `writablePaths` | Paths the sandbox lets the agent write, besides the run folder. `*` matches within one segment, and paths with unset `$VARS` are skipped |

## `mcp-tools.json`

Standard MCP tool definitions (`name`, `title`, `description`, `annotations`,
`inputSchema`). `mcp.py` validates every call and the final `submit_findings`
payload against these schemas. A tool's `name` must match its branch in
`MCPServer.call`, and `disk-prompt.txt` lists the names too.
