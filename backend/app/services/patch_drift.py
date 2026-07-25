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

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.datetimes import utcnow
from app.models.minion import Minion
from app.models.patch import (
    MinionGroup, MinionGroupMember, Organisation, PatchPipeline, PatchPromotion,
    PatchPromotionResult, PatchSchedule, PipelineStage,
)

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


async def pipeline_drift(
    db: AsyncSession, pipeline_id: str, window: str,
) -> Optional[dict[str, Any]]:
    """Advisory drift for every stage of one pipeline.

    Six bulk reads regardless of fleet size — all joining happens in Python.
    Returns None when the pipeline does not exist.
    """
    pipeline = await db.get(PatchPipeline, pipeline_id)
    if pipeline is None:
        return None
    org = await db.get(Organisation, pipeline.org_id)

    # ── 1. stages ────────────────────────────────────────────────────────────
    stages = sorted(
        (await db.exec(
            select(PipelineStage).where(PipelineStage.pipeline_id == pipeline_id)
        )).all(),
        key=lambda s: s.order,
    )
    group_ids = [s.group_id for s in stages]

    # ── 2. groups + membership ───────────────────────────────────────────────
    groups: dict[str, MinionGroup] = {}
    members_by_group: dict[str, list[str]] = {}
    if group_ids:
        groups = {g.id: g for g in (await db.exec(
            select(MinionGroup).where(MinionGroup.id.in_(group_ids))
        )).all()}
        for m in (await db.exec(
            select(MinionGroupMember).where(MinionGroupMember.group_id.in_(group_ids))
        )).all():
            members_by_group.setdefault(m.group_id, []).append(m.minion_id)

    # ── 3. minions ───────────────────────────────────────────────────────────
    all_minion_ids = {mid for ids in members_by_group.values() for mid in ids}
    minions: dict[str, Minion] = {}
    if all_minion_ids:
        minions = {m.id: m for m in (await db.exec(
            select(Minion).where(Minion.id.in_(all_minion_ids))
        )).all()}

    # ── 4. promotions ────────────────────────────────────────────────────────
    promos = (await db.exec(
        select(PatchPromotion).where(
            PatchPromotion.pipeline_id == pipeline_id,
            PatchPromotion.status.in_(("done", "partial")),
        )
    )).all()
    promos_by_stage: dict[str, list[PatchPromotion]] = {}
    for p in promos:
        promos_by_stage.setdefault(p.to_stage_id, []).append(p)

    # ── 5. per-host results (only the ones that actually succeeded) ──────────
    results_by_promo: dict[str, list[PatchPromotionResult]] = {}
    if promos:
        for r in (await db.exec(
            select(PatchPromotionResult).where(
                PatchPromotionResult.promotion_id.in_([p.id for p in promos]),
                PatchPromotionResult.status == "done",
            )
        )).all():
            results_by_promo.setdefault(r.promotion_id, []).append(r)

    # ── 6. live schedules ────────────────────────────────────────────────────
    sched_by_stage = {s.stage_id: s for s in (await db.exec(
        select(PatchSchedule).where(
            PatchSchedule.pipeline_id == pipeline_id,
            PatchSchedule.superseded_at == None,  # noqa: E711
            PatchSchedule.enabled == True,        # noqa: E712
        )
    )).all()}

    # ── derivation ───────────────────────────────────────────────────────────
    def device_keys(stage_id: str) -> dict[str, set[str]]:
        """minion_id -> every advisory key that host has taken in this stage.

        All-time and deliberately unfiltered by window: the window bounds what a
        stage is measured against, never what it has done.
        """
        out: dict[str, set[str]] = {}
        for p in promos_by_stage.get(stage_id, []):
            for r in results_by_promo.get(p.id, []):
                out.setdefault(r.minion_id, set()).update(applied_keys(r.applied_advisories))
        return out

    def last_patched_per_device(stage_id: str) -> dict[str, datetime]:
        out: dict[str, datetime] = {}
        for p in promos_by_stage.get(stage_id, []):
            done_at = as_utc(p.completed_at)
            if done_at is None:
                continue
            for r in results_by_promo.get(p.id, []):
                if out.get(r.minion_id) is None or done_at > out[r.minion_id]:
                    out[r.minion_id] = done_at
        return out

    def reference_promotions(stage_id: str) -> list[PatchPromotion]:
        """The reference stage's promotions, narrowed by the window."""
        candidates = [p for p in promos_by_stage.get(stage_id, []) if p.completed_at]
        if window == "latest":
            return [max(candidates, key=lambda p: as_utc(p.completed_at))] if candidates else []
        cutoff = window_cutoff(window)
        if cutoff is None:
            return candidates
        return [p for p in candidates if as_utc(p.completed_at) >= cutoff]

    out_stages: list[dict[str, Any]] = []
    for idx, stage in enumerate(stages):
        ref_stage = stages[idx - 1] if idx > 0 else None

        ref_meta: dict[str, dict[str, Any]] = {}
        if ref_stage is not None:
            for p in reference_promotions(ref_stage.id):
                for r in results_by_promo.get(p.id, []):
                    ref_meta.update(advisory_meta(r.applied_advisories))
        ref_set = set(ref_meta)

        own = device_keys(stage.id)
        stage_set: set[str] = set().union(*own.values()) if own else set()
        last_seen = last_patched_per_device(stage.id)
        member_ids = members_by_group.get(stage.group_id, [])

        devices: list[dict[str, Any]] = []
        covered = 0
        for mid in member_ids:
            held = own.get(mid, set())
            if ref_set and ref_set <= held:
                covered += 1
            minion = minions.get(mid)
            devices.append({
                "minion_id": mid,
                "hostname": minion.hostname if minion else mid,
                "status": minion.status if minion else "unknown",
                "percent": percent(ref_set, held),
                "matched": len(ref_set & held),
                "last_patched": last_seen.get(mid),
                "missing_count": len(ref_set - held),
            })
        # Worst first: lowest coverage, then longest since a patch landed.
        devices.sort(key=lambda d: (
            d["percent"] if d["percent"] is not None else -1,
            d["last_patched"].timestamp() if d["last_patched"] else 0.0,
        ))

        # Every reference key at least one device lacks — not just keys no device
        # has. An advisory 9 of 10 boxes carry still leaves one box behind.
        missing = [
            {**ref_meta[key], "key": key,
             "affected_minion_ids": [m for m in member_ids if key not in own.get(m, set())]}
            for key in sorted(ref_set)
            if any(key not in own.get(m, set()) for m in member_ids)
        ]
        missing.sort(key=lambda x: (SEVERITY_ORDER.get(x["severity"], 9), x["key"]))

        stage_runs = [as_utc(p.completed_at) for p in promos_by_stage.get(stage.id, []) if p.completed_at]
        sched = sched_by_stage.get(stage.id)
        group = groups.get(stage.group_id)

        out_stages.append({
            "id": stage.id,
            "name": stage.name,
            "order": stage.order,
            "group_id": stage.group_id,
            "group_name": group.name if group else None,
            "reference_stage_id": ref_stage.id if ref_stage else None,
            "reference_stage_name": ref_stage.name if ref_stage else None,
            "percent": percent(ref_set, stage_set),
            "ref_total": len(ref_set),
            "matched": len(ref_set & stage_set),
            "devices_total": len(member_ids),
            "devices_covered": covered if ref_set else None,
            "last_patched": max(stage_runs) if stage_runs else None,
            "schedule": {
                "cron_expr": sched.cron_expr,
                "timezone": sched.timezone,
                "next_run_at": as_utc(sched.next_run_at),
            } if sched else None,
            "missing": missing,
            "devices": devices,
        })

    # Cadence: advisories landed per ISO week over the last 12 weeks. Describes
    # the pipeline's rhythm, so it ignores the comparison window entirely.
    floor = utcnow() - timedelta(weeks=12)
    weeks: dict[str, int] = {}
    for p in promos:
        done_at = as_utc(p.completed_at)
        if done_at is None or done_at < floor:
            continue
        monday = (done_at - timedelta(days=done_at.weekday())).date().isoformat()
        weeks[monday] = weeks.get(monday, 0) + sum(
            r.packages_count for r in results_by_promo.get(p.id, [])
        )

    return {
        "pipeline": {
            "id": pipeline.id,
            "name": pipeline.name,
            "org_name": org.name if org else None,
        },
        "window": window,
        "cadence": [{"week": w, "advisories": n} for w, n in sorted(weeks.items())],
        "stages": out_stages,
    }
