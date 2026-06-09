"""patch_service.py — patch scan ingestion, apply logic, APScheduler bootstrap."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.core.db import engine
from app.models.minion import Minion
from app.models.patch import (
    MinionGroup, MinionGroupMember, MinionPatch, Organisation,
    PatchPipeline, PatchPromotion, PatchPromotionResult, PatchSchedule, PipelineStage,
)
from app.models.minion import Minion

_log = logging.getLogger(__name__)


def ps_quote(s: str) -> str:
    """Safely quote a string for a PowerShell single-quoted string.
    Doubles internal single quotes so they are literal, preventing $() expansion."""
    return "'" + s.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Onboarding auto-provisioning
# ---------------------------------------------------------------------------

def assign_minion_to_group(minion_id: str, org_id: str, group_id: str) -> None:
    """Move minion to group_id, removing any prior membership within the same org (one group per org)."""
    with Session(engine) as db:
        # Remove all existing memberships in this org
        all_group_ids = [
            g.id for g in db.exec(select(MinionGroup).where(MinionGroup.org_id == org_id)).all()
        ]
        for old in db.exec(
            select(MinionGroupMember)
            .where(MinionGroupMember.minion_id == minion_id)
            .where(MinionGroupMember.group_id.in_(all_group_ids))  # type: ignore[attr-defined]
        ).all():
            db.delete(old)
        db.add(MinionGroupMember(group_id=group_id, minion_id=minion_id))
        db.commit()
    _log.info("Assigned %s → group %s (org %s)", minion_id, group_id, org_id)


def find_existing_membership(minion_id: str, org_name: str, env_name: str) -> None:
    """Assign minion to an existing org/group only — never creates new orgs or groups.
    Prevents untrusted minion-supplied grains from polluting the org/group hierarchy."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", org_name.lower()).strip("-") or "default"
    with Session(engine) as db:
        org = db.exec(select(Organisation).where(Organisation.slug == slug)).first()
        if not org:
            _log.warning("Minion %s claimed org %r but it does not exist — skipping", minion_id, org_name)
            return
        group = db.exec(
            select(MinionGroup)
            .where(MinionGroup.org_id == org.id)
            .where(MinionGroup.name == env_name)
        ).first()
        if not group:
            _log.warning("Minion %s claimed group %r but it does not exist — skipping", minion_id, env_name)
            return
        org_id, group_id = org.id, group.id
    assign_minion_to_group(minion_id, org_id, group_id)
    _log.info("Auto-assigned %s → %s / %s", minion_id, org_name, env_name)


