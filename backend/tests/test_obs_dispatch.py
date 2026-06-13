import pytest
from sqlmodel import SQLModel, create_engine, Session
import json


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    import app.models.integration  # noqa
    import app.models.audit        # noqa
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr("app.core.db.sync_engine", test_engine)
    monkeypatch.setattr("app.services.integration_manager.sync_engine", test_engine)
    yield test_engine


def test_integration_tools_included_in_schema(isolated_db):
    """When Prometheus is active, prometheus_instant_query appears in the OpenAI tools schema."""
    from app.models.integration import IntegrationSettings
    from app.services.integrations.base import encrypt_credentials
    from app.services.integration_manager import IntegrationManager

    creds = encrypt_credentials({"token": "t"})
    with Session(isolated_db) as s:
        s.add(IntegrationSettings(
            backend="prometheus", display_name="P", base_url="http://prom:9090",
            auth_type="bearer", encrypted_credentials=creds, is_active=True,
        ))
        s.commit()

    from app.tools import registry as _registry
    mgr = IntegrationManager()
    obs_registry = mgr.get_active_tool_registry()

    extra_tools = [
        {"name": name, "description": info["description"]}
        for name, info in obs_registry.items()
    ]
    schema = _registry.build_openai_tools_schema(extra_tools=extra_tools)
    names = [t["function"]["name"] for t in schema]
    assert "prometheus_instant_query" in names
