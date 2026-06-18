"""patching.py — compliance, patch apply, pipeline management, schedule CRUD."""
from __future__ import annotations
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.datetimes import utcnow
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_async_db, get_current_user, require_god_mode
from app.models.patch import (
    MinionGroup, MinionGroupMember, MinionPatch, PatchAlertEvent, PatchPipeline,
    PatchPromotion, PatchPromotionResult, PatchSchedule, PipelineStage,
)
from app.models.minion import Minion
from app.models.user import User

router = APIRouter()


# ── Compliance ───────────────────────────────────────────────────────────────

@router.get("/compliance")
async def compliance_by_device(
    org_id: Optional[str] = None,
    group_id: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    """Per-device patch summary. Filterable by org or group."""
    minion_ids: Optional[list[str]] = None
    if group_id:
        minion_ids = [m.minion_id for m in (await db.exec(
            select(MinionGroupMember).where(MinionGroupMember.group_id == group_id)
        )).all()]
    elif org_id:
        groups = (await db.exec(select(MinionGroup).where(MinionGroup.org_id == org_id))).all()
        minion_ids = [m.minion_id for g in groups for m in (await db.exec(
            select(MinionGroupMember).where(MinionGroupMember.group_id == g.id)
        )).all()]

    q = select(Minion)
    if minion_ids is not None:
        q = q.where(Minion.id.in_(minion_ids))
    minions = (await db.exec(q)).all()

    result = []
    for m in minions:
        patches = (await db.exec(select(MinionPatch).where(MinionPatch.minion_id == m.id))).all()
        critical = sum(1 for p in patches if p.severity == "critical")
        high = sum(1 for p in patches if p.severity == "high")
        last_scan = max((p.scanned_at for p in patches), default=None) or m.last_patch_scan
        try:
            grains = json.loads(m.grains or "{}")
            os_str = grains.get("os", "").lower()
        except Exception:
            os_str = ""
        os_family = "windows" if "windows" in os_str else "linux" if os_str else "unknown"
        result.append({
            "minion_id": m.id,
            "hostname": m.hostname,
            "status": m.status,
            "os_family": os_family,
            "total_patches": len({p.advisory_id or f"{p.package_name}-{p.available_version}" for p in patches}),
            "critical": critical,
            "high": high,
            "last_scanned": last_scan,
        })
    return result


@router.get("/by-device/{minion_id}")
async def patches_for_device(
    minion_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    """All patches for a single device."""
    patches = (await db.exec(select(MinionPatch).where(MinionPatch.minion_id == minion_id))).all()
    return [
        {
            "package_name": p.package_name,
            "installed_version": p.installed_version,
            "available_version": p.available_version,
            "advisory_id": p.advisory_id,
            "advisory_type": p.advisory_type,
            "severity": p.severity,
            "cve_ids": json.loads(p.cve_ids or "[]"),
            "scanned_at": p.scanned_at,
        }
        for p in sorted(patches, key=lambda x: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3, "none": 4}.get(x.severity, 5)
        ))
    ]


