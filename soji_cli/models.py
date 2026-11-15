"""Stable measured nodes and wire-compatible findings below workflow services."""
from __future__ import annotations
import dataclasses
import sys
from .levels import normalize_mode,SESSION_FLOOR_SECONDS
from .policy import PolicyResult
from .safety import staged_ancestor

SESSION_HINTS=('claude-sessions','codex-sessions')

# slots (3.10+) keep large scans small; 3.9 (the macOS system Python) runs without.
@dataclasses.dataclass(**({'slots': True} if sys.version_info >= (3, 10) else {}))
class Node:
    path: str
    size: int = 0
    apparent: int = 0
    files: int = 0
    newest: float = 0
    own_newest: float = 0
    errors: int = 0
    secret: bool = False
    skipped: bool = False
    reason: str = ''
    directory: bool = True
    children: list[str] = dataclasses.field(default_factory=list)
    device: int = 0
    inode: int = 0
    own_size: int = 0
    own_apparent: int = 0
    own_errors: int = 0
    link_count: int = 0


@dataclasses.dataclass
class Finding:
    path: str
    size: int
    apparent: int
    files: int
    newest: float
    group: str
    label: str
    hint_id: str = ''
    tier: str = 'userData'
    comes_back: str = 'gone'
    rule: dict = dataclasses.field(default_factory=dict)
    smart_rule: str = ''
    list_only: bool = True
    holds: list[str] = dataclasses.field(default_factory=list)
    limitations: list[str] = dataclasses.field(default_factory=list)
    project_idle_hours: float | None = None
    matched_pattern: str = ''
    selected: bool = False
    decision: str = ''
    thresholds: dict = dataclasses.field(default_factory=dict)
    levels: dict | None = None
    catalog_min_hours: dict = dataclasses.field(default_factory=dict)
    last_activity: float | None = None
    mode_holds: dict = dataclasses.field(default_factory=dict)
    special_min_hours: float = 0
    evidence: list = dataclasses.field(default_factory=list)
    action: dict = dataclasses.field(default_factory=dict)
    identity: dict = dataclasses.field(default_factory=dict)
    source: str = 'hint'
    managed: bool = False
    recommendation: str = 'remove'
    confidence: float | None = None
    date_added: float | None = None
    default_holds: list[str] = dataclasses.field(default_factory=list)
    recent_activity_hours: float = 0
    rule_min_hours: dict = dataclasses.field(default_factory=dict)
    rule_project_min_hours: dict = dataclasses.field(default_factory=dict)
    rule_early_reason: str | None = None
    # Early outcome of a rule check (e.g. workspace missing -> careful). When
    # set, the rule's own age/rank gates were skipped; the level is combined
    # with the judged risk level.
    rule_level: str | None = None
    # Compound unit (Claude session): explicit member paths, each measured once.
    # Empty for ordinary single-path rows.
    members: list = dataclasses.field(default_factory=list)
    # Stable refusal code per hold text (e.g. active-use); text is for people.
    hold_codes: dict = dataclasses.field(default_factory=dict)

    def hold(self, text: str, code: str | None = None):
        self.holds.append(text)
        if code:self.hold_codes[text]=code

    def merge_holds(self, other):
        for text in other.holds:
            if text not in self.holds:self.holds.append(text)
        self.hold_codes.update({k:v for k,v in other.hold_codes.items() if k in self.holds})

    def decide(self, mode: str, now: float) -> tuple[bool, str]:
        return self.policy(mode, now).pair()

    def policy(self, mode: str, now: float) -> PolicyResult:
        mode=normalize_mode(mode)
        if staged_ancestor(self.path):return PolicyResult(False,'Sōji staged object requires manual review with `soji recover`; never cleaned automatically')
        if self.holds:
            code=next((self.hold_codes[h] for h in self.holds if h in self.hold_codes),None)
            return PolicyResult(False,'; '.join(dict.fromkeys(self.holds)),code)
        return PolicyResult(*self._gates(mode, now))

    def _gates(self, mode: str, now: float) -> tuple[bool, str]:
        if mode in self.mode_holds:return False,self.mode_holds[mode]
        if self.recommendation in ('keep','review'):return False,'Agent recommends '+self.recommendation
        if (self.list_only or self.tier in ('never','userData')) and not self.managed:
            return False, 'Listed for review; never automatically selected'
        from .levels import effective_minimum,judged_minimum,judgment_level,selected_at
        stamp=max(self.newest,self.date_added or self.newest)
        idle=(now-max(stamp,self.last_activity or stamp))/3600
        floor=max(300,self.recent_activity_hours*3600)
        if now-stamp<floor:return False,'Changed within the recent-activity window'
        # Sessions: a hard floor no downgrade or judgement can lower.
        if self.hint_id in SESSION_HINTS and mode in ('careful','balanced') and now-self.newest<SESSION_FLOOR_SECONDS:
            return False,f'Session changed {(now-self.newest)/3600:.1f} h ago; never cleaned within 24 h at {mode}'
        minimum=self.catalog_min_hours.get(mode,0)
        if idle<minimum:return False,f'Session catalog requires {minimum:g} h at {mode}; normal policy cannot be lowered by judgment'
        if self.levels is None and self.rule_level is None:
            if self.default_holds:return False,'; '.join(self.default_holds)
            minimum=self.rule_min_hours.get(mode,self.special_min_hours)
            if idle<minimum:return False,f'Idle {idle:.1f} h; rule needs {minimum:g} h at {mode}'
            project_min=self.rule_project_min_hours.get(mode)
            if project_min is not None:
                if self.project_idle_hours is None:return False,'Project inactivity not measurable'
                if self.project_idle_hours<project_min:return False,f'Project idle {self.project_idle_hours:.1f} h; rule needs {project_min:g} h at {mode}'
        if self.managed:
            # Session and Trash rows carry their own FindingPart levels, not
            # the general regenerable/costly risk policy.
            effective=judgment_level(self.levels or {},idle*3600)
        else:
            judged=judged_minimum(self.tier,self.recommendation,self.list_only,
                                  comes_back=self.comes_back)
            if self.levels is None and self.rule_level is not None:
                from .levels import combine_rule_level
                judged=combine_rule_level(self.rule_level,judged)
            effective=effective_minimum(judged,self.levels,self.tier,stamp,
                self.last_activity,now,self.recent_activity_hours,
                app_cache=self.group=='App caches')
        if not selected_at(effective,mode):
            return False,('Eligible from '+effective if effective else 'No eligible cleanup level at the current age/activity')
        return True,f'Idle {idle/24:.1f} d; eligible from {effective}'




