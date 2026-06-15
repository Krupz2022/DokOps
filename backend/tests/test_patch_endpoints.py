"""Integration tests for retry/exclude/alert patching endpoints."""
import asyncio
import json
import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlmodel import create_engine, Session, SQLModel, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from unittest.mock import AsyncMock, patch

from app.models.patch import (
    Organisation, MinionGroup, MinionGroupMember,
    PatchPipeline, PipelineStage, PatchPromotion, PatchAlertEvent,
)
from app.models.minion import Minion
from app.models.user import User


@pytest.fixture(name="engine")
def engine_fixture():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(name="client")
def client_fixture(engine):
    from app.main import app
    from app.api.deps import get_async_db, get_current_user, require_god_mode

    db_url = str(engine.url)
    async_url = db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    _async_engine = create_async_engine(async_url, connect_args={"check_same_thread": False})
    _AsyncSessionLocal = async_sessionmaker(_async_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_async_db():
        async with _AsyncSessionLocal() as session:
            yield session

    god_user = User(username="admin", email="admin@test.com", hashed_password="x", role="god")

    app.dependency_overrides[get_async_db] = override_async_db
    app.dependency_overrides[get_current_user] = lambda: god_user
    app.dependency_overrides[require_god_mode] = lambda: god_user

    with patch("app.services.patch_service.AsyncSessionLocal", _AsyncSessionLocal), \
         patch("app.core.db.engine", engine), \
         patch("app.services.connectors.confluence_connector.sync_engine", engine):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()
    asyncio.run(_async_engine.dispose())


def _seed_partial_promo(engine):
    with Session(engine) as db:
        org = Organisation(name="T", slug="t")
        db.add(org); db.flush()
        pipeline = PatchPipeline(org_id=org.id, name="p", auto_promote=False)
        db.add(pipeline); db.flush()
        grp = MinionGroup(org_id=org.id, name="dev")
        db.add(grp); db.flush()
        stage = PipelineStage(pipeline_id=pipeline.id, group_id=grp.id, order=0, name="dev")
        db.add(stage); db.flush()
        m = Minion(id="m-1", hostname="h1", status="active", grains='{"os":"Ubuntu"}')
        db.add(m)
        db.add(MinionGroupMember(group_id=grp.id, minion_id="m-1"))
        promo = PatchPromotion(
            pipeline_id=pipeline.id, to_stage_id=stage.id,
            patch_scope="security", triggered_by="test",
            status="partial",
            custom_packages='["nginx"]',
            failed_minions='["m-1"]',
        )
        db.add(promo); db.commit(); db.refresh(promo)
        return promo.id, stage.id, grp.id


def test_retry_failed_minions_success(client, engine):
    promo_id, stage_id, group_id = _seed_partial_promo(engine)

    with patch("app.services.minion_service.manager") as mock_mgr:
        mock_mgr.dispatch_job = AsyncMock(return_value={"exit_code": 0, "output": ""})
        mock_mgr._connections = {}
        resp = client.post(f"/api/v1/patches/promotions/{promo_id}/retry")

    assert resp.status_code == 200
    with Session(engine) as db:
        promo = db.get(PatchPromotion, promo_id)
        assert promo.status == "done"
        assert json.loads(promo.failed_minions or "[]") == []


def test_retry_failed_minions_still_fails(client, engine):
    promo_id, stage_id, group_id = _seed_partial_promo(engine)

    with patch("app.services.minion_service.manager") as mock_mgr:
        mock_mgr.dispatch_job = AsyncMock(return_value={"exit_code": 1, "output": ""})
        mock_mgr._connections = {}
        resp = client.post(f"/api/v1/patches/promotions/{promo_id}/retry")

    assert resp.status_code == 200
    with Session(engine) as db:
        promo = db.get(PatchPromotion, promo_id)
        assert promo.status == "failed"


def test_exclude_minion_resolves_partial(client, engine):
    promo_id, stage_id, group_id = _seed_partial_promo(engine)

    resp = client.post(
        f"/api/v1/patches/promotions/{promo_id}/exclude/m-1",
        json={"reason": "decommissioning"},
    )
    assert resp.status_code == 200
    with Session(engine) as db:
        promo = db.get(PatchPromotion, promo_id)
        assert promo.status == "done"
        excluded = json.loads(promo.excluded_minions or "[]")
        assert len(excluded) == 1
        assert excluded[0]["id"] == "m-1"
        assert excluded[0]["reason"] == "decommissioning"


def test_acknowledge_alert(client, engine):
    with Session(engine) as db:
        org = Organisation(name="X", slug="x"); db.add(org); db.flush()
        pipeline = PatchPipeline(org_id=org.id, name="p2"); db.add(pipeline); db.flush()
        grp = MinionGroup(org_id=org.id, name="g"); db.add(grp); db.flush()
        stage = PipelineStage(pipeline_id=pipeline.id, group_id=grp.id, order=0, name="dev")
        db.add(stage); db.flush()
        alert = PatchAlertEvent(
            pipeline_id=pipeline.id, stage_id=stage.id, reason="prior_stage_failed"
        )
        db.add(alert); db.commit(); db.refresh(alert)
        alert_id = alert.id

    resp = client.post(f"/api/v1/patches/alerts/{alert_id}/acknowledge")
    assert resp.status_code == 200
    with Session(engine) as db:
        a = db.get(PatchAlertEvent, alert_id)
        assert a.acknowledged is True
        assert a.acknowledged_by == "admin"


@pytest.fixture
def god_headers():
    """Auth headers — require_god_mode is overridden in the client fixture, so this can be empty."""
    return {}


@pytest.fixture
def pipeline_with_stage(client, engine, god_headers):
    """Create a pipeline + stage directly in DB and return (pipeline_id, stage_id)."""
    from sqlmodel import Session
    from app.models.patch import Organisation, MinionGroup, PatchPipeline, PipelineStage
    with Session(engine) as db:
        org = Organisation(name="FixtureOrg", slug="fixture-org-api")
        db.add(org)
        db.commit()
        db.refresh(org)
        grp = MinionGroup(org_id=org.id, name="fixture-grp")
        db.add(grp)
        db.commit()
        db.refresh(grp)
        pipeline = PatchPipeline(org_id=org.id, name="fixture-pipeline")
        db.add(pipeline)
        db.commit()
        db.refresh(pipeline)
        stage = PipelineStage(pipeline_id=pipeline.id, group_id=grp.id, order=0, name="dev")
        db.add(stage)
        db.commit()
        db.refresh(stage)
        pipeline_id = pipeline.id
        stage_id = stage.id
    return pipeline_id, stage_id


@pytest.fixture
def existing_schedule(client, god_headers, pipeline_with_stage):
    """Create a schedule via API and return its id."""
    from unittest.mock import MagicMock, patch as mock_patch
    pipeline_id, stage_id = pipeline_with_stage
    payload = {
        "pipeline_id": pipeline_id,
        "stage_id": stage_id,
        "cron_expr": "0 2 * * 1",
        "timezone": "UTC",
        "patch_scope": "security",
    }
    with mock_patch("app.main.scheduler") as mock_sched:
        mock_sched.add_job = MagicMock()
        r = client.post("/api/v1/patches/schedules/", json=payload, headers=god_headers)
    return r.json()["id"]


def test_create_schedule_with_notifications(client, god_headers, pipeline_with_stage):
    """POST /patches/schedules/ must accept and persist notifications + ai_beautify."""
    from unittest.mock import MagicMock, patch as mock_patch
    pipeline_id, stage_id = pipeline_with_stage
    payload = {
        "pipeline_id": pipeline_id,
        "stage_id": stage_id,
        "cron_expr": "0 3 * * 2",
        "timezone": "UTC",
        "patch_scope": "security",
        "notifications": {
            "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/x"},
            "teams": {"enabled": False, "webhook_url": ""},
            "jira":  {"enabled": False},
        },
        "ai_beautify": True,
    }
    with mock_patch("app.main.scheduler") as mock_sched:
        mock_sched.add_job = MagicMock()
        r = client.post("/api/v1/patches/schedules/", json=payload, headers=god_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["ai_beautify"] is True
    assert data["notifications"]["slack"]["enabled"] is True
    assert data["notifications"]["slack"]["webhook_url"] == "https://hooks.slack.com/x"


def test_update_schedule_notifications(client, god_headers, existing_schedule):
    """PATCH /patches/schedules/{id} with body must update notifications and ai_beautify."""
    from unittest.mock import MagicMock, patch as mock_patch
    schedule_id = existing_schedule
    update_payload = {
        "notifications": {
            "teams": {"enabled": True, "webhook_url": "https://outlook.office.com/webhook/y"},
        },
        "ai_beautify": True,
    }
    with mock_patch("app.main.scheduler") as mock_sched:
        mock_sched.add_job = MagicMock()
        r = client.patch(f"/api/v1/patches/schedules/{schedule_id}", json=update_payload, headers=god_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["ai_beautify"] is True
    assert data["notifications"]["teams"]["enabled"] is True


def test_update_schedule_toggle_via_enabled_field(client, god_headers, existing_schedule):
    """PATCH with {enabled: false} must disable the schedule."""
    from unittest.mock import MagicMock, patch as mock_patch
    schedule_id = existing_schedule
    with mock_patch("app.main.scheduler") as mock_sched:
        mock_sched.remove_job = MagicMock()
        r = client.patch(f"/api/v1/patches/schedules/{schedule_id}", json={"enabled": False}, headers=god_headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_list_alerts_returns_unacknowledged(client, engine):
    with Session(engine) as db:
        org = Organisation(name="Y", slug="y"); db.add(org); db.flush()
        pipeline = PatchPipeline(org_id=org.id, name="p3"); db.add(pipeline); db.flush()
        grp = MinionGroup(org_id=org.id, name="g2"); db.add(grp); db.flush()
        stage = PipelineStage(pipeline_id=pipeline.id, group_id=grp.id, order=0, name="dev")
        db.add(stage); db.flush()
        # One unacknowledged alert
        a1 = PatchAlertEvent(pipeline_id=pipeline.id, stage_id=stage.id, reason="no_prior_run")
        db.add(a1)
        # One acknowledged alert (should NOT appear)
        a2 = PatchAlertEvent(
            pipeline_id=pipeline.id, stage_id=stage.id, reason="prior_stage_failed",
            acknowledged=True, acknowledged_by="admin",
        )
        db.add(a2)
        db.commit()

    resp = client.get("/api/v1/patches/alerts/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["reason"] == "no_prior_run"
    assert data[0]["acknowledged"] is False
