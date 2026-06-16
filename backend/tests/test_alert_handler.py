# backend/tests/test_alert_handler.py
import asyncio
import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.alert_incident import AlertIncident
from app.models.setting import SystemSetting
from app.services.alert_normalizers import NormalizedAlert
from app.services.alert_handler_service import AlertHandlerService, build_jira_body


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def async_session_factory():
    """Return an async_sessionmaker backed by an in-memory aiosqlite DB.

    Uses a sync fixture (asyncio.run workaround) for pytest-asyncio 0.23.5 + Python 3.13
    compatibility. Each asyncio.run() creates a fresh event loop; safe with aiosqlite.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    asyncio.run(_init())
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def sample_alert():
    return NormalizedAlert(
        fingerprint="fp001",
        source="alertmanager",
        severity="critical",
        alert_name="CrashLoopBackOff",
        description="Pod is crash looping",
        namespace="production",
        pod_name="api-7d9b8c",
        labels={"alertname": "CrashLoopBackOff"},
        raw_payload={},
        received_at=datetime.now(timezone.utc),
    )


# ── Deduplication ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_is_duplicate_returns_false_when_no_existing_incident(
    async_session_factory, sample_alert
):
    svc = AlertHandlerService()
    with patch("app.services.alert_handler_service.AsyncSessionLocal", async_session_factory):
        result = await svc._is_duplicate(sample_alert)
    assert result is False


@pytest.mark.asyncio
async def test_is_duplicate_returns_true_when_open_recent_incident_exists(
    async_session_factory, sample_alert
):
    async with async_session_factory() as db:
        existing = AlertIncident(
            fingerprint="fp001",
            source="alertmanager",
            alert_name="CrashLoopBackOff",
            severity="critical",
            status="rca_running",
            created_at=datetime.now(timezone.utc),
        )
        db.add(existing)
        await db.commit()

    svc = AlertHandlerService()
    with patch("app.services.alert_handler_service.AsyncSessionLocal", async_session_factory):
        result = await svc._is_duplicate(sample_alert)
    assert result is True


@pytest.mark.asyncio
async def test_is_duplicate_returns_false_for_closed_incidents(
    async_session_factory, sample_alert
):
    async with async_session_factory() as db:
        existing = AlertIncident(
            fingerprint="fp001",
            source="alertmanager",
            alert_name="CrashLoopBackOff",
            severity="critical",
            status="closed",
            created_at=datetime.now(timezone.utc),
        )
        db.add(existing)
        await db.commit()

    svc = AlertHandlerService()
    with patch("app.services.alert_handler_service.AsyncSessionLocal", async_session_factory):
        result = await svc._is_duplicate(sample_alert)
    assert result is False


# ── build_jira_body ───────────────────────────────────────────────────────────

def test_build_jira_body_includes_alert_name():
    incident = AlertIncident(
        fingerprint="fp001",
        source="alertmanager",
        alert_name="CrashLoopBackOff",
        severity="critical",
        namespace="production",
        pod_name="api-xyz",
        rca_report=json.dumps([{"type": "result", "message": "The pod OOMKilled due to memory limit"}]),
        evidence=json.dumps({"logs": "OOMKilled\nContainer exit code 137", "events": ""}),
        created_at=datetime.now(timezone.utc),
    )
    body = build_jira_body(incident)
    assert "CrashLoopBackOff" in body
    assert "production" in body


# ── Remediation rate limit ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remediation_rate_limit_blocks_over_threshold(async_session_factory, sample_alert):
    svc = AlertHandlerService()
    # Simulate 3 recent remediations for same alert_name + action
    async with async_session_factory() as db:
        for _ in range(3):
            db.add(AlertIncident(
                fingerprint="other",
                source="alertmanager",
                alert_name="CrashLoopBackOff",
                severity="critical",
                status="remediated",
                remediation_action="restart_pod",
                created_at=datetime.now(timezone.utc),
            ))
        await db.commit()

    with patch("app.services.alert_handler_service.AsyncSessionLocal", async_session_factory):
        # Rule says max_per_hour=3, so 3 already done → should be blocked
        result = await svc._check_remediation_rate_limit("CrashLoopBackOff", "restart_pod", 3)
    assert result is False


@pytest.mark.asyncio
async def test_remediation_rate_limit_allows_under_threshold(async_session_factory):
    svc = AlertHandlerService()
    # Only 1 remediation so far, max is 3
    async with async_session_factory() as db:
        db.add(AlertIncident(
            fingerprint="other",
            source="alertmanager",
            alert_name="CrashLoopBackOff",
            severity="critical",
            status="remediated",
            remediation_action="restart_pod",
            created_at=datetime.now(timezone.utc),
        ))
        await db.commit()

    with patch("app.services.alert_handler_service.AsyncSessionLocal", async_session_factory):
        result = await svc._check_remediation_rate_limit("CrashLoopBackOff", "restart_pod", 3)
    assert result is True


# ── RCA concurrency limit provider ──────────────────────────────────────────────

def test_get_max_concurrent_rca_default_when_unset(monkeypatch):
    import app.services.alert_handler_service as ahs
    monkeypatch.setattr(ahs, "get_setting", lambda key: None)
    assert ahs._get_max_concurrent_rca() == 5


def test_get_max_concurrent_rca_reads_setting(monkeypatch):
    import app.services.alert_handler_service as ahs
    monkeypatch.setattr(ahs, "get_setting", lambda key: "8")
    assert ahs._get_max_concurrent_rca() == 8


def test_get_max_concurrent_rca_falls_back_on_garbage(monkeypatch):
    import app.services.alert_handler_service as ahs
    monkeypatch.setattr(ahs, "get_setting", lambda key: "not-a-number")
    assert ahs._get_max_concurrent_rca() == 5


def test_get_max_concurrent_rca_floors_at_one(monkeypatch):
    import app.services.alert_handler_service as ahs
    monkeypatch.setattr(ahs, "get_setting", lambda key: "0")
    assert ahs._get_max_concurrent_rca() == 5


# ── Pipeline runs under the RCA gate ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_pipeline_acquires_gate(async_session_factory, sample_alert, monkeypatch):
    """Peak concurrent _run_pipeline bodies must not exceed the configured limit."""
    import app.services.alert_handler_service as ahs

    monkeypatch.setattr(ahs, "get_setting", lambda key: "2")   # limit = 2

    svc = ahs.AlertHandlerService()
    active = 0
    peak = 0

    async def fake_collect(incident):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return {}

    # Neutralise every step except the gate + the probe in _collect_evidence.
    monkeypatch.setattr(svc, "_collect_evidence", fake_collect)
    monkeypatch.setattr(svc, "_run_rca", AsyncMock(return_value=[]))
    monkeypatch.setattr(svc, "_create_jira_ticket", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_notify", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_trigger_workflows", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_maybe_remediate", AsyncMock(return_value=None))

    async def make_incident(i):
        return AlertIncident(
            id=None, fingerprint=f"fp{i}", source="alertmanager",
            alert_name="X", severity="critical", status="pending",
            created_at=datetime.now(timezone.utc),
        )

    with patch("app.services.alert_handler_service.AsyncSessionLocal", async_session_factory):
        incidents = []
        async with async_session_factory() as db:
            for i in range(6):
                inc = await make_incident(i)
                db.add(inc)
            await db.commit()
            from sqlmodel import select as _select
            incidents = (await db.exec(_select(AlertIncident))).all()

        await asyncio.gather(*(svc._run_pipeline(inc, sample_alert) for inc in incidents))

    assert peak <= 2
    assert peak == 2          # gate allowed exactly the limit concurrently


# ── Recovery-safety guards ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_jira_ticket_skips_when_already_ticketed(async_session_factory):
    svc = AlertHandlerService()
    incident = AlertIncident(
        id=1, fingerprint="fp1", source="alertmanager", alert_name="X",
        severity="critical", status="rca_running",
        jira_ticket_key="DOK-123", created_at=datetime.now(timezone.utc),
    )
    with patch("app.services.alert_handler_service.AsyncSessionLocal", async_session_factory):
        result = await svc._create_jira_ticket(incident)
    assert result == "DOK-123"   # returns the existing key, creates nothing


@pytest.mark.asyncio
async def test_notify_skips_when_already_sent():
    svc = AlertHandlerService()
    incident = AlertIncident(
        id=1, fingerprint="fp1", source="alertmanager", alert_name="X",
        severity="critical", status="rca_running",
        notification_sent_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    # Guard must short-circuit BEFORE any DB session is opened. If _notify opens
    # AsyncSessionLocal, this side-effect raises and the test fails.
    mock_session_factory = MagicMock(side_effect=AssertionError("DB must not be opened on early return"))
    with patch("app.services.alert_handler_service.AsyncSessionLocal", mock_session_factory):
        await svc._notify(incident)   # must not raise


# ── Recovery sweep ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recover_interrupted_selects_only_pre_sideeffect_statuses(
    async_session_factory, monkeypatch
):
    import app.services.alert_handler_service as ahs

    svc = ahs.AlertHandlerService()
    ahs._recovered_ids.clear()

    before = datetime(2020, 1, 1, tzinfo=timezone.utc)   # well before _PROCESS_START
    statuses = ["pending", "collecting", "rca_running", "notified", "remediated", "closed"]
    async with async_session_factory() as db:
        for i, st in enumerate(statuses):
            db.add(AlertIncident(
                fingerprint=f"fp{i}", source="alertmanager", alert_name="X",
                severity="critical", status=st, created_at=before,
            ))
        await db.commit()

    scheduled: list[int] = []
    monkeypatch.setattr(svc, "handle_recovery", AsyncMock(side_effect=lambda iid: scheduled.append(iid)))

    with patch("app.services.alert_handler_service.AsyncSessionLocal", async_session_factory):
        await svc.recover_interrupted()
        await asyncio.sleep(0.01)   # let create_task'd recoveries run

        async with async_session_factory() as db:
            from sqlmodel import select as _select
            rows = (await db.exec(_select(AlertIncident))).all()
            by_fp = {r.fingerprint: r.status for r in rows}

    assert by_fp["fp0"] == "interrupted"
    assert by_fp["fp1"] == "interrupted"
    assert by_fp["fp2"] == "interrupted"
    assert by_fp["fp3"] == "notified"
    assert by_fp["fp4"] == "remediated"
    assert by_fp["fp5"] == "closed"
    assert len(scheduled) == 3


@pytest.mark.asyncio
async def test_recover_interrupted_ignores_incidents_created_after_process_start(
    async_session_factory, monkeypatch
):
    import app.services.alert_handler_service as ahs
    svc = ahs.AlertHandlerService()
    ahs._recovered_ids.clear()

    after = datetime.now(timezone.utc) + timedelta(hours=1)  # after _PROCESS_START
    async with async_session_factory() as db:
        db.add(AlertIncident(
            fingerprint="fresh", source="alertmanager", alert_name="X",
            severity="critical", status="pending", created_at=after,
        ))
        await db.commit()

    monkeypatch.setattr(svc, "handle_recovery", AsyncMock())
    with patch("app.services.alert_handler_service.AsyncSessionLocal", async_session_factory):
        await svc.recover_interrupted()
        await asyncio.sleep(0.01)
        async with async_session_factory() as db:
            from sqlmodel import select as _select
            row = (await db.exec(_select(AlertIncident))).first()
    assert row.status == "pending"   # untouched
    svc.handle_recovery.assert_not_called()


@pytest.mark.asyncio
async def test_recover_interrupted_poison_guard_skips_seen_ids(
    async_session_factory, monkeypatch
):
    import app.services.alert_handler_service as ahs
    svc = ahs.AlertHandlerService()
    ahs._recovered_ids.clear()

    before = datetime(2020, 1, 1, tzinfo=timezone.utc)
    async with async_session_factory() as db:
        db.add(AlertIncident(
            fingerprint="fp1", source="alertmanager", alert_name="X",
            severity="critical", status="rca_running", created_at=before,
        ))
        await db.commit()

    monkeypatch.setattr(svc, "handle_recovery", AsyncMock())
    with patch("app.services.alert_handler_service.AsyncSessionLocal", async_session_factory):
        await svc.recover_interrupted()
        await asyncio.sleep(0.01)
        first_calls = svc.handle_recovery.call_count
        await svc.recover_interrupted()   # second sweep, same process
        await asyncio.sleep(0.01)
        second_calls = svc.handle_recovery.call_count

    assert first_calls == 1
    assert second_calls == 1   # not re-scheduled the second time


def test_alert_from_incident_roundtrips_core_fields():
    svc = AlertHandlerService()
    incident = AlertIncident(
        id=7, fingerprint="fp7", source="grafana", alert_name="HighMem",
        severity="warning", namespace="prod", pod_name="api-1",
        created_at=datetime.now(timezone.utc),
    )
    alert = svc._alert_from_incident(incident)
    assert alert.fingerprint == "fp7"
    assert alert.source == "grafana"
    assert alert.alert_name == "HighMem"
    assert alert.severity == "warning"
    assert alert.namespace == "prod"
    assert alert.pod_name == "api-1"


@pytest.mark.asyncio
async def test_handle_recovery_runs_pipeline_once_without_duplicate_sideeffects(
    async_session_factory, monkeypatch
):
    import app.services.alert_handler_service as ahs
    monkeypatch.setattr(ahs, "get_setting", lambda key: "5")
    svc = ahs.AlertHandlerService()

    jira = AsyncMock(return_value="DOK-1")
    notify = AsyncMock(return_value=None)
    monkeypatch.setattr(svc, "_collect_evidence", AsyncMock(return_value={"logs": "x"}))
    monkeypatch.setattr(svc, "_run_rca", AsyncMock(return_value=[{"type": "result", "message": "ok"}]))
    monkeypatch.setattr(svc, "_create_jira_ticket", jira)
    monkeypatch.setattr(svc, "_notify", notify)
    monkeypatch.setattr(svc, "_trigger_workflows", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_maybe_remediate", AsyncMock(return_value=None))

    async with async_session_factory() as db:
        inc = AlertIncident(
            fingerprint="fp1", source="alertmanager", alert_name="X",
            severity="critical", status="rca_running",
            created_at=datetime.now(timezone.utc),
        )
        db.add(inc)
        await db.commit()
        await db.refresh(inc)
        incident_id = inc.id

    with patch("app.services.alert_handler_service.AsyncSessionLocal", async_session_factory):
        await svc.handle_recovery(incident_id)

    assert jira.await_count == 1
    assert notify.await_count == 1
    async with async_session_factory() as db:
        fresh = await db.get(AlertIncident, incident_id)
    assert fresh.rca_report is not None
    assert fresh.status in ("notified", "remediated")
