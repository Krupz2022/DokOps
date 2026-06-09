import pytest
from sqlmodel import SQLModel, create_engine, Session
from datetime import datetime, timezone


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    import app.models.integration  # noqa — registers IntegrationSettings with metadata
    import app.models.audit        # noqa
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr("app.core.db.engine", test_engine)
    yield test_engine


def test_integration_settings_create_and_read(isolated_db):
    from app.models.integration import IntegrationSettings
    engine = isolated_db
    row = IntegrationSettings(
        backend="prometheus",
        display_name="My Prom",
        base_url="http://prometheus:9090",
        auth_type="bearer",
        encrypted_credentials='{"token":"abc"}',
        is_active=True,
    )
    with Session(engine) as s:
        s.add(row)
        s.commit()
        s.refresh(row)
        assert row.id is not None

    with Session(engine) as s:
        found = s.get(IntegrationSettings, row.id)
        assert found.backend == "prometheus"
        assert found.is_active is True


def test_integration_settings_defaults():
    from app.models.integration import IntegrationSettings
    row = IntegrationSettings(backend="loki", display_name="Loki", base_url="http://loki:3100")
    assert row.auth_type == "none"
    assert row.is_active is False
    assert row.encrypted_credentials is None
