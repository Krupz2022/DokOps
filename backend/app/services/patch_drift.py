"""patch_drift.py — advisory-drift arithmetic between promotion stages.

Read-only derivation over promotion history: how much of what a reference stage
applied has a downstream stage also applied. No writes, no new tables.

Kept separate from patch_service.py, which is about *executing* patches. This
module is about reading what execution left behind.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.datetimes import utcnow

WINDOWS: tuple[str, ...] = ("latest", "30d", "90d", "all")

SEVERITY_ORDER: dict[str, int] = {
    "critical": 0, "high": 1, "medium": 2, "low": 3, "none": 4,
}


def advisory_key(entry: dict[str, Any]) -> str:
    """Stable identity for one applied advisory.

    dnf and zypper carry real advisory ids (RHSA-2024:1234); apt and winget do
    not, so fall back to the package name.

    ponytail: name-level fallback means dev going openssl->1.1.1b and qa going
    openssl->1.1.1c both count as "has openssl". Upgrade path is per-package-
    manager version comparison — only worth building if someone reports a false
    100%.
    """
    return entry.get("advisory_id") or entry.get("package_name") or ""


def _entries(raw: Optional[str]) -> list[dict[str, Any]]:
    """Parse a PatchPromotionResult.applied_advisories blob defensively.

    A malformed blob on one host must not take the whole dashboard down.
    """
    try:
        parsed = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [e for e in parsed if isinstance(e, dict)]


def applied_keys(raw: Optional[str]) -> set[str]:
    """Advisory keys recorded in one result row."""
    return {key for e in _entries(raw) if (key := advisory_key(e))}


def advisory_meta(raw: Optional[str]) -> dict[str, dict[str, Any]]:
    """Key -> display metadata, for rendering the missing-advisory list."""
    out: dict[str, dict[str, Any]] = {}
    for e in _entries(raw):
        key = advisory_key(e)
        if key:
            out[key] = {
                "advisory_id": e.get("advisory_id"),
                "package_name": e.get("package_name") or "",
                "severity": e.get("severity") or "none",
            }
    return out


def percent(ref: set[str], own: set[str]) -> Optional[int]:
    """Share of the reference set that `own` covers, 0-100.

    None when the reference set is empty. Having nothing to catch up with is not
    the same as being caught up — returning 100 would tell an operator prod is
    fine when dev has never run.
    """
    if not ref:
        return None
    return round(len(ref & own) / len(ref) * 100)


def window_cutoff(window: str) -> Optional[datetime]:
    """Datetime floor for a window. None for 'latest' and 'all', which are not
    time-boxed (see pipeline_drift for how those two are resolved)."""
    days = {"30d": 30, "90d": 90}.get(window)
    return utcnow() - timedelta(days=days) if days else None


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Force a timestamp aware.

    SQLite returns naive datetimes even from DateTime(timezone=True) columns,
    and comparing naive to aware raises TypeError. Postgres returns aware. This
    keeps the same code correct on both.
    """
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