def find_or_create_membership(minion_id: str, org_name: str, env_name: str) -> None:
    """Idempotently provision org → group, then assign minion (one group per org)."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", org_name.lower()).strip("-") or "default"

    with Session(engine) as db:
        org = db.exec(select(Organisation).where(Organisation.slug == slug)).first()
        if not org:
            org = Organisation(name=org_name, slug=slug)
            db.add(org)
            db.flush()

        group = db.exec(
            select(MinionGroup)
            .where(MinionGroup.org_id == org.id)
            .where(MinionGroup.name == env_name)
        ).first()
        if not group:
            group = MinionGroup(org_id=org.id, name=env_name)
            db.add(group)
            db.flush()

        db.commit()
        org_id, group_id = org.id, group.id

    assign_minion_to_group(minion_id, org_id, group_id)
    _log.info("Provisioned %s → %s / %s", minion_id, org_name, env_name)


# ---------------------------------------------------------------------------
# Scan ingestion
# ---------------------------------------------------------------------------

def ingest_scan(minion_id: str, packages: list[dict], scanned_at: Optional[datetime]) -> None:
    """Replace all MinionPatch rows for *minion_id* with fresh scan data."""
    ts = scanned_at or datetime.utcnow()
    with Session(engine) as db:
        # Delete stale rows
        old = db.exec(select(MinionPatch).where(MinionPatch.minion_id == minion_id)).all()
        for row in old:
            db.delete(row)
        # Insert fresh rows
        for pkg in packages:
            db.add(MinionPatch(
                minion_id=minion_id,
                package_name=pkg.get("name", ""),
                installed_version=pkg.get("installed_version", ""),
                available_version=pkg.get("available_version", ""),
                advisory_id=pkg.get("advisory_id"),
                advisory_type=pkg.get("advisory_type", "enhancement"),
                severity=pkg.get("severity", "none"),
                cve_ids=json.dumps(pkg.get("cve_ids", [])),
                scanned_at=ts,
            ))
        # Always stamp last_patch_scan so "never scanned" clears even on clean machines
        m = db.get(Minion, minion_id)
        if m:
            m.last_patch_scan = ts
            db.add(m)
        db.commit()
    _log.info("Ingested %d patches for minion %s", len(packages), minion_id)


# ---------------------------------------------------------------------------
# Patch command builder
# ---------------------------------------------------------------------------

_WUA_ALL = (
    "$s=New-Object -ComObject Microsoft.Update.Session;"
    "$q=$s.CreateUpdateSearcher().Search('IsInstalled=0 and Type=''Software''');"
    "if($q.Updates.Count -eq 0){Write-Host 'No updates pending';exit 0};"
    "$c=New-Object -ComObject Microsoft.Update.UpdateColl;"
    "$q.Updates|ForEach-Object{if(!$_.EulaAccepted){$_.AcceptEula()};$c.Add($_)|Out-Null};"
    "$d=$s.CreateUpdateDownloader();$d.Updates=$c;$d.Download()|Out-Null;"
    "$i=$s.CreateUpdateInstaller();$i.Updates=$c;$r=$i.Install();"
    "Write-Host \"Installed $($c.Count) update(s). ResultCode=$($r.ResultCode)\";"
    "exit $(if($r.ResultCode -le 3){0}else{1})"
)

_WUA_SECURITY = (
    "$s=New-Object -ComObject Microsoft.Update.Session;"
    "$q=$s.CreateUpdateSearcher().Search('IsInstalled=0 and Type=''Software''');"
    "$c=New-Object -ComObject Microsoft.Update.UpdateColl;"
    "$q.Updates|Where-Object{$_.MsrcSeverity -in @('Critical','Important')}|"
    "ForEach-Object{if(!$_.EulaAccepted){$_.AcceptEula()};$c.Add($_)|Out-Null};"
    "if($c.Count -eq 0){Write-Host 'No security updates pending';exit 0};"
    "$d=$s.CreateUpdateDownloader();$d.Updates=$c;$d.Download()|Out-Null;"
    "$i=$s.CreateUpdateInstaller();$i.Updates=$c;$r=$i.Install();"
    "Write-Host \"Installed $($c.Count) security update(s). ResultCode=$($r.ResultCode)\";"
    "exit $(if($r.ResultCode -le 3){0}else{1})"
)


def _build_patch_cmd(pkg_manager: str, scope: str, custom_packages: Optional[str]) -> str:
    """Return the shell command to apply patches for the given scope."""
    if pkg_manager == "winget":
        # WUA COM works under SYSTEM; winget does not
        if scope == "custom":
            pkgs = " ".join(json.loads(custom_packages or "[]"))
            return (
                "$s=New-Object -ComObject Microsoft.Update.Session;"
                "$q=$s.CreateUpdateSearcher().Search('IsInstalled=0 and Type=''Software''');"
                "$c=New-Object -ComObject Microsoft.Update.UpdateColl;"
                f"$names=@({','.join(ps_quote(p) for p in json.loads(custom_packages or '[]'))});"
                "$q.Updates|Where-Object{$n=$_.Title;$names|Where-Object{$n -like \"*$_*\"}}|"
                "ForEach-Object{if(!$_.EulaAccepted){$_.AcceptEula()};$c.Add($_)|Out-Null};"
                "if($c.Count -eq 0){Write-Host 'No matching updates';exit 0};"
                "$d=$s.CreateUpdateDownloader();$d.Updates=$c;$d.Download()|Out-Null;"
                "$i=$s.CreateUpdateInstaller();$i.Updates=$c;$r=$i.Install();"
                "exit $(if($r.ResultCode -le 3){0}else{1})"
            ) if pkgs else "Write-Host 'No packages specified'"
        if scope == "security":
            return _WUA_SECURITY
        return _WUA_ALL

    if scope == "security":
        if pkg_manager in ("dnf", "yum"):
            return f"{pkg_manager} upgrade --security -y"
        return (
            "apt-get upgrade -y "
            "$(apt list --upgradable 2>/dev/null "
            "| grep -E '\\-security|\\-ESM' "
            "| cut -d/ -f1 | tr '\\n' ' ')"
        )
    if scope == "all":
        if pkg_manager in ("dnf", "yum"):
            return f"{pkg_manager} upgrade -y"
        return "apt-get upgrade -y"
    if scope == "custom":
        import shlex
        pkgs = " ".join(shlex.quote(p) for p in json.loads(custom_packages or "[]"))
        if pkg_manager in ("dnf", "yum"):
            return f"{pkg_manager} install -y {pkgs}"
        return f"apt-get install -y {pkgs}"
    raise ValueError(f"Unknown scope: {scope}")


def _reboot_cmd(pkg_manager: str) -> str:
    """Return the command to immediately reboot the machine."""
    if pkg_manager == "winget":
        return "Restart-Computer -Force"
    return "shutdown -r now"


def _reboot_check_cmd(pkg_manager: str) -> str:
    """Return a command that prints 'yes' if a reboot is pending, 'no' otherwise."""
    if pkg_manager == "winget":
        # Agent already runs this inside: powershell -NonInteractive -Command <cmd>
        return (
            "$r=$false;"
            "if(Get-Item 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Component Based Servicing\\RebootPending' -EA SilentlyContinue){$r=$true};"
            "if(Get-Item 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update\\RebootRequired' -EA SilentlyContinue){$r=$true};"
            "if($r){'yes'}else{'no'}"
        )
    # Universal Linux reboot-check — tries each method in order, first match wins
    return (
        # 1. Debian/Ubuntu/some SUSE: sentinel file written by unattended-upgrades / needrestart
        "if [ -f /var/run/reboot-required ]; then echo yes; "
        # 2. RHEL-family with yum-utils installed
        "elif command -v needs-restarting >/dev/null 2>&1; then "
        "  needs-restarting -r >/dev/null 2>&1 && echo no || echo yes; "
        # 3. RPM-based without yum-utils: compare running kernel vs newest installed
        "elif command -v rpm >/dev/null 2>&1; then "
        "  RUNNING=$(uname -r); "
        "  INSTALLED=$(rpm -q kernel --last 2>/dev/null | head -1 | awk '{print $1}' | sed 's/kernel-//'); "
        "  if [ -n \"$INSTALLED\" ] && [ \"$RUNNING\" != \"$INSTALLED\" ]; then echo yes; else echo no; fi; "
        # 4. DEB-based fallback: compare running kernel vs newest installed linux-image
        "elif command -v dpkg >/dev/null 2>&1; then "
        "  RUNNING=$(uname -r); "
        "  INSTALLED=$(dpkg -l 'linux-image-[0-9]*' 2>/dev/null | awk '/^ii/{print $2}' | sed 's/linux-image-//' | sort -V | tail -1); "
        "  if [ -n \"$INSTALLED\" ] && [ \"$RUNNING\" != \"$INSTALLED\" ]; then echo yes; else echo no; fi; "
        # 5. Generic: any running process whose binary has been replaced (deleted on disk)
        "else "
        "  if find /proc/[0-9]*/exe -maxdepth 0 2>/dev/null | xargs -r readlink 2>/dev/null | grep -q deleted; then echo yes; else echo no; fi; "
        "fi"
    )


# ---------------------------------------------------------------------------
# Patch apply
# ---------------------------------------------------------------------------

def _snapshot_advisories(db: Session, minion_id: str) -> list[dict]:
    """Return the current pending MinionPatch rows for minion_id as a serialisable list."""
    rows = db.exec(select(MinionPatch).where(MinionPatch.minion_id == minion_id)).all()
    return [
        {
            "advisory_id": r.advisory_id,
            "package_name": r.package_name,
            "severity": r.severity,
            "advisory_type": r.advisory_type,
            "from_version": r.installed_version,
            "to_version": r.available_version,
        }
        for r in rows
    ]


async def apply_patches(
    group_id: str,
    scope: str,
    custom_packages: Optional[str],
    actor: str,
    promotion_id: Optional[str] = None,
    auto_reboot: bool = False,
) -> dict:
    """Dispatch patch commands to all active minions in *group_id* in parallel."""
    from app.services.minion_service import manager  # avoid circular import

    with Session(engine) as db:
        member_ids = [
            m.minion_id for m in
            db.exec(select(MinionGroupMember).where(MinionGroupMember.group_id == group_id)).all()
        ]
        minions = [
            m for m in
            [db.get(Minion, mid) for mid in member_ids]
            if m and m.status == "active"
        ]

    if not minions:
        return {"dispatched": 0, "results": []}

    async def _patch_one(minion: Minion) -> dict:
        with Session(engine) as db:
            import json as _json
            grains = _json.loads(minion.grains or "{}")
            # Snapshot BEFORE patching — captures what was pending
            advisory_snapshot = _snapshot_advisories(db, minion.id)

        os_str = grains.get("os", "").lower()
        if "windows" in os_str:
            pkg_mgr = "winget"
        elif any(x in os_str for x in ("rhel", "centos", "rocky", "fedora", "alma", "ol", "anolis")):
            pkg_mgr = "dnf"
        elif any(x in os_str for x in ("suse", "sles", "opensuse")):
            pkg_mgr = "zypper"
        elif any(x in os_str for x in ("ubuntu", "debian", "mint", "pop", "kali", "raspbian")):
            pkg_mgr = "apt"
        else:
            pkg_mgr = "apt"

        cmd = _build_patch_cmd(pkg_mgr, scope, custom_packages)
        try:
            result = await manager.dispatch_job(minion.id, cmd, actor=actor, timeout=300, god_mode=True)
            status = "done" if result["exit_code"] == 0 else "failed"
            stdout_raw = result.get("stdout", result.get("output", "")) or ""

            reboot_required = False
            try:
                rb_result = await manager.dispatch_job(
                    minion.id, _reboot_check_cmd(pkg_mgr), actor=actor, timeout=30, god_mode=True
                )
                reboot_required = "yes" in rb_result.get("stdout", "").lower()
            except Exception:
                pass

            if auto_reboot and reboot_required:
                try:
                    await asyncio.wait_for(
                        manager.dispatch_job(minion.id, _reboot_cmd(pkg_mgr), actor=actor, timeout=10, god_mode=True),
                        timeout=15.0,
                    )
                except Exception:
                    pass

            if promotion_id:
                with Session(engine) as db:
                    db.add(PatchPromotionResult(
                        promotion_id=promotion_id,
                        minion_id=minion.id,
                        status=status,
                        exit_code=result["exit_code"],
                        stdout=stdout_raw[:4096] if stdout_raw else None,
                        applied_advisories=json.dumps(advisory_snapshot),
                        packages_count=len(advisory_snapshot),
                    ))
                    db.commit()

            return {
                "minion_id": minion.id,
                "exit_code": result["exit_code"],
                "status": status,
                "reboot_required": reboot_required,
                "rebooted": auto_reboot and reboot_required,
            }
        except Exception as e:
            if promotion_id:
                with Session(engine) as db:
                    db.add(PatchPromotionResult(
                        promotion_id=promotion_id,
                        minion_id=minion.id,
                        status="failed",
                        exit_code=-1,
                        stdout=str(e)[:4096],
                        applied_advisories=json.dumps(advisory_snapshot),
                        packages_count=len(advisory_snapshot),
                    ))
                    db.commit()
            return {"minion_id": minion.id, "exit_code": -1, "status": "failed", "error": str(e), "reboot_required": False, "rebooted": False}

    results = await asyncio.gather(*[_patch_one(m) for m in minions])

    # Determine final status
    passed = [r for r in results if r["status"] == "done"]
    failed = [r for r in results if r["status"] == "failed"]

    if len(failed) == 0:
        final_status = "done"
    elif len(passed) == 0:
        final_status = "failed"
    else:
        final_status = "partial"

    failed_ids = [r["minion_id"] for r in failed]
    reboot_ids = [r["minion_id"] for r in results if r.get("reboot_required")]

    if promotion_id:
        with Session(engine) as db:
            promo = db.get(PatchPromotion, promotion_id)
            if promo:
                promo.status = final_status
                promo.completed_at = datetime.utcnow()
                if failed_ids:
                    promo.failed_minions = json.dumps(failed_ids)
                if reboot_ids:
                    promo.reboot_minions = json.dumps(reboot_ids)
                db.add(promo)
                db.commit()

    # Trigger rescan via WebSocket scan_patches message (not a dummy shell command)
    from app.services.minion_service import manager as _mgr
    for m in minions:
        ws = _mgr._connections.get(m.id)
        if ws:
            try:
                asyncio.ensure_future(ws.send_json({"type": "scan_patches"}))
            except Exception:
                pass

    return {"dispatched": len(minions), "results": list(results)}


# ---------------------------------------------------------------------------
# APScheduler bootstrap
# ---------------------------------------------------------------------------

def create_scheduler(db_url: str):
    """Create and return a configured AsyncIOScheduler with SQLAlchemy job store."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

    scheduler = AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=db_url)},
        job_defaults={"coalesce": True, "max_instances": 1},
    )
    return scheduler


