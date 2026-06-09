import pytest
from unittest.mock import patch
from sqlmodel import Session, create_engine, SQLModel, select
from app.models.patch import (
    Organisation, MinionGroup, MinionGroupMember,
    MinionPatch, PatchPipeline, PipelineStage,
    PatchPromotion, PatchSchedule, PatchPromotionResult,
)
from app.services.patch_service import ingest_scan, _build_patch_cmd
from app.models.minion import Minion

TEST_DB = "sqlite://"

@pytest.fixture(name="engine")
def engine_fixture():
    from app.models.minion import Minion, MinionJob  # ensure minion tables exist
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)

def test_models_create_tables(engine):
    """All new models must be importable and tables must be created."""
    with Session(engine) as db:
        db.add(Organisation(name="Acme", slug="acme"))
        db.commit()
        org = db.exec(select(Organisation).where(Organisation.slug == "acme")).first()
        assert org is not None
        assert org.id is not None

def test_minion_group_belongs_to_org(engine):
    with Session(engine) as db:
        org = Organisation(name="Corp", slug="corp")
        db.add(org)
        db.commit()
        db.refresh(org)
        grp = MinionGroup(org_id=org.id, name="dev-web")
        db.add(grp)
        db.commit()
        db.refresh(grp)
        assert grp.org_id == org.id

@pytest.fixture
def seeded_minion(engine):
    with Session(engine) as db:
        m = Minion(id="m1", hostname="host1", status="active")
        db.add(m)
        db.commit()
    return "m1"

def test_ingest_scan_creates_patch_rows(engine, seeded_minion):
    packages = [
        {
            "name": "nginx",
            "installed_version": "1.18.0",
            "available_version": "1.24.0",
            "advisory_id": "USN-5834-1",
            "advisory_type": "security",
            "severity": "high",
            "cve_ids": ["CVE-2023-44487"],
        }
    ]
    with patch("app.services.patch_service.engine", engine):
        ingest_scan("m1", packages, scanned_at=None)

    with Session(engine) as db:
        rows = db.exec(select(MinionPatch).where(MinionPatch.minion_id == "m1")).all()
        assert len(rows) == 1
        assert rows[0].package_name == "nginx"
        assert rows[0].severity == "high"
        assert rows[0].cve_ids == '["CVE-2023-44487"]'

def test_ingest_scan_replaces_old_rows(engine, seeded_minion):
    """Second scan must replace first — no stale rows."""
    with patch("app.services.patch_service.engine", engine):
        ingest_scan("m1", [{"name": "old-pkg", "installed_version": "1.0",
                             "available_version": "2.0", "advisory_type": "bugfix",
                             "severity": "low", "cve_ids": []}], scanned_at=None)
        ingest_scan("m1", [{"name": "new-pkg", "installed_version": "3.0",
                             "available_version": "4.0", "advisory_type": "security",
                             "severity": "critical", "cve_ids": ["CVE-2024-0001"]}], scanned_at=None)

    with Session(engine) as db:
        rows = db.exec(select(MinionPatch).where(MinionPatch.minion_id == "m1")).all()
        assert len(rows) == 1
        assert rows[0].package_name == "new-pkg"

def test_build_patch_cmd_security(engine):
    assert "security" in _build_patch_cmd("apt", "security", None)
    assert "security" in _build_patch_cmd("dnf", "security", None)

def test_build_patch_cmd_all(engine):
    cmd = _build_patch_cmd("apt", "all", None)
    assert "upgrade" in cmd
    cmd2 = _build_patch_cmd("yum", "all", None)
    assert "upgrade" in cmd2

def test_build_patch_cmd_custom(engine):
    cmd = _build_patch_cmd("apt", "custom", '["nginx", "openssl"]')
    assert "nginx" in cmd
    assert "openssl" in cmd


# ---------------------------------------------------------------------------
# Tests for partial apply status + rescan
# ---------------------------------------------------------------------------

