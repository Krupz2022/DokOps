# backend/tests/test_settings_cache.py
import pytest
from sqlmodel import SQLModel, create_engine, Session


@pytest.fixture
def isolated_db(monkeypatch):
    test_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    import app.models.setting  # noqa: F401
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr("app.core.db.engine", test_engine)
    monkeypatch.setattr("app.core.db.sync_engine", test_engine)
    # Invalidate any cached settings snapshot from a previous test.
    from app.core import settings_cache
    settings_cache.invalidate()
    yield test_engine
    settings_cache.invalidate()


def _insert(engine, key, value):
    from app.models.setting import SystemSetting
    with Session(engine) as s:
        s.add(SystemSetting(key=key, value=value))
        s.commit()


def test_get_setting_returns_value(isolated_db):
    from app.core import settings_cache
    _insert(isolated_db, "ai_provider", "OPENAI")
    assert settings_cache.get_setting("ai_provider") == "OPENAI"


def test_get_setting_missing_returns_none(isolated_db):
    from app.core import settings_cache
    assert settings_cache.get_setting("does_not_exist") is None


def test_value_is_cached_until_invalidated(isolated_db):
    from app.core import settings_cache
    from app.models.setting import SystemSetting
    _insert(isolated_db, "ai_model", "gpt-4o")
    assert settings_cache.get_setting("ai_model") == "gpt-4o"

    # Mutate the DB directly behind the cache's back.
    with Session(isolated_db) as s:
        row = s.get(SystemSetting, "ai_model")
        row.value = "gpt-5"
        s.add(row)
        s.commit()

    # Still serving the cached value.
    assert settings_cache.get_setting("ai_model") == "gpt-4o"

    # After invalidation the fresh value is loaded.
    settings_cache.invalidate()
    assert settings_cache.get_setting("ai_model") == "gpt-5"


def test_ai_service_get_setting_uses_cache(isolated_db):
    from app.services.ai_service import ai_service
    from app.core import settings_cache
    _insert(isolated_db, "ai_provider", "AZURE")
    assert ai_service._get_setting("ai_provider") == "AZURE"
    # Delegation means the shared snapshot is now populated:
    assert settings_cache._cache.get(settings_cache._ALL_KEY) is not None