def load_schedules(scheduler) -> None:
    """Load all enabled PatchSchedule rows from DB and register as cron jobs."""
    with Session(engine) as db:
        schedules = db.exec(select(PatchSchedule).where(PatchSchedule.enabled == True)).all()

    for sched in schedules:
        _register_schedule(scheduler, sched)
    _log.info("Loaded %d patch schedules", len(schedules))


def _register_schedule(scheduler, sched: PatchSchedule) -> None:
    from apscheduler.triggers.cron import CronTrigger

    async def _run(sched_id: str = sched.id):
        with Session(engine) as db:
            _sched = db.get(PatchSchedule, sched_id)
        if not _sched or not _sched.enabled:
            return
        await run_scheduled_stage(_sched)

    scheduler.add_job(
        _run,
        trigger=CronTrigger.from_crontab(sched.cron_expr, timezone=sched.timezone),
        id=f"patch_sched_{sched.id}",
        replace_existing=True,
    )


# ---------------------------------------------------------------------------
# Alert events
# ---------------------------------------------------------------------------

def emit_alert_event(pipeline_id: str, stage_id: str, reason: str) -> None:
    """Write a PatchAlertEvent row. Called when a promote_from_previous cron is blocked."""
    from app.models.patch import PatchAlertEvent
    with Session(engine) as db:
        db.add(PatchAlertEvent(pipeline_id=pipeline_id, stage_id=stage_id, reason=reason))
        db.commit()
    _log.warning("Alert event: pipeline=%s stage=%s reason=%s", pipeline_id, stage_id, reason)


