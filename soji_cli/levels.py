"""Pure translations of four recovered ARM64 cleanup-level functions.

Evidence: research/mode-instructions.json. These functions intentionally separate
level policy from filesystem/activity guards and UI selection. Units are seconds
for timestamps/idle and hours for the values in a LevelJudgement.
"""
from __future__ import annotations
import math
from collections.abc import Mapping

LEVELS = ("careful", "balanced", "aggressive")


def _finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def level_for_idle(since: float | None, now: float, recent_activity_hours: float = 0) -> str | None:
    """SōjiModel.CleanupLevel.forIdle, ARM64 0x1004601b4."""
    if since is None or not _finite(since) or not _finite(now):
        return None
    if not _finite(recent_activity_hours):
        return None
    idle = now - since
    configured = max(300.0, recent_activity_hours * 3600.0) if recent_activity_hours > 0 else 0.0
    for name, baseline in zip(LEVELS, (604800.0, 86400.0, 3600.0)):
        if idle >= max(baseline, configured):
            return name
    return None


def judgment_level(judgment: Mapping, idle_seconds: float) -> str | None:
    """SōjiModel.LevelJudgement.level(idle:), ARM64 0x100460e04.

    The first eligible level wins. Eligibility at Careful therefore includes
    Balanced/Aggressive even if those keys are absent or nonmonotonic.
    """
    if not _finite(idle_seconds):
        return None
    for name in LEVELS:
        hours = judgment.get(name)
        if hours is not None and _finite(hours) and idle_seconds >= max(0.0, float(hours)) * 3600:
            return name
    return None


def judged_minimum(tier: str, recommendation: str, list_only: bool,
                   claimed: str | None = None, comes_back: str | None = None) -> str | None:
    """CleanupLevels.judged specialization, ARM64 0x100663310."""
    if recommendation not in ("remove", "trash") or list_only:
        return None
    if tier not in ("regenerable", "costly") or comes_back == "gone":
        return None
    if tier == "costly":
        return "aggressive"
    base = 1 if comes_back == "downloads" else 0
    claim = LEVELS.index(claimed) if claimed in LEVELS else base
    return LEVELS[max(base, claim)]


def effective_minimum(judged: str | None, judgment: Mapping | None, tier: str,
                      newest_change: float | None, last_activity: float | None,
                      now: float, recent_activity_hours: float = 0,
                      app_cache: bool = False) -> str | None:
    """CleanupLevels.effective, ARM64 0x10066130c.

    Without a per-item judgment, supplied agent activity must be at least a day
    old. With a judgment, activity contributes to that judgment's idle time.
    The minimum newest-change floor applies before either path.
    """
    if newest_change is None or not _finite(newest_change) or not _finite(now):
        return None
    if not _finite(recent_activity_hours):
        return None
    floor = max(300.0, recent_activity_hours * 3600.0) if recent_activity_hours > 0 else 300.0
    if now - newest_change < floor or judged not in LEVELS:
        return None
    if last_activity is not None and not _finite(last_activity):
        return None
    idle_since = max(newest_change, last_activity if last_activity is not None else newest_change)
    if judgment is not None:
        return judgment_level(judgment, now - idle_since)
    if last_activity is not None and now - last_activity < max(86400.0, floor):
        return None
    age_level = level_for_idle(idle_since, now, recent_activity_hours)
    if age_level is None:
        if not (app_cache and tier == "regenerable"):
            return None
        age_level = "aggressive"
    elif tier == "costly" and age_level == "aggressive":
        return None
    return LEVELS[max(LEVELS.index(judged), LEVELS.index(age_level))]


def selected_at(effective: str | None, requested: str) -> bool:
    if requested not in LEVELS:
        raise ValueError("Unknown cleanup level: " + str(requested))
    return effective in LEVELS and LEVELS.index(effective) <= LEVELS.index(requested)
