import asyncio
from datetime import datetime, timedelta
from sqlmodel import SQLModel, create_engine, Session
from fastapi.testclient import TestClient
import pytest

from app.models.analytics import AITokenUsage
from app.models.user import User  # noqa: F401 - Required for foreign key table creation
from app.core.token_context import set_token_context, push_token_usage, _token_queue
from app.core.datetimes import utcnow

import app.models.analytics  # noqa
import app.models.audit      # noqa
import app.models.setting    # noqa


# ── Fixtures for API-level tests — delegate to shared conftest fixtures ───────

@pytest.fixture(name="session")
def session_fixture(isolated_session):
    return isolated_session


@pytest.fixture(name="client")
def client_fixture(isolated_client):
    return isolated_client


@pytest.fixture(name="superuser_token_headers")
def superuser_token_headers_fixture(session: Session, client: TestClient):
    from app.core import security

    user = User(
        username="admin",
        hashed_password=security.get_password_hash("pass123"),
        is_active=True,
        is_superuser=True,
        role="admin",
    )
    session.add(user)
    session.commit()
    resp = client.post(
        "/api/v1/login/access-token", data={"username": "admin", "password": "pass123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ── Unit tests ────────────────────────────────────────────────────────────────

def test_aitokenusage_table_creates():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(AITokenUsage(user_id=1, source="chat", model="gpt-4o", input_tokens=100, output_tokens=50))
        db.commit()
        row = db.get(AITokenUsage, 1)
    assert row.source == "chat"
    assert row.input_tokens == 100


def test_push_token_usage_enqueues_record():
    # Drain any leftover items from queue first
    while not _token_queue.empty():
        try:
            _token_queue.get_nowait()
        except Exception:
            break

    set_token_context(user_id=42, source="chat")
    asyncio.run(push_token_usage("gpt-4o", 200, 80))
    record = _token_queue.get_nowait()
    assert record["user_id"] == 42
    assert record["source"] == "chat"
    assert record["model"] == "gpt-4o"
    assert record["input_tokens"] == 200
    assert record["output_tokens"] == 80


# ── API-level test ────────────────────────────────────────────────────────────

def test_get_token_analytics_returns_structure(client, superuser_token_headers):
    now = utcnow()
    res = client.get(
        "/api/v1/analytics/tokens",
        params={"start": (now - timedelta(days=7)).isoformat(), "end": now.isoformat()},
        headers=superuser_token_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert "summary" in data
    assert "daily" in data
    assert "by_source" in data
    assert "by_model" in data
    assert "by_user" in data


def test_summary_includes_cached_tokens_field():
    """AITokenUsage model must have a cached_tokens field."""
    from app.models.analytics import AITokenUsage
    assert "cached_tokens" in AITokenUsage.model_fields


def test_summary_cached_tokens_aggregated_correctly(client, superuser_token_headers, session):
    """Insert rows with cached_tokens, call the analytics endpoint, verify the total is returned."""
    # Insert two rows with known cached_tokens values
    session.add(AITokenUsage(
        source="agent", model="gpt-4o",
        input_tokens=500, output_tokens=100, cached_tokens=200,
    ))
    session.add(AITokenUsage(
        source="chat", model="gpt-4o",
        input_tokens=300, output_tokens=50, cached_tokens=150,
    ))
    session.commit()

    now = utcnow()
    res = client.get(
        "/api/v1/analytics/tokens",
        params={"start": (now - timedelta(days=7)).isoformat(), "end": now.isoformat()},
        headers=superuser_token_headers,
    )
    assert res.status_code == 200
    summary = res.json()["summary"]
    assert "cached_tokens" in summary
    assert summary["cached_tokens"] == 350  # 200 + 150


def test_bucket_for_span_thresholds():
    from app.api.v1.analytics import _bucket_for_span
    end = utcnow()
    assert _bucket_for_span(end - timedelta(days=7), end) == "day"
    assert _bucket_for_span(end - timedelta(days=31), end) == "day"
    assert _bucket_for_span(end - timedelta(days=32), end) == "week"
    assert _bucket_for_span(end - timedelta(days=180), end) == "week"
    assert _bucket_for_span(end - timedelta(days=181), end) == "month"
    assert _bucket_for_span(end - timedelta(days=365), end) == "month"


def test_resolve_range_rejects_inverted():
    from fastapi import HTTPException
    from app.api.v1.analytics import _resolve_range
    end = utcnow()
    with pytest.raises(HTTPException) as exc:
        _resolve_range(end, end - timedelta(days=1))
    assert exc.value.status_code == 422


def test_resolve_range_clamps_to_366_days():
    from app.api.v1.analytics import _resolve_range
    end = utcnow()
    start = end - timedelta(days=900)
    out_start, out_end, gran = _resolve_range(start, end)
    assert (out_end - out_start).days == 366
    assert gran == "month"


def test_tokens_endpoint_accepts_start_end_and_returns_granularity(
    client, superuser_token_headers, session
):
    session.add(AITokenUsage(
        source="agent", model="gpt-4o",
        input_tokens=500, output_tokens=100, cached_tokens=0,
    ))
    session.commit()
    now = utcnow()
    start = (now - timedelta(days=7)).isoformat()
    end = (now + timedelta(seconds=1)).isoformat()
    res = client.get(
        "/api/v1/analytics/tokens",
        params={"start": start, "end": end},
        headers=superuser_token_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["granularity"] == "day"
    assert data["summary"]["total_tokens"] == 600
    assert {"summary", "daily", "by_source", "by_model", "by_user"} <= data.keys()


def test_tokens_endpoint_rejects_inverted_range(client, superuser_token_headers):
    now = utcnow()
    res = client.get(
        "/api/v1/analytics/tokens",
        params={"start": now.isoformat(), "end": (now - timedelta(days=1)).isoformat()},
        headers=superuser_token_headers,
    )
    assert res.status_code == 422


def test_tokens_endpoint_buckets_long_range_by_month(
    client, superuser_token_headers, session
):
    now = utcnow()
    session.add(AITokenUsage(
        source="agent", model="gpt-4o", input_tokens=10, output_tokens=5,
        created_at=now - timedelta(days=200),
    ))
    session.add(AITokenUsage(
        source="agent", model="gpt-4o", input_tokens=20, output_tokens=5,
        created_at=now - timedelta(days=10),
    ))
    session.commit()
    res = client.get(
        "/api/v1/analytics/tokens",
        params={"start": (now - timedelta(days=300)).isoformat(), "end": now.isoformat()},
        headers=superuser_token_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["granularity"] == "month"
    # two rows in distinct months -> two month buckets
    assert len(data["daily"]) == 2
