# backend/tests/test_env_seeding.py
import pytest
from unittest.mock import patch
from sqlmodel import SQLModel, create_engine, Session, select
from sqlmodel.pool import StaticPool

from app.models.user import User
from app.models.setting import SystemSetting
from app.core.db import seed_from_env


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_settings(**kwargs):
    """Return a mock settings object with DOKOPS_* values."""
    from types import SimpleNamespace
    defaults = dict(
        DOKOPS_FORCE_SEED=False,
        DOKOPS_ADMIN_USERNAME=None,
        DOKOPS_ADMIN_PASSWORD=None,
        DOKOPS_AI_PROVIDER=None,
        DOKOPS_AI_API_KEY=None,
        DOKOPS_AI_MODEL=None,
        DOKOPS_AI_BASE_URL=None,
        DOKOPS_AI_API_VERSION=None,
        DOKOPS_RAG_ENABLED=None,
        DOKOPS_RAG_CHROMA_HOST=None,
        DOKOPS_RAG_CHROMA_PORT=None,
        DOKOPS_SIGNUP_ENABLED=None,
        DOKOPS_SIGNUP_DEFAULT_ROLE=None,
        DOKOPS_RAG_EMBEDDING_PROVIDER=None,
        DOKOPS_RAG_EMBEDDING_API_KEY=None,
        DOKOPS_RAG_EMBEDDING_MODEL=None,
        DOKOPS_RAG_EMBEDDING_BASE_URL=None,
        DOKOPS_ES_URL=None,
        DOKOPS_ES_AUTH_TYPE=None,
        DOKOPS_ES_API_KEY=None,
        DOKOPS_ES_HEADER_NAME=None,
        DOKOPS_ES_USERNAME=None,
        DOKOPS_ES_PASSWORD=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


_FAKE_HASH = "FAKE_BCRYPT_HASH_FOR_TESTING"


# ── Admin user seeding ────────────────────────────────────────────────────────

def test_creates_superuser_when_no_user_exists(session):
    s = _make_settings(DOKOPS_ADMIN_USERNAME="admin", DOKOPS_ADMIN_PASSWORD="secret")
    with patch("app.core.db.get_password_hash", return_value=_FAKE_HASH):
        seed_from_env(session, s)

    user = session.exec(select(User).where(User.username == "admin")).first()
    assert user is not None
    assert user.is_superuser is True
    assert user.role == "admin"
    assert user.is_active is True
    assert user.hashed_password == _FAKE_HASH


def test_skips_user_creation_when_user_exists_no_force(session):
    session.add(User(username="admin", hashed_password="original", is_superuser=True, role="admin", is_active=True))
    session.commit()

    s = _make_settings(DOKOPS_ADMIN_USERNAME="admin", DOKOPS_ADMIN_PASSWORD="newpassword", DOKOPS_FORCE_SEED=False)
    with patch("app.core.db.get_password_hash", return_value="new_hash"):
        seed_from_env(session, s)

    user = session.exec(select(User).where(User.username == "admin")).first()
    assert user.hashed_password == "original"  # unchanged


def test_updates_password_when_user_exists_and_force_seed(session):
    session.add(User(username="admin", hashed_password="original", is_superuser=True, role="admin", is_active=True))
    session.commit()

    s = _make_settings(DOKOPS_ADMIN_USERNAME="admin", DOKOPS_ADMIN_PASSWORD="newpassword", DOKOPS_FORCE_SEED=True)
    with patch("app.core.db.get_password_hash", return_value="new_hash"):
        seed_from_env(session, s)

    user = session.exec(select(User).where(User.username == "admin")).first()
    assert user.hashed_password == "new_hash"


def test_skips_user_seed_when_env_vars_not_set(session):
    s = _make_settings()  # both username and password are None
    seed_from_env(session, s)

    users = session.exec(select(User)).all()
    assert len(users) == 0


# ── SystemSetting seeding ─────────────────────────────────────────────────────

def test_inserts_setting_when_key_missing(session):
    s = _make_settings(DOKOPS_AI_PROVIDER="OPENAI")
    seed_from_env(session, s)

    row = session.exec(select(SystemSetting).where(SystemSetting.key == "ai_provider")).first()
    assert row is not None
    assert row.value == "OPENAI"


def test_skips_setting_when_key_exists_no_force(session):
    session.add(SystemSetting(key="ai_provider", value="GEMINI"))
    session.commit()

    s = _make_settings(DOKOPS_AI_PROVIDER="OPENAI", DOKOPS_FORCE_SEED=False)
    seed_from_env(session, s)

    row = session.exec(select(SystemSetting).where(SystemSetting.key == "ai_provider")).first()
    assert row.value == "GEMINI"  # unchanged


def test_overwrites_setting_when_key_exists_and_force_seed(session):
    session.add(SystemSetting(key="ai_provider", value="GEMINI"))
    session.commit()

    s = _make_settings(DOKOPS_AI_PROVIDER="AZURE", DOKOPS_FORCE_SEED=True)
    seed_from_env(session, s)

    row = session.exec(select(SystemSetting).where(SystemSetting.key == "ai_provider")).first()
    assert row.value == "AZURE"


def test_skips_none_values(session):
    s = _make_settings()  # all None
    seed_from_env(session, s)

    rows = session.exec(select(SystemSetting)).all()
    assert len(rows) == 0


def test_bool_settings_stored_as_lowercase_string(session):
    s = _make_settings(DOKOPS_RAG_ENABLED=True, DOKOPS_SIGNUP_ENABLED=False)
    seed_from_env(session, s)

    rag = session.exec(select(SystemSetting).where(SystemSetting.key == "rag_enabled")).first()
    signup = session.exec(select(SystemSetting).where(SystemSetting.key == "signup_enabled")).first()
    assert rag.value == "true"
    assert signup.value == "false"


def test_seeds_all_tier2_keys(session):
    s = _make_settings(
        DOKOPS_AI_BASE_URL="https://api.openai.com/v1",
        DOKOPS_AI_API_VERSION="2023-05-15",
        DOKOPS_RAG_CHROMA_HOST="chroma-svc",
        DOKOPS_RAG_CHROMA_PORT="8001",
        DOKOPS_SIGNUP_DEFAULT_ROLE="user",
    )
    seed_from_env(session, s)

    expected = {
        "ai_base_url": "https://api.openai.com/v1",
        "ai_api_version": "2023-05-15",
        "rag_chroma_host": "chroma-svc",
        "rag_chroma_port": "8001",
        "signup_default_role": "user",
    }
    for key, expected_value in expected.items():
        row = session.exec(select(SystemSetting).where(SystemSetting.key == key)).first()
        assert row is not None, f"Missing key: {key}"
        assert row.value == expected_value, f"{key}: expected {expected_value!r}, got {row.value!r}"


def test_seeds_all_tier3_keys(session):
    s = _make_settings(
        DOKOPS_RAG_EMBEDDING_PROVIDER="openai",
        DOKOPS_RAG_EMBEDDING_API_KEY="sk-embed",
        DOKOPS_RAG_EMBEDDING_MODEL="text-embedding-3-small",
        DOKOPS_RAG_EMBEDDING_BASE_URL="https://api.openai.com/v1",
    )
    seed_from_env(session, s)

    expected = {
        "rag_embedding_provider": "openai",
        "rag_embedding_api_key": "sk-embed",
        "rag_embedding_model": "text-embedding-3-small",
        "rag_embedding_base_url": "https://api.openai.com/v1",
    }
    for key, expected_value in expected.items():
        row = session.exec(select(SystemSetting).where(SystemSetting.key == key)).first()
        assert row is not None, f"Missing key: {key}"
        assert row.value == expected_value