@router.get("/by-cve")
async def compliance_by_cve(
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    """Aggregate view: one row per advisory/CVE with affected device count.
    Only includes patches for minions that still exist (no orphaned rows)."""
    existing_minion_ids = {m.id for m in (await db.exec(select(Minion))).all()}
    all_patches = (await db.exec(select(MinionPatch))).all()
    advisory_map: dict[str, dict] = {}
    for p in all_patches:
        if p.minion_id not in existing_minion_ids:
            continue
        key = p.advisory_id or f"{p.package_name}-{p.available_version}"
        if key not in advisory_map:
            advisory_map[key] = {
                "advisory_id": p.advisory_id,
                "package_name": p.package_name,
                "severity": p.severity,
                "advisory_type": p.advisory_type,
                "cve_ids": json.loads(p.cve_ids or "[]"),
                "affected_minion_ids": [],
            }
        if p.minion_id not in advisory_map[key]["affected_minion_ids"]:
            advisory_map[key]["affected_minion_ids"].append(p.minion_id)
    return list(advisory_map.values())


@router.get("/minions/{minion_id}/patches")
async def get_minion_patches(
    minion_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    return (await db.exec(select(MinionPatch).where(MinionPatch.minion_id == minion_id))).all()


# ── Patch Apply ──────────────────────────────────────────────────────────────

class ApplyRequest(BaseModel):
    scope: str  # security / all / custom
    custom_packages: Optional[List[str]] = None
    reboot_after: bool = False


@router.post("/groups/{group_id}/patches/apply")
async def apply_group_patches(
    group_id: str,
    body: ApplyRequest,
    current_user: User = Depends(require_god_mode),
):
    from app.services.patch_service import apply_patches
    custom = json.dumps(body.custom_packages) if body.custom_packages else None
    result = await apply_patches(
        group_id=group_id,
        scope=body.scope,
        custom_packages=custom,
        actor=current_user.username,
        auto_reboot=body.reboot_after,
    )
    return result


# ── Pipelines ────────────────────────────────────────────────────────────────

class PipelineCreate(BaseModel):
    name: str
    auto_promote: bool = False


class StageCreate(BaseModel):
    name: str
    group_id: str
    order: int


class StageUpdate(BaseModel):
    name: Optional[str] = None
    group_id: Optional[str] = None


@router.get("/organisations/{org_id}/pipelines")
async def list_pipelines(org_id: str, db: AsyncSession = Depends(get_async_db), _: User = Depends(get_current_user)):
    pipelines = (await db.exec(select(PatchPipeline).where(PatchPipeline.org_id == org_id))).all()
    result = []
    for p in pipelines:
        stages = (await db.exec(
            select(PipelineStage).where(PipelineStage.pipeline_id == p.id)
            .order_by(PipelineStage.order)
        )).all()
        result.append({**p.model_dump(), "stages": [s.model_dump() for s in stages]})
    return result


@router.delete("/pipelines/{pipeline_id}")
async def delete_pipeline(
    pipeline_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(require_god_mode),
):
    pipeline = await db.get(PatchPipeline, pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    # cascade delete stages, promotions, schedules
    for stage in (await db.exec(select(PipelineStage).where(PipelineStage.pipeline_id == pipeline_id))).all():
        await db.delete(stage)
    for promo in (await db.exec(select(PatchPromotion).where(PatchPromotion.pipeline_id == pipeline_id))).all():
        await db.delete(promo)
    for sched in (await db.exec(select(PatchSchedule).where(PatchSchedule.pipeline_id == pipeline_id))).all():
        await db.delete(sched)
    await db.delete(pipeline)
    await db.commit()
    return {"deleted": True}


@router.post("/organisations/{org_id}/pipelines")
async def create_pipeline(
    org_id: str, body: PipelineCreate,
    db: AsyncSession = Depends(get_async_db), _: User = Depends(require_god_mode),
):
    p = PatchPipeline(org_id=org_id, name=body.name, auto_promote=body.auto_promote)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@router.post("/pipelines/{pipeline_id}/stages")
async def add_pipeline_stage(
    pipeline_id: str, body: StageCreate,
    db: AsyncSession = Depends(get_async_db), _: User = Depends(require_god_mode),
):
    stage = PipelineStage(
        pipeline_id=pipeline_id, name=body.name,
        group_id=body.group_id, order=body.order,
    )
    db.add(stage)
    await db.commit()
    await db.refresh(stage)
    return stage


@router.patch("/pipelines/{pipeline_id}/stages/{stage_id}")
async def update_pipeline_stage(
    pipeline_id: str,
    stage_id: str,
    body: StageUpdate,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(require_god_mode),
):
    stage = await db.get(PipelineStage, stage_id)
    if not stage or stage.pipeline_id != pipeline_id:
        raise HTTPException(status_code=404, detail="Stage not found")
    if body.name is not None:
        stage.name = body.name
    if body.group_id is not None:
        stage.group_id = body.group_id
    db.add(stage)
    await db.commit()
    await db.refresh(stage)
    return stage


@router.delete("/pipelines/{pipeline_id}/stages/{stage_id}")
async def delete_pipeline_stage(
    pipeline_id: str,
    stage_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(require_god_mode),
):
    stage = await db.get(PipelineStage, stage_id)
    if not stage or stage.pipeline_id != pipeline_id:
        raise HTTPException(status_code=404, detail="Stage not found")
    await db.delete(stage)
    await db.commit()
    return {"deleted": True}


@router.post("/pipelines/{pipeline_id}/stages/{stage_id}/apply")
async def apply_to_stage(
    pipeline_id: str,
    stage_id: str,
    body: ApplyRequest,
    current_user: User = Depends(require_god_mode),
    db: AsyncSession = Depends(get_async_db),
):
    """Initial patch application to a pipeline stage (creates first PatchPromotion for that stage)."""
    from app.services.patch_service import apply_patches

    stage = await db.get(PipelineStage, stage_id)
    if not stage or stage.pipeline_id != pipeline_id:
        raise HTTPException(status_code=404, detail="Stage not found")

    custom = json.dumps(body.custom_packages) if body.custom_packages else None

    promo = PatchPromotion(
        pipeline_id=pipeline_id,
        from_stage_id=None,
        to_stage_id=stage_id,
        patch_scope=body.scope,
        custom_packages=custom,
        triggered_by=current_user.username,
        status="running",
    )
    db.add(promo)
    await db.commit()
    await db.refresh(promo)

    result = await apply_patches(
        group_id=stage.group_id,
        scope=body.scope,
        custom_packages=custom,
        actor=current_user.username,
        promotion_id=promo.id,
        auto_reboot=body.reboot_after,
    )
    return {"promotion_id": promo.id, **result}


@router.post("/pipelines/{pipeline_id}/stages/{stage_id}/promote")
async def promote_stage(
    pipeline_id: str,
    stage_id: str,
    current_user: User = Depends(require_god_mode),
    db: AsyncSession = Depends(get_async_db),
):
    """Promote the frozen package list from stage_id to the next stage in the pipeline.
    Reads packages from the source stage's latest successful PatchPromotion."""
    from app.services.patch_service import apply_patches

    current_stage = await db.get(PipelineStage, stage_id)
    if not current_stage or current_stage.pipeline_id != pipeline_id:
        raise HTTPException(status_code=404, detail="Stage not found")

    next_stage = (await db.exec(
        select(PipelineStage)
        .where(PipelineStage.pipeline_id == pipeline_id, PipelineStage.order > current_stage.order)
        .order_by(PipelineStage.order)
    )).first()
    if not next_stage:
        raise HTTPException(status_code=400, detail="No next stage to promote to")

    # Read frozen package list from source stage's latest done promotion
    source_promo = (await db.exec(
        select(PatchPromotion)
        .where(PatchPromotion.to_stage_id == stage_id, PatchPromotion.status == "done")
        .order_by(PatchPromotion.triggered_at.desc())
    )).first()
    if not source_promo:
        raise HTTPException(
            status_code=400,
            detail="Source stage has no successful promotion to promote from. Apply patches to this stage first.",
        )

    promo = PatchPromotion(
        pipeline_id=pipeline_id,
        from_stage_id=stage_id,
        to_stage_id=next_stage.id,
        patch_scope="custom",
        custom_packages=source_promo.custom_packages,
        triggered_by=current_user.username,
        status="running",
    )
    db.add(promo)
    await db.commit()
    await db.refresh(promo)

    result = await apply_patches(
        group_id=next_stage.group_id,
        scope="custom",
        custom_packages=source_promo.custom_packages,
        actor=current_user.username,
        promotion_id=promo.id,
    )
    return {"promotion_id": promo.id, "promoted_to_stage": next_stage.id, **result}


@router.get("/pipelines/{pipeline_id}/promotions")
async def list_promotions(
    pipeline_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    return (await db.exec(
        select(PatchPromotion).where(PatchPromotion.pipeline_id == pipeline_id)
        .order_by(PatchPromotion.triggered_at.desc())
    )).all()


@router.get("/promotions/{promotion_id}/results")
async def get_promotion_results(
    promotion_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    """Per-minion results for a single promotion including advisory snapshot."""
    results = (await db.exec(
        select(PatchPromotionResult)
        .where(PatchPromotionResult.promotion_id == promotion_id)
        .order_by(PatchPromotionResult.created_at)
    )).all()

    minion_ids = list({r.minion_id for r in results})
    from app.models.minion import Minion
    minions = (await db.exec(select(Minion).where(Minion.id.in_(minion_ids)))).all()  # type: ignore[attr-defined]
    hostname_map = {m.id: m.hostname for m in minions}

    return [
        {
            **r.model_dump(),
            "hostname": hostname_map.get(r.minion_id, r.minion_id[:8]),
            "applied_advisories": json.loads(r.applied_advisories or "[]"),
        }
        for r in results
    ]


# ── Schedules ────────────────────────────────────────────────────────────────

class ScheduleCreate(BaseModel):
    pipeline_id: str
    stage_id: str
    cron_expr: str
    timezone: str = "UTC"
    patch_scope: str
    custom_packages: Optional[List[str]] = None
    promote_from_previous: bool = False
    auto_reboot: bool = False
    week_of_month: Optional[int] = None  # 1-4; None = every week
    notifications: Dict[str, Any] = PydanticField(default_factory=dict)
    ai_beautify: bool = False


class ScheduleUpdate(BaseModel):
    cron_expr: Optional[str] = None
    timezone: Optional[str] = None
    patch_scope: Optional[str] = None
    custom_packages: Optional[List[str]] = None
    promote_from_previous: Optional[bool] = None
    auto_reboot: Optional[bool] = None
    week_of_month: Optional[int] = None
    notifications: Optional[Dict[str, Any]] = None
    ai_beautify: Optional[bool] = None
    enabled: Optional[bool] = None


@router.get("/schedules/")
async def list_schedules(db: AsyncSession = Depends(get_async_db), _: User = Depends(get_current_user)):
    return (await db.exec(select(PatchSchedule))).all()


@router.post("/schedules/")
async def create_schedule(
    body: ScheduleCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_god_mode),
):
    from app.main import scheduler
    from app.services.patch_service import _register_schedule
    from apscheduler.triggers.cron import CronTrigger as _CronTrigger

    # Fix 1: Validate pipeline/stage exist before creating the schedule
    stage = await db.get(PipelineStage, body.stage_id)
    if not stage or stage.pipeline_id != body.pipeline_id:
        raise HTTPException(status_code=404, detail="Stage not found in pipeline")

    # Fix 2: Validate cron expression before DB commit
    try:
        _CronTrigger.from_crontab(body.cron_expr, timezone=body.timezone)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {exc}")

    sched = PatchSchedule(
        pipeline_id=body.pipeline_id,
        stage_id=body.stage_id,
        cron_expr=body.cron_expr,
        timezone=body.timezone,
        patch_scope=body.patch_scope,
        custom_packages=json.dumps(body.custom_packages) if body.custom_packages else None,
        promote_from_previous=body.promote_from_previous,
        auto_reboot=body.auto_reboot,
        week_of_month=body.week_of_month,
        notifications=body.notifications,
        ai_beautify=body.ai_beautify,
        created_by=current_user.username,
    )
    db.add(sched)
    await db.commit()
    await db.refresh(sched)

    # Fix 3: Wrap scheduler registration — rollback on failure
    try:
        _register_schedule(scheduler, sched)
    except Exception as exc:
        await db.delete(sched)
        await db.commit()
        raise HTTPException(status_code=400, detail=f"Failed to register schedule: {exc}")

    return sched


@router.patch("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    body: ScheduleUpdate,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(require_god_mode),
):
    from app.main import scheduler
    from app.services.patch_service import _register_schedule

    sched = await db.get(PatchSchedule, schedule_id)
    if not sched:
        raise HTTPException(status_code=404)

    if body.cron_expr is not None:
        from apscheduler.triggers.cron import CronTrigger as _CT
        try:
            _CT.from_crontab(body.cron_expr, timezone=body.timezone or sched.timezone)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid cron expression: {exc}")
        sched.cron_expr = body.cron_expr
    if body.timezone is not None:
        sched.timezone = body.timezone
    if body.patch_scope is not None:
        sched.patch_scope = body.patch_scope
    if body.custom_packages is not None:
        sched.custom_packages = json.dumps(body.custom_packages)
    if body.promote_from_previous is not None:
        sched.promote_from_previous = body.promote_from_previous
    if body.auto_reboot is not None:
        sched.auto_reboot = body.auto_reboot
    if body.week_of_month is not None:
        sched.week_of_month = body.week_of_month
    if body.notifications is not None:
        sched.notifications = body.notifications
    if body.ai_beautify is not None:
        sched.ai_beautify = body.ai_beautify
    if body.enabled is not None:
        sched.enabled = body.enabled

    db.add(sched)
    await db.commit()

    job_id = f"patch_sched_{schedule_id}"
    if sched.enabled:
        _register_schedule(scheduler, sched)
    else:
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass

    return sched


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(require_god_mode),
):
    from app.main import scheduler

    sched = await db.get(PatchSchedule, schedule_id)
    if not sched:
        raise HTTPException(status_code=404)
    await db.delete(sched)
    await db.commit()
    try:
        scheduler.remove_job(f"patch_sched_{schedule_id}")
    except Exception:
        pass
    return {"deleted": True}


# ── Promotion partial-failure resolution ─────────────────────────────────────

class ExcludeRequest(BaseModel):
    reason: str


@router.post("/promotions/{promo_id}/retry")
async def retry_failed_minions(
    promo_id: str,
    current_user: User = Depends(require_god_mode),
    db: AsyncSession = Depends(get_async_db),
):
    """Re-dispatch patch jobs only to minions that failed in a partial promotion."""
    from app.services.minion_service import manager
    from app.models.minion import Minion as _Minion
    from app.services.patch_service import _build_patch_cmd

    promo = await db.get(PatchPromotion, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Promotion not found")
    if promo.status != "partial":
        raise HTTPException(status_code=400, detail=f"Promotion is {promo.status}, not partial")

    failed_ids: list[str] = json.loads(promo.failed_minions or "[]")
    if not failed_ids:
        raise HTTPException(status_code=400, detail="No failed minions to retry")

    results = []
    for minion_id in failed_ids:
        m = await db.get(_Minion, minion_id)
        if not m or m.status != "active":
            results.append({"minion_id": minion_id, "exit_code": -1, "status": "failed", "error": "not connected"})
            continue
        grains = json.loads(m.grains or "{}")
        os_str = grains.get("os", "").lower()
        if any(x in os_str for x in ("rhel", "centos", "rocky", "fedora", "alma", "ol", "anolis")):
            pkg_mgr = "dnf"
        elif any(x in os_str for x in ("suse", "sles", "opensuse")):
            pkg_mgr = "zypper"
        else:
            pkg_mgr = "apt"
        cmd = _build_patch_cmd(pkg_mgr, promo.patch_scope, promo.custom_packages)
        try:
            result = await manager.dispatch_job(minion_id, cmd, actor=current_user.username, timeout=300, god_mode=True)
            status = "done" if result["exit_code"] == 0 else "failed"
            results.append({"minion_id": minion_id, "exit_code": result["exit_code"], "status": status})
        except Exception as e:
            results.append({"minion_id": minion_id, "exit_code": -1, "status": "failed", "error": str(e)})

    still_failed = [r["minion_id"] for r in results if r["status"] == "failed"]
    if not still_failed:
        promo.status = "done"
        promo.failed_minions = None
    else:
        promo.status = "failed"
        promo.failed_minions = json.dumps(still_failed)
    promo.completed_at = utcnow()
    db.add(promo)
    await db.commit()

    return {"results": results, "promo_status": promo.status}


@router.post("/promotions/{promo_id}/exclude/{minion_id}")
async def exclude_minion(
    promo_id: str,
    minion_id: str,
    body: ExcludeRequest,
    current_user: User = Depends(require_god_mode),
    db: AsyncSession = Depends(get_async_db),
):
    """Exclude a failing minion from a partial promotion. If it was the last failing minion, status → done."""
    if not body.reason.strip():
        raise HTTPException(status_code=400, detail="Reason is required")

    promo = await db.get(PatchPromotion, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Promotion not found")
    if promo.status != "partial":
        raise HTTPException(status_code=400, detail=f"Promotion is {promo.status}, not partial")

    failed_ids: list[str] = json.loads(promo.failed_minions or "[]")
    if minion_id not in failed_ids:
        raise HTTPException(status_code=400, detail="Minion is not in the failed list")

    excluded: list[dict] = json.loads(promo.excluded_minions or "[]")
    excluded.append({
        "id": minion_id,
        "reason": body.reason.strip(),
        "excluded_by": current_user.username,
        "at": utcnow().isoformat(),
    })
    failed_ids.remove(minion_id)

    promo.excluded_minions = json.dumps(excluded)
    promo.failed_minions = json.dumps(failed_ids) if failed_ids else None
    if not failed_ids:
        promo.status = "done"
        promo.completed_at = utcnow()

    db.add(promo)
    await db.commit()
    return promo


# ── Alert events ─────────────────────────────────────────────────────────────

@router.get("/alerts/")
async def list_alerts(
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    """List all unacknowledged PatchAlertEvents."""
    return (await db.exec(
        select(PatchAlertEvent).where(PatchAlertEvent.acknowledged == False)
        .order_by(PatchAlertEvent.fired_at.desc())
    )).all()


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    current_user: User = Depends(require_god_mode),
    db: AsyncSession = Depends(get_async_db),
):
    alert = await db.get(PatchAlertEvent, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = True
    alert.acknowledged_by = current_user.username
    alert.acknowledged_at = utcnow()
    db.add(alert)
    await db.commit()
    return alert