import asyncio
import json
from unittest.mock import patch as mock_patch


@pytest.fixture(name="engine2")
def engine2_fixture():
    from app.models.minion import MinionJob  # ensure all tables registered
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


def _seed(db_engine):
    """Seed org, group, 4 minions (all active), return (group_id, [minion_ids])."""
    with Session(db_engine) as db:
        org = Organisation(name="Acme", slug="acme-partial")
        db.add(org)
        db.flush()
        grp = MinionGroup(org_id=org.id, name="dev-web")
        db.add(grp)
        db.flush()
        minion_ids = []
        for i in range(4):
            m = Minion(
                id=f"minion-{i}",
                hostname=f"host-{i}",
                status="active",
                grains='{"os": "Ubuntu 22.04"}',
            )
            db.add(m)
            db.flush()
            db.add(MinionGroupMember(group_id=grp.id, minion_id=m.id))
            minion_ids.append(m.id)
        db.commit()
        return grp.id, minion_ids


def _fake_dispatch(results_by_minion: dict):
    """Return an async function that resolves based on minion_id.
    results_by_minion maps minion_id -> exit_code (int)."""
    async def _dispatch(minion_id, cmd, actor, timeout=60, god_mode=False):
        exit_code = results_by_minion.get(minion_id, 0)
        stdout = "Installed 3 update(s)." if exit_code == 0 else "Error: package not found"
        return {"exit_code": exit_code, "stdout": stdout, "output": stdout}
    return _dispatch