# ---------------------------------------------------------------------------
# Scheduled stage execution
# ---------------------------------------------------------------------------

async def run_scheduled_stage(sched: PatchSchedule) -> None:
    """Execute a scheduled patch stage. Handles both fresh-resolve and promote_from_previous modes."""
    # Enforce week-of-month constraint when set (1=first, 2=second, 3=third, 4=fourth).
    # The cron fires every week on the given weekday; we skip here when the week number
    # within the current month does not match.
    if sched.week_of_month is not None:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(sched.timezone or "UTC")
        except Exception:
            from datetime import timezone as _tz
            tz = _tz.utc
        import datetime as _dt
        now = _dt.datetime.now(tz)
        current_week = (now.day - 1) // 7 + 1
        if current_week != sched.week_of_month:
            _log.info(
                "Skipping schedule %s: current week %d != required week %d",
                sched.id, current_week, sched.week_of_month,
            )
            return

    def _create_fresh_promo(
        db: Session,
        stage: PipelineStage,
    ) -> tuple[str, str, str, Optional[str]]:
        """Insert a fresh PatchPromotion for *stage* and return (promo_id, group_id, scope, custom)."""
        promo = PatchPromotion(
            pipeline_id=sched.pipeline_id,
            to_stage_id=sched.stage_id,
            patch_scope=sched.patch_scope,
            custom_packages=sched.custom_packages,
            triggered_by="scheduler",
            status="running",
        )
        db.add(promo)
        db.commit()
        db.refresh(promo)
        return promo.id, stage.group_id, sched.patch_scope, sched.custom_packages

    with Session(engine) as db:
        stage = db.get(PipelineStage, sched.stage_id)
        if not stage:
            _log.error("Stage %s not found for schedule %s", sched.stage_id, sched.id)
            return

        if not sched.promote_from_previous:
            # Fresh resolve — apply directly to this stage's group
            promo_id, group_id, scope, custom = _create_fresh_promo(db, stage)

        else:
            # promote_from_previous — find prior stage and read its frozen package list
            prior_stage = db.exec(
                select(PipelineStage)
                .where(
                    PipelineStage.pipeline_id == sched.pipeline_id,
                    PipelineStage.order == stage.order - 1,
                )
            ).first()

            if not prior_stage:
                # This is stage 0 — no prior stage. Treat as fresh resolve.
                _log.warning(
                    "promote_from_previous=True on first stage %s — treating as fresh resolve",
                    sched.stage_id,
                )
                promo_id, group_id, scope, custom = _create_fresh_promo(db, stage)

            else:
                # Find the latest PatchPromotion for the prior stage
                prior_promo = db.exec(
                    select(PatchPromotion)
                    .where(PatchPromotion.to_stage_id == prior_stage.id)
                    .order_by(PatchPromotion.triggered_at.desc())
                ).first()

                if not prior_promo:
                    emit_alert_event(sched.pipeline_id, sched.stage_id, "no_prior_run")
                    return
                if prior_promo.status in ("running", "pending"):
                    emit_alert_event(sched.pipeline_id, sched.stage_id, "prior_stage_not_complete")
                    return
                if prior_promo.status == "failed":
                    emit_alert_event(sched.pipeline_id, sched.stage_id, "prior_stage_failed")
                    return
                if prior_promo.status == "partial":
                    emit_alert_event(sched.pipeline_id, sched.stage_id, "prior_stage_partial")
                    return

                # prior stage is done — promote its frozen package list
                promo = PatchPromotion(
                    pipeline_id=sched.pipeline_id,
                    from_stage_id=prior_stage.id,
                    to_stage_id=sched.stage_id,
                    patch_scope="custom",
                    custom_packages=prior_promo.custom_packages,
                    triggered_by="scheduler",
                    status="running",
                )
                db.add(promo)
                db.commit()
                db.refresh(promo)
                promo_id = promo.id
                group_id = stage.group_id
                scope = "custom"
                custom = prior_promo.custom_packages

    await apply_patches(
        group_id=group_id,
        scope=scope,
        custom_packages=custom,
        actor="scheduler",
        promotion_id=promo_id,
        auto_reboot=sched.auto_reboot,
    )

    # ── Post-run notifications ─────────────────────────────────────────────────
    if sched.notifications:
        try:
            from app.services.notification_service import (
                build_patch_summary, send_notifications, ai_beautify_message,
            )
            with Session(engine) as db:
                promo    = db.get(PatchPromotion, promo_id)
                results  = db.exec(
                    select(PatchPromotionResult)
                    .where(PatchPromotionResult.promotion_id == promo_id)
                ).all()
                pipeline = db.get(PatchPipeline, sched.pipeline_id)
                stage_obj = db.get(PipelineStage, sched.stage_id)
                minion_ids = [r.minion_id for r in results]
                minion_hostnames = {
                    m.id: m.hostname
                    for m in [db.get(Minion, mid) for mid in minion_ids]
                    if m
                }
            summary = build_patch_summary(
                promo,
                list(results),
                minion_hostnames,
                pipeline.name if pipeline else sched.pipeline_id,
                stage_obj.name if stage_obj else sched.stage_id,
                sched.auto_reboot,
            )
            if sched.ai_beautify:
                summary = await ai_beautify_message(summary)
            await send_notifications(sched.notifications, summary)
        except Exception as exc:
            _log.warning("Patch notification failed: %s", exc)
