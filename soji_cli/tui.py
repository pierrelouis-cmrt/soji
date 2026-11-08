"""Dependency-free curses UI.

Scanning is read-only. Cleaning (Space to mark, X to clean, U to undo) only
moves items to the Trash, after a confirmation screen, through the same plan,
re-verification and journal as `soji clean PLAN --apply`.
"""

import collections
import curses
import json
import os
import textwrap
import threading
import time
from pathlib import Path

from .engine import MODE_TEXT, MODES, human

# Actions that need `soji clean --execute-tools --permanent`; never run from the TUI.
TOOL_ACTIONS = (
    "simulator-device",
    "simulator-runtime",
    "document-version",
    "git-worktree",
)


def cleanup_targets(rows, marked):
    """(targets, skipped) for X: marked rows if any are marked, else every row in
    view. Only rows soji selected in this mode qualify; tool actions are skipped."""
    pool = [f for f in rows if f.path in marked] if marked else list(rows)
    targets, skipped = [], []
    for f in pool:
        if not f.selected:
            skipped.append((f, "no longer eligible in this mode"))
        elif (f.action or {}).get("kind") in TOOL_ACTIONS:
            skipped.append((f, "needs soji clean --execute-tools"))
        elif not f.identity:
            skipped.append((f, "no file identity"))
        else:
            targets.append(f)
    return targets, skipped


def clean_targets(scanner, mode, targets, state_dir, cleaner=None, progress=None):
    """Plan the targets (Trash only), save the plan for audit, apply it."""
    from .cleanup import Cleaner, create_plan
    from .util import atomic_json

    plan = create_plan(scanner, mode, paths={f.path for f in targets}, method="trash")
    plans = Path(state_dir).expanduser() / "tui-plans"
    plans.mkdir(parents=True, exist_ok=True)
    atomic_json(plans / f"plan-{plan['id']}.json", plan)
    result = (cleaner or Cleaner(state_dir)).apply(plan, progress=progress)
    result["plan"] = str(plans / f"plan-{plan['id']}.json")
    result["freed"] = sum(
        e.get("sizeBytes", 0) for e in result["entries"] if e["status"] == "done"
    )
    return result


class CleanupJob:
    """Run a confirmed batch without blocking curses; publish whole snapshots."""

    def __init__(self, scanner, mode, targets, state_dir):
        self.progress = {"phase": "verify", "completed": 0,
                         "total": len(targets), "path": ""}
        self.result = None
        self.error = None
        self.done = threading.Event()
        self.thread = threading.Thread(
            target=self._run, args=(scanner, mode, targets, state_dir), daemon=False
        )
        self.thread.start()

    def _run(self, scanner, mode, targets, state_dir):
        try:
            self.result = clean_targets(
                scanner, mode, targets, state_dir,
                progress=lambda value: setattr(self, "progress", dict(value)),
            )
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.done.set()


def progress_line(progress, width=18, tick=None):
    """A quiet determinate bar, or a moving segment when no total is known."""
    phase = progress.get("phase", "scan")
    label = {"scan": "Scanning disk", "categorize": "Sorting categories",
             "verify": "Checking items", "clean": "Cleaning", "done": "Complete"}.get(phase, "Working")
    completed = max(0, progress.get("completed", 0))
    total = progress.get("total")
    width = max(4, width)
    if total is not None and total > 0:
        fraction = min(1, completed / total)
        filled = int(width * fraction)
        bar = "━" * filled + "─" * (width - filled)
        detail = f"{completed:,}/{total:,} · {fraction:.0%}"
    else:
        offset = int((time.monotonic() if tick is None else tick) * 5) % (width - 2)
        bar = "─" * offset + "━━━" + "─" * (width - offset - 3)
        detail = f"{completed:,} entries" if phase == "scan" else "Preparing…"
    return f"{label}  {bar}  {detail}"


def undo_entries(entries, state_dir, cleaner=None):
    """Restore completed Trash moves from one batch; returns (restored, errors)."""
    from .cleanup import Cleaner

    cleaner = cleaner or Cleaner(state_dir)
    restored = 0
    errors = []
    for e in entries:
        if e["status"] not in ("done", "partial"):
            continue
        try:
            cleaner.undo(e["id"])
            restored += 1
        except Exception as exc:
            errors.append(f"{e['path']}: {exc}")
    return restored, errors


def clean(text):
    # Paths are untrusted terminal text; never emit escape/control sequences.
    return "".join(c if c.isprintable() else "?" for c in str(text))