def test_apply_patches_all_pass(engine2):
    group_id, minion_ids = _seed(engine2)
    results = {mid: 0 for mid in minion_ids}

    with Session(engine2) as db:
        p = PatchPromotion(
            pipeline_id="pipe-1", to_stage_id="stage-1",
            patch_scope="security", triggered_by="test", status="running",
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        promo_id = p.id

    from app.services import patch_service
    with mock_patch("app.services.patch_service.engine", engine2), \
         mock_patch("app.services.minion_service.manager") as mock_mgr:
        mock_mgr.dispatch_job.side_effect = _fake_dispatch(results)
        mock_mgr._connections = {}
        asyncio.run(patch_service.apply_patches(
            group_id=group_id, scope="security",
            custom_packages=None, actor="test", promotion_id=promo_id,
        ))

    with Session(engine2) as db:
        promo = db.get(PatchPromotion, promo_id)
        assert promo.status == "done"
        assert promo.failed_minions is None or json.loads(promo.failed_minions or "[]") == []


def test_apply_patches_partial(engine2):
    group_id, minion_ids = _seed(engine2)
    # minion-0 and minion-1 fail, minion-2 and minion-3 pass
    results = {minion_ids[0]: 1, minion_ids[1]: 1, minion_ids[2]: 0, minion_ids[3]: 0}

    with Session(engine2) as db:
        p = PatchPromotion(
            pipeline_id="pipe-1", to_stage_id="stage-1",
            patch_scope="security", triggered_by="test", status="running",
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        promo_id = p.id

    from app.services import patch_service
    with mock_patch("app.services.patch_service.engine", engine2), \
         mock_patch("app.services.minion_service.manager") as mock_mgr:
        mock_mgr.dispatch_job.side_effect = _fake_dispatch(results)
        mock_mgr._connections = {}
        asyncio.run(patch_service.apply_patches(
            group_id=group_id, scope="security",
            custom_packages=None, actor="test", promotion_id=promo_id,
        ))

    with Session(engine2) as db:
        promo = db.get(PatchPromotion, promo_id)
        assert promo.status == "partial"
        failed = json.loads(promo.failed_minions or "[]")
        assert set(failed) == {minion_ids[0], minion_ids[1]}


def test_apply_patches_all_fail(engine2):
    group_id, minion_ids = _seed(engine2)
    results = {mid: 1 for mid in minion_ids}

    with Session(engine2) as db:
        p = PatchPromotion(
            pipeline_id="pipe-1", to_stage_id="stage-1",
            patch_scope="security", triggered_by="test", status="running",
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        promo_id = p.id

    from app.services import patch_service
    with mock_patch("app.services.patch_service.engine", engine2), \
         mock_patch("app.services.minion_service.manager") as mock_mgr:
        mock_mgr.dispatch_job.side_effect = _fake_dispatch(results)
        mock_mgr._connections = {}
        asyncio.run(patch_service.apply_patches(
            group_id=group_id, scope="security",
            custom_packages=None, actor="test", promotion_id=promo_id,
        ))

    with Session(engine2) as db:
        promo = db.get(PatchPromotion, promo_id)
        assert promo.status == "failed"
        failed = json.loads(promo.failed_minions or "[]")
        assert set(failed) == set(minion_ids)


def test_apply_patches_saves_result_rows(engine2):
    """A PatchPromotionResult row must exist for every minion after apply."""
    group_id, minion_ids = _seed(engine2)
    with Session(engine2) as db:
        for mid in minion_ids:
            db.add(MinionPatch(
                minion_id=mid,
                package_name="openssl",
                installed_version="1.1.1",
                available_version="3.0.0",
                advisory_id="RLSA-2024:1234",
                advisory_type="security",
                severity="high",
                cve_ids='["CVE-2024-0001"]',
            ))
        promo = PatchPromotion(
            pipeline_id="pipe-1", to_stage_id="stage-1",
            patch_scope="security", triggered_by="test", status="running",
        )
        db.add(promo)
        db.commit()
        db.refresh(promo)
        promo_id = promo.id

    results = {mid: 0 for mid in minion_ids}
    from app.services import patch_service
    with mock_patch("app.services.patch_service.engine", engine2), \
         mock_patch("app.services.minion_service.manager") as mock_mgr:
        mock_mgr.dispatch_job.side_effect = _fake_dispatch(results)
        mock_mgr._connections = {}
        asyncio.run(patch_service.apply_patches(
            group_id=group_id, scope="security",
            custom_packages=None, actor="test", promotion_id=promo_id,
        ))

    with Session(engine2) as db:
        rows = db.exec(
            select(PatchPromotionResult)
            .where(PatchPromotionResult.promotion_id == promo_id)
        ).all()
        assert len(rows) == len(minion_ids)
        for row in rows:
            assert row.status == "done"
            assert row.exit_code == 0
            assert row.packages_count == 1
            advisories = json.loads(row.applied_advisories)
            assert len(advisories) == 1
            assert advisories[0]["advisory_id"] == "RLSA-2024:1234"
            assert advisories[0]["severity"] == "high"
            assert advisories[0]["from_version"] == "1.1.1"
            assert advisories[0]["to_version"] == "3.0.0"


def test_apply_patches_result_row_failed_minion(engine2):
    """Failed minion must have status='failed' and non-zero exit_code in result row."""
    group_id, minion_ids = _seed(engine2)
    with Session(engine2) as db:
        promo = PatchPromotion(
            pipeline_id="pipe-2", to_stage_id="stage-2",
            patch_scope="all", triggered_by="test", status="running",
        )
        db.add(promo)
        db.commit()
        db.refresh(promo)
        promo_id = promo.id

    results = {minion_ids[0]: 1, minion_ids[1]: 0, minion_ids[2]: 0, minion_ids[3]: 0}
    from app.services import patch_service
    with mock_patch("app.services.patch_service.engine", engine2), \
         mock_patch("app.services.minion_service.manager") as mock_mgr:
        mock_mgr.dispatch_job.side_effect = _fake_dispatch(results)
        mock_mgr._connections = {}
        asyncio.run(patch_service.apply_patches(
            group_id=group_id, scope="all",
            custom_packages=None, actor="test", promotion_id=promo_id,
        ))

    with Session(engine2) as db:
        failed_rows = db.exec(
            select(PatchPromotionResult)
            .where(PatchPromotionResult.promotion_id == promo_id)
            .where(PatchPromotionResult.minion_id == minion_ids[0])
        ).all()
        assert len(failed_rows) == 1
        assert failed_rows[0].status == "failed"
        assert failed_rows[0].exit_code == 1

        done_rows = db.exec(
            select(PatchPromotionResult)
            .where(PatchPromotionResult.promotion_id == promo_id)
            .where(PatchPromotionResult.minion_id == minion_ids[1])
        ).all()
        assert done_rows[0].status == "done"


def test_apply_patches_result_stdout_truncated(engine2):
    """stdout longer than 4096 chars must be stored truncated."""
    group_id, minion_ids = _seed(engine2)
    with Session(engine2) as db:
        promo = PatchPromotion(
            pipeline_id="pipe-3", to_stage_id="stage-3",
            patch_scope="all", triggered_by="test", status="running",
        )
        db.add(promo)
        db.commit()
        db.refresh(promo)
        promo_id = promo.id

    long_stdout = "x" * 8000

    async def _long_dispatch(minion_id, cmd, actor, timeout=60, god_mode=False):
        return {"exit_code": 0, "stdout": long_stdout, "output": long_stdout}

    from app.services import patch_service
    with mock_patch("app.services.patch_service.engine", engine2), \
         mock_patch("app.services.minion_service.manager") as mock_mgr:
        mock_mgr.dispatch_job.side_effect = _long_dispatch
        mock_mgr._connections = {}
        asyncio.run(patch_service.apply_patches(
            group_id=group_id, scope="all",
            custom_packages=None, actor="test", promotion_id=promo_id,
        ))

    with Session(engine2) as db:
        rows = db.exec(
            select(PatchPromotionResult)
            .where(PatchPromotionResult.promotion_id == promo_id)
        ).all()
        for row in rows:
            assert len(row.stdout or "") <= 4096


# ── run_scheduled_stage tests ──────────────────────────────────────────────

from app.models.patch import PatchPipeline, PipelineStage, PatchSchedule
from app.models.patch import PatchAlertEvent
from unittest.mock import AsyncMock


def _seed_pipeline(engine):
    """Seed a pipeline with two stages (dev order=0, qa order=1) and return IDs."""
    with Session(engine) as db:
        org = Organisation(name="Beta", slug="beta")
        db.add(org)
        db.flush()
        pipeline = PatchPipeline(org_id=org.id, name="pipe", auto_promote=False)
        db.add(pipeline)
        db.flush()
        grp_dev = MinionGroup(org_id=org.id, name="dev-web")
        grp_qa = MinionGroup(org_id=org.id, name="qa-web")
        db.add(grp_dev); db.add(grp_qa); db.flush()
        stage_dev = PipelineStage(pipeline_id=pipeline.id, group_id=grp_dev.id, order=0, name="dev")
        stage_qa = PipelineStage(pipeline_id=pipeline.id, group_id=grp_qa.id, order=1, name="qa")
        db.add(stage_dev); db.add(stage_qa); db.flush()
        db.commit()
        return pipeline.id, stage_dev.id, stage_qa.id, grp_dev.id, grp_qa.id


def test_run_scheduled_stage_no_prior_run(engine):
    pipeline_id, stage_dev_id, stage_qa_id, grp_dev_id, grp_qa_id = _seed_pipeline(engine)
    sched = PatchSchedule(
        pipeline_id=pipeline_id, stage_id=stage_qa_id,
        cron_expr="0 2 * * 1", timezone="UTC",
        patch_scope="security", promote_from_previous=True,
        created_by="test",
    )

    from app.services import patch_service
    with patch("app.services.patch_service.engine", engine):
        asyncio.run(patch_service.run_scheduled_stage(sched))

    with Session(engine) as db:
        alerts = db.exec(
            select(PatchAlertEvent)
            .where(PatchAlertEvent.stage_id == stage_qa_id)
        ).all()
        assert len(alerts) == 1
        assert alerts[0].reason == "no_prior_run"
        assert alerts[0].acknowledged is False


def test_run_scheduled_stage_prior_failed(engine):
    pipeline_id, stage_dev_id, stage_qa_id, grp_dev_id, grp_qa_id = _seed_pipeline(engine)
    with Session(engine) as db:
        promo = PatchPromotion(
            pipeline_id=pipeline_id, to_stage_id=stage_dev_id,
            patch_scope="security", triggered_by="test",
            status="failed", custom_packages='["nginx"]',
        )
        db.add(promo); db.commit()

    sched = PatchSchedule(
        pipeline_id=pipeline_id, stage_id=stage_qa_id,
        cron_expr="0 2 * * 1", timezone="UTC",
        patch_scope="security", promote_from_previous=True,
        created_by="test",
    )

    from app.services import patch_service
    with patch("app.services.patch_service.engine", engine):
        asyncio.run(patch_service.run_scheduled_stage(sched))

    with Session(engine) as db:
        alerts = db.exec(
            select(PatchAlertEvent)
            .where(PatchAlertEvent.stage_id == stage_qa_id)
        ).all()
        assert len(alerts) == 1
        assert alerts[0].reason == "prior_stage_failed"


def test_run_scheduled_stage_prior_partial(engine):
    pipeline_id, stage_dev_id, stage_qa_id, grp_dev_id, grp_qa_id = _seed_pipeline(engine)
    with Session(engine) as db:
        promo = PatchPromotion(
            pipeline_id=pipeline_id, to_stage_id=stage_dev_id,
            patch_scope="security", triggered_by="test",
            status="partial", custom_packages='["nginx"]',
            failed_minions='["minion-0"]',
        )
        db.add(promo); db.commit()

    sched = PatchSchedule(
        pipeline_id=pipeline_id, stage_id=stage_qa_id,
        cron_expr="0 2 * * 1", timezone="UTC",
        patch_scope="security", promote_from_previous=True,
        created_by="test",
    )

    from app.services import patch_service
    with patch("app.services.patch_service.engine", engine):
        asyncio.run(patch_service.run_scheduled_stage(sched))

    with Session(engine) as db:
        alerts = db.exec(
            select(PatchAlertEvent)
            .where(PatchAlertEvent.stage_id == stage_qa_id)
        ).all()
        assert len(alerts) == 1
        assert alerts[0].reason == "prior_stage_partial"


def test_run_scheduled_stage_prior_done_calls_apply(engine):
    pipeline_id, stage_dev_id, stage_qa_id, grp_dev_id, grp_qa_id = _seed_pipeline(engine)
    with Session(engine) as db:
        promo = PatchPromotion(
            pipeline_id=pipeline_id, to_stage_id=stage_dev_id,
            patch_scope="security", triggered_by="test",
            status="done", custom_packages='["nginx", "openssl"]',
        )
        db.add(promo); db.commit()

    sched = PatchSchedule(
        pipeline_id=pipeline_id, stage_id=stage_qa_id,
        cron_expr="0 2 * * 1", timezone="UTC",
        patch_scope="security", promote_from_previous=True,
        created_by="test",
    )

    from app.services import patch_service
    with patch("app.services.patch_service.engine", engine), \
         patch.object(patch_service, "apply_patches", new=AsyncMock()) as mock_apply:
        asyncio.run(patch_service.run_scheduled_stage(sched))
        mock_apply.assert_called_once()
        call_kwargs = mock_apply.call_args.kwargs
        assert call_kwargs["group_id"] == grp_qa_id
        assert call_kwargs["scope"] == "custom"
        assert call_kwargs["custom_packages"] == '["nginx", "openssl"]'

    with Session(engine) as db:
        from sqlmodel import select as _select
        promos = db.exec(
            _select(PatchPromotion).where(PatchPromotion.to_stage_id == stage_qa_id)
        ).all()
        assert len(promos) == 1
        assert promos[0].from_stage_id == stage_dev_id
        assert promos[0].status == "running"
        assert promos[0].patch_scope == "custom"


def test_patch_schedule_notification_fields(engine):
    """PatchSchedule must store notifications JSON and ai_beautify bool with safe defaults."""
    from app.models.patch import PatchPipeline, PipelineStage
    with Session(engine) as db:
        org = Organisation(name="Acme", slug="acme-notif")
        db.add(org)
        db.commit()
        db.refresh(org)
        pipeline = PatchPipeline(org_id=org.id, name="prod", auto_promote=False)
        db.add(pipeline)
        db.commit()
        db.refresh(pipeline)
        grp = MinionGroup(org_id=org.id, name="prod-web")
        db.add(grp)
        db.commit()
        db.refresh(grp)
        stage = PipelineStage(pipeline_id=pipeline.id, group_id=grp.id, order=0, name="prod")
        db.add(stage)
        db.commit()
        db.refresh(stage)

        sched = PatchSchedule(
            pipeline_id=pipeline.id,
            stage_id=stage.id,
            cron_expr="0 2 * * 1",
            patch_scope="security",
            created_by="admin",
        )
        db.add(sched)
        db.commit()
        db.refresh(sched)

        assert sched.notifications == {}
        assert sched.ai_beautify is False

        # Now store notification config and read it back
        import json
        sched.notifications = {
            "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/test"},
            "teams": {"enabled": False, "webhook_url": ""},
            "jira":  {"enabled": False},
        }
        sched.ai_beautify = True
        db.add(sched)
        db.commit()
        db.refresh(sched)

        assert sched.notifications["slack"]["enabled"] is True
        assert sched.notifications["slack"]["webhook_url"] == "https://hooks.slack.com/test"
        assert sched.ai_beautify is True


@pytest.mark.asyncio
async def test_run_scheduled_stage_fires_notification(engine):
    """After apply_patches, send_notifications must be called with the schedule's config."""
    from sqlmodel import Session
    from app.models.patch import PatchPipeline, PipelineStage, PatchSchedule

    with Session(engine) as db:
        org = Organisation(name="NotifOrg", slug="notif-org")
        db.add(org)
        db.commit()
        db.refresh(org)
        grp = MinionGroup(org_id=org.id, name="dev")
        db.add(grp)
        db.commit()
        db.refresh(grp)
        pipeline = PatchPipeline(org_id=org.id, name="dev-pipeline")
        db.add(pipeline)
        db.commit()
        db.refresh(pipeline)
        stage = PipelineStage(pipeline_id=pipeline.id, group_id=grp.id, order=0, name="dev")
        db.add(stage)
        db.commit()
        db.refresh(stage)

        notif_cfg = {"slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/x"}}
        sched = PatchSchedule(
            pipeline_id=pipeline.id,
            stage_id=stage.id,
            cron_expr="0 2 * * 1",
            patch_scope="security",
            created_by="admin",
            notifications=notif_cfg,
            ai_beautify=False,
        )
        db.add(sched)
        db.commit()
        db.refresh(sched)

    from unittest.mock import AsyncMock, patch as mock_patch
    with mock_patch("app.services.patch_service.apply_patches", new_callable=AsyncMock) as mock_apply, \
         mock_patch("app.services.notification_service.send_notifications", new_callable=AsyncMock) as mock_notify:
        mock_apply.return_value = {}
        from app.services.patch_service import run_scheduled_stage
        with mock_patch("app.services.patch_service.engine", engine):
            await run_scheduled_stage(sched)

    mock_notify.assert_awaited_once()
    call_config = mock_notify.call_args[0][0]
    assert call_config == notif_cfg
