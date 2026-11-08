"""Pure scheduling policy; callers own timers, consent and run accounting.

This module never schedules or launches an agent by itself.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime

MAX_PROCESS_RUNS_PER_HOUR = 2
VERIFY_LANES = 4
WATCH_INTERVAL = 15
IDLE_WATCH_INTERVAL = 60
LISTED_PER_RUN = 40
CATALOG_MINIMUM_BYTES = 20_000_000
FRESHNESS = {
    'runtimes': 300, 'runtimes_interactive': 30, 'versions': 1800,
    'prepare': 60, 'store_verified': 300, 'disk_findings': 21600,
    'process_start_delay': 60, 'harmless_verdict': 14 * 86400,
    'catalog_check': 900, 'closed_catalog_check': 3600,
    'closed_reverify': 600, 'closed_catalog': 60, 'open_catalog': 10,
    'sessions_changed': 60, 'closed_sessions_changed': 600,
    'sessions': 600, 'quit_verdict': 3600, 'process_plan': 600,
    'temp': 1800, 'outside_sizes': 21600,
}

@dataclass(frozen=True)
class Backlog:
    unjudged_count: int = 0
    unjudged_bytes: int = 0
    stale_count: int = 0

@dataclass(frozen=True)
class Moment:
    now: float
    last_change: float | None = None
    last_backlog_run: float | None = None
    last_daily_run: float | None = None
    idle_seconds: float = 0
    on_battery: bool = False
    battery_percent: float | None = None
    pause_below_percent: float | None = None

@dataclass(frozen=True)
class AnalysisCadence:
    backlog_items: int = 10
    backlog_bytes: int = 1_000_000_000
    quiet_for: float = 180
    backlog_every: float = 3600
    idle_for: float = 600
    first_scan_batches: int = 6
    daily_batches: int = 3
    check_every: float = 60
    backoff: tuple[float, ...] = (3600, 14400, 86400)

    def due(self, backlog: Backlog, at: Moment) -> str | None:
        quiet = at.last_change is None or at.now - at.last_change >= self.quiet_for
        large = backlog.unjudged_count >= self.backlog_items or backlog.unjudged_bytes >= self.backlog_bytes
        elapsed = at.last_backlog_run is None or at.now - at.last_backlog_run >= self.backlog_every
        # The executable returns backlog before checking daily idle/power gates.
        if quiet and large and elapsed:
            return 'backlog'
        same_day = at.last_daily_run is not None and datetime.fromtimestamp(at.now).date() == datetime.fromtimestamp(at.last_daily_run).date()
        if same_day or backlog.unjudged_count + backlog.stale_count < 1 or at.idle_seconds < self.idle_for:
            return None
        if at.on_battery and at.pause_below_percent is not None:
            percent = at.battery_percent if at.battery_percent is not None else 0
            if percent <= at.pause_below_percent:
                return None
        return 'daily'
