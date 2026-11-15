"""Reuse policy for persisted per-item judgments.

These functions decide whether a stored verdict still describes the measured
row; they never grant cleanup permission.
"""
from __future__ import annotations
import math
from .identity import digest


def fingerprint(f):
    return digest({'size':f.size,'newest':f.newest,'files':f.files,'identity':f.identity,'hint':f.hint_id,'rule':f.rule,'tier':f.tier if f.hint_id else 'unmatched'})


IDENTITY_FIELDS = ('device', 'inode', 'type', 'parentDevice', 'parentInode')


def content_fingerprint(f):
    """Measured content plus stable identity; mutable mtime/ctime are excluded.

    Identity is a safety boundary in addition to the three-field content
    policy. Return fresh dictionaries for snapshot storage.
    """
    identity = f.identity or {}
    return {'sizeBytes': f.size, 'newestChange': f.newest, 'fileCount': f.files,
            'identity': {key: identity[key] for key in IDENTITY_FIELDS if key in identity}}


def reusable_verdict(store, f, now, trigger='ordinary'):
    """Return a reusable claim; absence/negative claims return None.

    Raw records use the selection policy only after stable identity
    matches. Legacy stores/rows retain their strict hash and TTL behavior.
    Backlog deliberately checks size alone, ignoring age,
    levels, count and timestamp; this never bypasses local cleanup checks.
    """
    reader = getattr(store, 'verdict_record', None)
    if not callable(reader):
        return store.verdict(f.path, fingerprint(f), now)
    record = reader(f.path)
    if record is None:
        return None
    old = record.get('content')
    if old is None:
        return store.verdict(f.path, fingerprint(f), now)
    if not isinstance(old, dict):
        return None
    current = content_fingerprint(f)
    identity = current['identity']
    if (not all(identity.get(key) is not None for key in IDENTITY_FIELDS)
            or old.get('identity') != identity):
        return None
    claim = record.get('data')
    if not isinstance(claim, dict) or claim.get('path') != f.path:
        return None
    # Malformed persisted measurements fail closed instead of reaching numeric
    # policy comparisons. A nullable newestChange remains a valid measurement.
    def numeric(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    for content in (old, current):
        if not all(numeric(content.get(k)) and content[k] >= 0 for k in ('sizeBytes', 'fileCount')):
            return None
        newest = content.get('newestChange')
        if newest is not None and not numeric(newest):
            return None
    if trigger == 'backlog':
        tolerance = max(100_000_000, old['sizeBytes'] // 4)
        return claim if abs(current['sizeBytes'] - old['sizeBytes']) <= tolerance else None
    judged_at = record.get('judgedAt')
    if not numeric(judged_at):
        return None
    return None if judgement_needed(old, current, judged_at, now, claim) else claim


def judgement_lapsed(old, current, judged_at, now, *, keep=False):
    """Judgements.lapsed / AgentKeeps.lapsed; strict > boundaries."""
    if now - judged_at > 14 * 86400:
        return True
    if current is None:
        return False
    size = old['sizeBytes']
    tolerance = max(50_000_000, size // 10) if keep else max(100_000_000, size // 4)
    if abs(current['sizeBytes'] - size) > tolerance:
        return True
    if keep and current.get('newestChange') is not None:
        previous = old.get('newestChange')
        # Swift uses Date.distantPast when the old date is absent.
        return previous is None or current['newestChange'] - previous > 3600
    return False


def judgement_needed(old, current, judged_at, now, finding):
    """None means a cached negative judgment, not an absent cache record.

    Caller handles cache misses before invoking this policy. A non-keep claim
    without levels is retried. These functions do not grant cleanup permission.
    """
    if finding is None:
        return now - judged_at > 86400
    keep = finding.get('recommendation') == 'keep'
    if not keep and finding.get('levels') is None:
        return True
    return judgement_lapsed(old, current, judged_at, now, keep=keep)


