"""Policy values: measured facts, rule gates and decision outcomes.

A Finding stores these values in its persisted fields (plans and reports keep
their JSON shape); this module states how they combine and which outcome takes
precedence, so no caller depends on the order in which fields are cleared.
"""
from __future__ import annotations
import dataclasses

# Stable refusal/hold codes. Any refusal carrying a code starts the 24-hour
# cooldown; text is for people only.
ACTIVE_USE = 'active-use'
IDENTITY_CHANGED = 'identity-changed'
CONTENTS_CHANGED = 'contents-changed'
MEMBERS_CHANGED = 'members-changed'


@dataclasses.dataclass(frozen=True)
class Measurement:
    """What a walk measured for one cleanup unit."""
    path: str
    size: int
    files: int
    newest: float

    @classmethod
    def of(cls, row):
        get = row.get if isinstance(row, dict) else lambda k: getattr(row, k)
        return cls(get('path'), get('size'), get('files'), get('newest'))

    def same_contents(self, other) -> bool:
        return (self.size, self.newest, self.files) == (other.size, other.newest, other.files)


@dataclasses.dataclass(frozen=True)
class PolicyResult:
    """Outcome of one mode decision; `code` is set when a hold refuses for live use."""
    selected: bool
    reason: str
    code: str | None = None

    def pair(self):
        return self.selected, self.reason


@dataclasses.dataclass(frozen=True)
class RuleGates:
    """Age, project-age and retention gates a catalog rule imposes per mode.

    Precedence: an early rule outcome (workspace missing, newer device build)
    replaces the rule's own gates with a fixed level; it never removes holds.
    """
    min_hours: dict = dataclasses.field(default_factory=dict)
    project_min_hours: dict = dataclasses.field(default_factory=dict)
    mode_holds: dict = dataclasses.field(default_factory=dict)
    special_min_hours: float = 0
    early_reason: str | None = None
    level: str | None = None

    @classmethod
    def from_thresholds(cls, thresholds):
        return cls({m: v['minIdleDays'] * 24 for m, v in thresholds.items() if 'minIdleDays' in v},
                   {m: v['minProjectIdleDays'] * 24 for m, v in thresholds.items() if 'minProjectIdleDays' in v})

    def retain(self, mode, reason):
        return dataclasses.replace(self, mode_holds={**self.mode_holds, mode: reason})

    def early(self, reason, level='careful'):
        return RuleGates(early_reason=reason, level=level, special_min_hours=self.special_min_hours)

    def explicit_levels(self, reason):
        """The rule supplies explicit levels; only the special age floor is dropped."""
        return dataclasses.replace(self, special_min_hours=0, early_reason=reason)

    def apply_to(self, f):
        f.rule_min_hours = dict(self.min_hours)
        f.rule_project_min_hours = dict(self.project_min_hours)
        f.mode_holds = dict(self.mode_holds)
        f.special_min_hours = self.special_min_hours
        f.rule_early_reason = self.early_reason
        f.rule_level = self.level
        return f
