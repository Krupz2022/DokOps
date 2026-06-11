# backend/tests/test_integration_manager.py
import pytest
from sqlmodel import SQLModel, create_engine, Session


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    import app.models.integration  # noqa
    import app.models.audit        # noqa
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr("app.core.db.engine", test_engine)
    monkeypatch.setattr("app.services.integration_manager.engine", test_engine)
    yield test_engine


def test_get_active_tool_registry_empty(isolated_db):
    from app.services.integration_manager import IntegrationManager
    mgr = IntegrationManager()
    registry = mgr.get_active_tool_registry()
    assert isinstance(registry, dict)
    assert len(registry) == 0


def test_get_active_tool_registry_with_prometheus(isolated_db):
    from app.models.integration import IntegrationSettings
    from app.services.integrations.base import encrypt_credentials
    from app.services.integration_manager import IntegrationManager

    creds = encrypt_credentials({"token": "mytoken"})
    row = IntegrationSettings(
        backend="prometheus",
        display_name="Test Prom",
        base_url="http://prometheus:9090",
        auth_type="bearer",
        encrypted_credentials=creds,
        is_active=True,
    )
    with Session(isolated_db) as s:
        s.add(row)
        s.commit()

    mgr = IntegrationManager()
    registry = mgr.get_active_tool_registry()
    assert "prometheus_instant_query" in registry
    assert "prometheus_range_query" in registry
    assert "prometheus_list_alert_rules" in registry


def test_inactive_backend_not_included(isolated_db):
    from app.models.integration import IntegrationSettings
    from app.services.integration_manager import IntegrationManager

    row = IntegrationSettings(
        backend="loki",
        display_name="Loki",
        base_url="http://loki:3100",
        is_active=False,
    )
    with Session(isolated_db) as s:
        s.add(row)
        s.commit()

    mgr = IntegrationManager()
    registry = mgr.get_active_tool_registry()
    assert "loki_query_logs" not in registry


def test_get_active_tools_description_for_prompt(isolated_db):
    from app.models.integration import IntegrationSettings
    from app.services.integration_manager import IntegrationManager

    row = IntegrationSettings(
        backend="elasticsearch",
        display_name="ES",
        base_url="http://es:9200",
        is_active=True,
    )
    with Session(isolated_db) as s:
        s.add(row)
        s.commit()

    mgr = IntegrationManager()
    prompt_section = mgr.get_tools_description_for_prompt()
    assert "elasticsearch_search" in prompt_section


def test_registry_is_cached_until_invalidated(isolated_db):
    from app.services.integration_manager import (
        IntegrationManager, invalidate_registry_cache,
    )
    from app.models.integration import IntegrationSettings

    invalidate_registry_cache()
    mgr = IntegrationManager()
    assert mgr.get_active_tool_registry() == {}   # populates cache with empty

    # Add an active integration directly in the DB.
    with Session(isolated_db) as s:
        s.add(IntegrationSettings(
            backend="prometheus",
            display_name="Prom",
            base_url="http://prometheus:9090",
            auth_type="bearer",
            is_active=True,
        ))
        s.commit()

    # Cache still serves the empty snapshot.
    assert mgr.get_active_tool_registry() == {}

    # After invalidation the new tools appear.
    invalidate_registry_cache()
    assert "prometheus_instant_query" in mgr.get_active_tool_registry()
