# backend/tests/test_alert_handler.py
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from sqlmodel import Session, create_engine, SQLModel

from app.models.alert_incident import AlertIncident
from app.services.alert_normalizers import NormalizedAlert
from app.services.alert_handler_service import AlertHandlerService, build_jira_body


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def in_memory_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


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

def test_is_duplicate_returns_false_when_no_existing_incident(in_memory_db, sample_alert):
    svc = AlertHandlerService()
    assert svc._is_duplicate(sample_alert, in_memory_db) is False


def test_is_duplicate_returns_true_when_open_recent_incident_exists(in_memory_db, sample_alert):
    existing = AlertIncident(
        fingerprint="fp001",
        source="alertmanager",
        alert_name="CrashLoopBackOff",
        severity="critical",
        status="rca_running",
        created_at=datetime.now(timezone.utc),
    )
    in_memory_db.add(existing)
    in_memory_db.commit()

    svc = AlertHandlerService()
    assert svc._is_duplicate(sample_alert, in_memory_db) is True


def test_is_duplicate_returns_false_for_closed_incidents(in_memory_db, sample_alert):
    existing = AlertIncident(
        fingerprint="fp001",
        source="alertmanager",
        alert_name="CrashLoopBackOff",
        severity="critical",
        status="closed",
        created_at=datetime.now(timezone.utc),
    )
    in_memory_db.add(existing)
    in_memory_db.commit()

    svc = AlertHandlerService()
    assert svc._is_duplicate(sample_alert, in_memory_db) is False


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

def test_remediation_rate_limit_blocks_over_threshold(in_memory_db, sample_alert):
    svc = AlertHandlerService()
    # Simulate 3 recent remediations for same alert_name + action
    for _ in range(3):
        in_memory_db.add(AlertIncident(
            fingerprint="other",
            source="alertmanager",
            alert_name="CrashLoopBackOff",
            severity="critical",
            status="remediated",
            remediation_action="restart_pod",
            created_at=datetime.now(timezone.utc),
        ))
    in_memory_db.commit()

    # Rule says max_per_hour=3, so 3 already done → should be blocked
    result = svc._check_remediation_rate_limit("CrashLoopBackOff", "restart_pod", 3, in_memory_db)
    assert result is False


def test_remediation_rate_limit_allows_under_threshold(in_memory_db):
    svc = AlertHandlerService()
    # Only 1 remediation so far, max is 3
    in_memory_db.add(AlertIncident(
        fingerprint="other",
        source="alertmanager",
        alert_name="CrashLoopBackOff",
        severity="critical",
        status="remediated",
        remediation_action="restart_pod",
        created_at=datetime.now(timezone.utc),
    ))
    in_memory_db.commit()

    result = svc._check_remediation_rate_limit("CrashLoopBackOff", "restart_pod", 3, in_memory_db)
    assert result is True