def run_tui(scanner, mode="balanced", export_path=None, state_dir=None):
    def main(scr):
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        curses.use_default_colors()
        for i, fg in [
            (1, curses.COLOR_CYAN),
            (2, curses.COLOR_GREEN),
            (3, curses.COLOR_YELLOW),
            (4, curses.COLOR_WHITE),
            (5, curses.COLOR_RED),
        ]:
            curses.init_pair(i, fg, -1)
        scr.keypad(True)
        scr.timeout(100)
        thread = threading.Thread(target=scanner.run, daemon=True)
        thread.start()
        state = {
            "mode": mode,
            "group": "All categories",
            "cursor": 0,
            "offset": 0,
            "query": "",
            "eligible": False,
            "details": False,
            "help": False,
            "message": "",
            "sort": "size",
            "detailOffset": 0,
            "marked": set(),
            "confirm": None,
            "result": None,
            "lastBatch": None,
            "cleanup": None,
        }
        from .demo import DemoScanner

        demo = isinstance(scanner, DemoScanner)
        analysis_key = None
        analysis_view = None
        rows_key = None
        cached_rows = []

        def rescan(refresh):
            nonlocal thread
            options = dict(
                home=scanner.home,
                protected=scanner.protected,
                max_files=scanner.max_files,
                max_seconds=scanner.max_seconds,
                min_bytes=scanner.min_bytes,
                context=scanner.context,
                recent_activity_hours=scanner.recent_activity_hours,
            )
            if hasattr(scanner, "database") and scanner.database:
                options.update(database=scanner.database, refresh=refresh)
            if demo:
                scanner.__init__()
            else:
                scanner.__init__(scanner.roots, **options)
            thread = threading.Thread(target=scanner.run, daemon=True)
            thread.start()

        def modal(title, lines, footer):
            h, w = scr.getmaxyx()
            boxw = min(w - 8, 108)
            wrapped = []
            for line in lines:
                wrapped.extend(
                    textwrap.wrap(clean(line), boxw - 5, subsequent_indent="  ") or [""]
                )
            boxh = min(h - 4, max(8, len(wrapped) + 5))
            ox = (w - boxw) // 2
            oy = (h - boxh) // 2
            for y in range(oy, oy + boxh):
                put(y, ox, " " * boxw, curses.A_REVERSE, width=boxw)
            put(oy + 1, ox + 2, title, curses.A_REVERSE | curses.A_BOLD, width=boxw - 4)
            room = boxh - 5
            shown = wrapped if len(wrapped) <= room else wrapped[: room - 1]
            for i, line in enumerate(shown):
                put(oy + 3 + i, ox + 2, line, curses.A_REVERSE, width=boxw - 4)
            if len(shown) < len(wrapped):
                put(
                    oy + 3 + len(shown),
                    ox + 2,
                    f"… and {len(wrapped) - len(shown)} more lines",
                    curses.A_REVERSE | curses.A_DIM,
                    width=boxw - 4,
                )
            put(
                oy + boxh - 2,
                ox + 2,
                footer,
                curses.A_REVERSE | curses.A_BOLD,
                width=boxw - 4,
            )

        def put(y, x, text, attr=0, width=None):
            h, w = scr.getmaxyx()
            if y < 0 or y >= h or x < 0 or x >= w:
                return
            text = clean(text)
            try:
                scr.addnstr(
                    y, x, text, max(0, min(w - x - 1, width or w - x - 1)), attr
                )
            except curses.error:
                pass

        def prompt(label):
            h, w = scr.getmaxyx()
            scr.timeout(-1)
            curses.echo()
            try:
                curses.curs_set(1)
                scr.move(h - 2, 0)
                scr.clrtoeol()
                put(h - 2, 0, label)
                raw = scr.getstr(
                    h - 2, min(len(label), w - 3), max(1, w - len(label) - 2)
                )
                return raw.decode("utf-8", "replace")
            finally:
                curses.noecho()
                scr.timeout(100)
                try:
                    curses.curs_set(0)
                except curses.error:
                    pass

        while True:
            job = state["cleanup"]
            if job is not None and job.done.is_set():
                job.thread.join()
                state["cleanup"] = None
                if job.error is not None:
                    state["message"] = "Clean failed: " + job.error
                else:
                    result = job.result
                    state["result"] = result
                    state["lastBatch"] = result["entries"]
                    state["marked"] -= {
                        e["path"] for e in result["entries"] if e["status"] == "done"
                    }
                    state["message"] = (
                        f"Moved {result['completed']} item(s) to the Trash ({human(result['freed'])}); {result['failed']} refused."
                    )
                    rescan(False)
            h, w = scr.getmaxyx()
            scr.erase()
            if h < 18 or w < 82:
                put(0, 0, "Resize Terminal to at least 82 columns x 18 rows."
                    + (" Cleaning continues…" if state["cleanup"] else " Q exits."))
                scr.refresh()
                if scr.getch() in (ord("q"), ord("Q")) and state["cleanup"] is None:
                    scanner.cancel.set()
                    break
                continue
            left = min(29, max(22, w // 5))
            right = left + 2
            put(1, 2, "SOJI / TERMINAL", curses.A_BOLD | curses.color_pair(1))
            put(1, right, "DISK ANALYSIS", curses.A_BOLD)
            put(
                1,
                w - 28,
                "LOCAL  ·  TRASH ON CONFIRM" if not demo else "DEMO  ·  NOTHING REAL",
                curses.color_pair(2),
            )
            x = right
            for i, name in enumerate(MODES, 1):
                label = f" {i} {name.capitalize()} "
                attr = (
                    curses.A_REVERSE | curses.A_BOLD
                    if state["mode"] == name
                    else curses.A_DIM
                )
                put(3, x, label, attr)
                x += len(label) + 2
            put(4, right, MODE_TEXT[state["mode"]], curses.A_DIM)
            # The status bar animates at 10 Hz; decisions and large table sorts
            # only need recomputing when the analysis or view actually changes.
            current_analysis = (
                id(scanner.findings), len(scanner.findings), scanner.now,
                scanner.done, state["mode"],
            )
            if analysis_key != current_analysis:
                findings = list(scanner.decisions(state["mode"]))
                groups = collections.defaultdict(lambda: [0, 0])
                for f in findings:
                    groups[f.group][0] += f.size
                    if f.selected:
                        groups[f.group][1] += f.size
                group_names = ["All categories"] + sorted(
                    groups, key=lambda k: groups[k][0], reverse=True
                )
                total = sum(f.size for f in findings)
                eligible = sum(f.size for f in findings if f.selected)
                analysis_key = current_analysis
                analysis_view = findings, groups, group_names, total, eligible
            findings, groups, group_names, total, eligible = analysis_view
            put(3, 2, "CATEGORIES", curses.A_DIM)
            group_index = (
                group_names.index(state["group"])
                if state["group"] in group_names
                else 0
            )
            group_offset = max(0, group_index - (h - 12))
            for i, g in enumerate(group_names[group_offset : group_offset + h - 10]):
                y = 5 + i
                active = g == state["group"]
                size = total if g == "All categories" else groups[g][0]
                put(
                    y,
                    2,
                    ("› " if active else "  ") + g,
                    curses.A_BOLD | curses.color_pair(1) if active else 0,
                    width=left - 3,
                )
                if active and y + 1 < h - 5:
                    pass
            put(h - 5, 2, human(scanner.bytes) + " measured", curses.A_BOLD)
            put(h - 4, 2, human(eligible) + " eligible", curses.color_pair(2))
            marked_rows = [f for f in findings if f.path in state["marked"]] if state["marked"] else []
            if marked_rows:
                put(
                    h - 3,
                    2,
                    f"{len(marked_rows)} marked · {human(sum(f.size for f in marked_rows))}",
                    curses.color_pair(1) | curses.A_BOLD,
                )
            for y in range(2, h - 2):
                put(y, left, "│", curses.A_DIM)
            status = (
                "Scanning"
                if not scanner.done
                else "Partial scan"
                if scanner.limited or scanner.cancel.is_set()
                else "Scan complete"
            )
            operation = None
            if state["cleanup"] is not None:
                operation = state["cleanup"].progress
            elif not scanner.done:
                operation = getattr(scanner, "progress", None) or {
                    "phase": "scan", "completed": scanner.visited, "total": None,
                    "path": scanner.current,
                }
            put(
                6, right,
                progress_line(operation, width=min(18, max(4, w - right - 44)))
                if operation else
                f"{status}  ·  {scanner.visited:,} entries  ·  {scanner.unreadable} unreadable  ·  {scanner.skipped} excluded",
                curses.A_DIM,
            )
            put(
                7, right,
                scanner.error or (
                    operation.get("path", "").replace(scanner.home, "~", 1)
                    if operation else "Scope: " + ", ".join(scanner.roots)
                ),
                curses.A_DIM,
            )
            current_rows = (analysis_key, state["group"], state["eligible"],
                            state["query"], state["sort"])
            if rows_key != current_rows:
                query = state["query"].casefold()
                cached_rows = [
                    f for f in findings
                    if (state["group"] == "All categories" or f.group == state["group"])
                    and (not state["eligible"] or f.selected)
                    and (not query or query in (f.path + " " + f.group + " " + f.label).casefold())
                ]
                if state["sort"] == "name":
                    cached_rows.sort(key=lambda f: f.path.casefold())
                elif state["sort"] == "age":
                    cached_rows.sort(key=lambda f: f.newest)
                rows_key = current_rows
            rows = cached_rows
            state["cursor"] = min(state["cursor"], max(0, len(rows) - 1))
            page = max(1, h - 16)
            state["offset"] = min(state["offset"], state["cursor"])
            if state["cursor"] >= state["offset"] + page:
                state["offset"] = state["cursor"] - page + 1
            put(9, right, f"{'SIZE':>10}   {'STATE':<7}  ITEM / CATEGORY", curses.A_DIM)
            for i, f in enumerate(rows[state["offset"] : state["offset"] + page]):
                y = 10 + i
                chosen = state["offset"] + i == state["cursor"]
                attr = curses.A_REVERSE if chosen else 0
                if chosen:
                    put(y, right, " " * (w - right - 1), attr)
                status = "READY" if f.selected else "HELD" if f.holds else "REVIEW"
                put(y, right, f"{human(f.size):>10}", attr | curses.A_BOLD)
                if f.path in state["marked"]:
                    put(y, right, "✓", attr | curses.A_BOLD | curses.color_pair(1))
                put(
                    y,
                    right + 13,
                    f"{status:<7}",
                    attr | curses.color_pair(2 if f.selected else 3 if f.holds else 4),
                )
                text = f.label + "  ·  " + f.path.replace(scanner.home, "~", 1)
                put(y, right + 22, text, attr)
            if not rows:
                put(
                    12,
                    right,
                    "Measuring folders…"
                    if not scanner.done
                    else "No items match this view.",
                    curses.A_DIM,
                )
            selected = rows[state["cursor"]] if rows else None
            put(
                h - 5,
                right,
                f"{len(rows)} items  ·  sort: {state['sort']}"
                + ("  ·  filter: " + state["query"] if state["query"] else "")
                + ("  ·  eligible only" if state["eligible"] else ""),
                curses.A_DIM,
            )
            if selected:
                put(
                    h - 4,
                    right,
                    selected.decision,
                    curses.color_pair(2 if selected.selected else 3),
                )
            put(
                h - 2,
                2,
                "Cleaning in progress · items are re-checked before moving to Trash"
                if state["cleanup"] is not None else
                "↑↓ items  ←→ category  1–3 mode  Space mark  X clean  U undo  Enter details  / search  A eligible  S sort  ? help  Q quit",
                curses.A_DIM,
            )
            if state["message"] and state["cleanup"] is None:
                put(h - 3, right, state["message"], curses.color_pair(1))
            if state["help"] or (state["details"] and selected):
                boxw = min(w - 8, 108)
                boxh = min(h - 4, 30)
                ox = (w - boxw) // 2
                oy = (h - boxh) // 2
                for y in range(oy, oy + boxh):
                    put(y, ox, " " * boxw, curses.A_REVERSE, width=boxw)
                if state["help"]:
                    lines = [
                        "KEYS / RECONSTRUCTION NOTES",
                        "",
                        "1 Careful — only clearly disposable items.",
                        "2 Balanced — stale items, with per-item judgments.",
                        "3 Aggressive — unused recoverable items.",
                        "",
                        "All modes respect holds, retained versions, activity, and identity.",
                        "375 exact hints; independently reconstructed rules and index.",
                        "",
                        "CLEANING",
                        "Space: mark or unmark a READY row.",
                        "X: clean the marked rows, or with nothing marked, every READY row in the current view",
                        "   (category, search and mode). A confirmation lists everything first.",
                        "Items go to the Trash after the same re-checks as soji clean; held, changed or",
                        "in-use items are refused. U: put the last batch back. Permanent deletion,",
                        "simulators, document versions and worktrees stay terminal commands.",
                        "",
                        "↑/↓ or J/K: items     ←/→ or H/L: categories",
                        "Enter: evidence       /: search       A: eligible only",
                        "S: cycle size/name/age   E: export JSON   R: rescan",
                        "C: cancel scan          Q: exit         Esc: close",
                    ]

                else:
                    f = selected
                    age = max(0, (scanner.now - f.newest) / 3600)
                    lines = [
                        f.label,
                        f.path,
                        "",
                        f"{human(f.size)} allocated · {human(f.apparent)} logical · {f.files:,} files · idle {age:.1f} h",
                        f"Category: {f.group}",
                        f"Hint: {f.hint_id or 'unmatched'} · tier: {f.tier} · returns: {f.comes_back}",
                        f"Pattern: {f.matched_pattern or 'none'}",
                        "",
                        "DECISION: " + f.decision,
                        "",
                        "SHIPPED RULE: " + (f.smart_rule or "No explanatory rule text"),
                        json.dumps(f.rule, ensure_ascii=False),
                        "",
                    ]
                    about = scanner.catalog.groups.get(f.group, {})
                    lines += [
                        about[k] for k in ("whatItIs", "howItComesBack") if about.get(k)
                    ]
                    lines += ["", "MODE COMPARISON"]
                    for m in MODES:
                        yes, why = f.decide(m, scanner.now)
                        lines.append(f"{m:9} {'READY' if yes else 'KEEP':5} {why}")
                wrapped_lines = []
                for line in lines:
                    wrapped_lines.extend(textwrap.wrap(clean(line), boxw - 5) or [""])
                visible = boxh - 3
                state["detailOffset"] = min(
                    state["detailOffset"], max(0, len(wrapped_lines) - visible)
                )
                for i, line in enumerate(
                    wrapped_lines[
                        state["detailOffset"] : state["detailOffset"] + visible
                    ]
                ):
                    put(oy + 1 + i, ox + 2, line, curses.A_REVERSE)
                put(
                    oy + boxh - 2,
                    ox + 2,
                    "↑↓ scroll · Esc / Enter close",
                    curses.A_REVERSE | curses.A_BOLD,
                )
            if state["confirm"]:
                targets, skipped = state["confirm"]
                lines = [
                    f"{len(targets)} item(s), {human(sum(f.size for f in targets))}, will be moved to the Trash ({state['mode']} mode).",
                    "",
                ]
                lines += [
                    f"{human(f.size):>10}  {f.path.replace(scanner.home, '~', 1)}"
                    for f in targets
                ]
                if skipped:
                    lines += ["", f"Not included ({len(skipped)}):"] + [
                        f"{human(f.size):>10}  {f.path.replace(scanner.home, '~', 1)} — {why}"
                        for f, why in skipped
                    ]
                lines += [
                    "",
                    "Each item is re-checked first; anything changed, in use or held is refused.",
                    "Undo afterwards with U, or soji journal / soji undo ID --apply.",
                ]
                modal(
                    "CLEAN — CONFIRM", lines, "Y move to Trash · any other key cancels"
                )
            elif state["result"]:
                r = state["result"]
                lines = [
                    f"Moved {r['completed']} item(s) to the Trash · {human(r['freed'])} freed.",
                    "",
                ]
                failed = [e for e in r["entries"] if e["status"] != "done"]
                if failed:
                    lines += (
                        [f"Refused or failed ({len(failed)}):"]
                        + [
                            f"  {e['path'].replace(scanner.home, '~', 1)} — {e.get('error', '')}"
                            for e in failed
                        ]
                        + [""]
                    )
                lines += [
                    "Press U to put this batch back. Rescanning in the background.",
                    "Plan saved: " + r["plan"].replace(str(Path.home()), "~", 1),
                ]
                modal("CLEAN — DONE", lines, "any key closes")
            scr.refresh()
            key = scr.getch()
            if key == -1:
                continue
            if state["confirm"]:
                targets, _ = state["confirm"]
                state["confirm"] = None
                if key not in (ord("y"), ord("Y")):
                    state["message"] = "Clean cancelled; nothing was moved."
                    continue
                state["message"] = ""
                state["cleanup"] = CleanupJob(scanner, state["mode"], targets, state_dir)
                continue
            if state["cleanup"] is not None:
                # Keep painting and resizing; never leave a live mutation worker
                # behind or allow a rescan/undo to race with this batch.
                continue
            if state["result"]:
                state["result"] = None
                continue
            if state["help"] or state["details"]:
                if key in (curses.KEY_DOWN, ord("j")):
                    state["detailOffset"] += 1
                elif key in (curses.KEY_UP, ord("k")):
                    state["detailOffset"] = max(0, state["detailOffset"] - 1)
                elif key in (curses.KEY_NPAGE,):
                    state["detailOffset"] += 10
                elif key in (curses.KEY_PPAGE,):
                    state["detailOffset"] = max(0, state["detailOffset"] - 10)
                elif key in (27, 10, 13, ord("q"), ord("?")):
                    state["help"] = False
                    state["details"] = False
                continue
            if key in (ord("q"), ord("Q")):
                scanner.cancel.set()
                break
            if key in (curses.KEY_DOWN, ord("j")):
                state["cursor"] = min(len(rows) - 1, state["cursor"] + 1)
            elif key in (curses.KEY_UP, ord("k")):
                state["cursor"] = max(0, state["cursor"] - 1)
            elif key in (curses.KEY_NPAGE,):
                state["cursor"] = min(len(rows) - 1, state["cursor"] + page)
            elif key in (curses.KEY_PPAGE,):
                state["cursor"] = max(0, state["cursor"] - page)
            elif key in (curses.KEY_LEFT, ord("h"), curses.KEY_RIGHT, ord("l")):
                i = (
                    group_names.index(state["group"])
                    if state["group"] in group_names
                    else 0
                )
                i = (i + (-1 if key in (curses.KEY_LEFT, ord("h")) else 1)) % len(
                    group_names
                )
                state["group"] = group_names[i]
                state["cursor"] = 0
                state["offset"] = 0
            elif key in (ord("1"), ord("2"), ord("3")):
                state["mode"] = MODES[key - ord("1")]
            elif key in (10, 13):
                state["details"] = bool(selected)
                state["detailOffset"] = 0
            elif key == ord("?"):
                state["help"] = True
                state["detailOffset"] = 0
            elif key == ord("/"):
                state["query"] = prompt("Search: ")
                state["cursor"] = 0
                state["offset"] = 0
            elif key == 27:
                state["query"] = ""
                state["eligible"] = False
            elif key in (ord("a"), ord("A")):
                state["eligible"] = not state["eligible"]
                state["cursor"] = 0
                state["offset"] = 0
            elif key in (ord("s"), ord("S")):
                state["sort"] = {"size": "name", "name": "age", "age": "size"}[
                    state["sort"]
                ]
            elif key in (ord("c"), ord("C")):
                scanner.cancel.set()
                state["message"] = "Stopping after the current filesystem operation…"
            elif key in (ord("r"), ord("R")) and scanner.done:
                rescan(True)
                state["message"] = ""
            elif key == ord(" ") and selected:
                if selected.path in state["marked"]:
                    state["marked"].discard(selected.path)
                elif selected.selected:
                    state["marked"].add(selected.path)
                else:
                    state["message"] = (
                        "Only READY rows can be marked: " + selected.decision
                    )
                state["cursor"] = min(len(rows) - 1, state["cursor"] + 1)
            elif key in (ord("x"), ord("X")):
                if demo:
                    state["message"] = (
                        "Demo data: nothing to clean. Run without --demo."
                    )
                elif not scanner.done:
                    state["message"] = "Wait for the scan to finish before cleaning."
                elif state_dir is None:
                    state["message"] = "Cleaning unavailable: no state directory."
                else:
                    targets, skipped = cleanup_targets(
                        rows,
                        {
                            p
                            for p in state["marked"]
                            if any(f.path == p for f in findings)
                        },
                    )
                    if targets:
                        state["confirm"] = (targets, skipped)
                    else:
                        state["message"] = "Nothing to clean here: no READY rows" + (
                            " among the marked ones."
                            if state["marked"]
                            else " in this view."
                        )
            elif key in (ord("u"), ord("U")):
                if not state["lastBatch"]:
                    state["message"] = "Nothing to undo in this session."
                else:
                    restored, errors = undo_entries(state["lastBatch"], state_dir)
                    state["lastBatch"] = None
                    state["message"] = f"Restored {restored} item(s) from the Trash" + (
                        f"; {len(errors)} failed: " + errors[0] if errors else "."
                    )
                    if restored:
                        rescan(False)
            elif key in (ord("e"), ord("E")):
                target = Path(
                    export_path
                    or Path.home()
                    / f"soji-{time.strftime('%Y%m%d-%H%M%S')}.json"
                )
                try:
                    target.write_text(
                        json.dumps(scanner.report(state["mode"]), indent=2)
                    )
                    state["message"] = "Exported " + str(target)
                except OSError as e:
                    state["message"] = "Export failed: " + str(e)
        thread.join(timeout=1)

    curses.wrapper(main)
