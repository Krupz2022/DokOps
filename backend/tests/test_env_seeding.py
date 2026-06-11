# backend/tests/test_env_seeding.py
import asyncio
import pytest
from unittest.mock import patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.pool import StaticPool

from app.models.user import User
from app.models.setting import SystemSetting
from app.core.db import seed_from_env


def _make_async_session():
    """Create an async in-memory SQLite engine and return (engine, session_factory)."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


@pytest.fixture(name="session")
def session_fixture():
    """Synchronous fixture that yields an AsyncSession via asyncio.run().

    Workaround for pytest-asyncio 0.23.5 + Python 3.13 async-fixture bug. Each
    asyncio.run() uses a fresh event loop, so __aenter__/__aexit__ run on
    different loops — safe with aiosqlite (thread-backed), NOT safe with
    native-asyncio drivers like asyncpg. Revisit if the test driver changes.
    """
    engine, session_factory = _make_async_session()

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        return session_factory()

    sess_cm = asyncio.run(_setup())

    async def _enter():
        return await sess_cm.__aenter__()

    session = asyncio.run(_enter())

    yield session

    async def _teardown():
        await sess_cm.__aexit__(None, None, None)
        await engine.dispose()

    asyncio.run(_teardown())


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
        asyncio.run(seed_from_env(session, s))

    user = asyncio.run(session.exec(select(User).where(User.username == "admin")))
    user = user.first()
    assert user is not None
    assert user.is_superuser is True
    assert user.role == "admin"
    assert user.is_active is True
    assert user.hashed_password == _FAKE_HASH


def test_skips_user_creation_when_user_exists_no_force(session):
    session.add(User(username="admin", hashed_password="original", is_superuser=True, role="admin", is_active=True))
    asyncio.run(session.commit())

    s = _make_settings(DOKOPS_ADMIN_USERNAME="admin", DOKOPS_ADMIN_PASSWORD="newpassword", DOKOPS_FORCE_SEED=False)
    with patch("app.core.db.get_password_hash", return_value="new_hash"):
        asyncio.run(seed_from_env(session, s))

    user = asyncio.run(session.exec(select(User).where(User.username == "admin")))
    user = user.first()
    assert user.hashed_password == "original"  # unchanged


def test_updates_password_when_user_exists_and_force_seed(session):
    session.add(User(username="admin", hashed_password="original", is_superuser=True, role="admin", is_active=True))
    asyncio.run(session.commit())

    s = _make_settings(DOKOPS_ADMIN_USERNAME="admin", DOKOPS_ADMIN_PASSWORD="newpassword", DOKOPS_FORCE_SEED=True)
    with patch("app.core.db.get_password_hash", return_value="new_hash"):
        asyncio.run(seed_from_env(session, s))

    user = asyncio.run(session.exec(select(User).where(User.username == "admin")))
    user = user.first()
    assert user.hashed_password == "new_hash"


def test_skips_user_seed_when_env_vars_not_set(session):
    s = _make_settings()  # both username and password are None
    asyncio.run(seed_from_env(session, s))

    users = asyncio.run(session.exec(select(User)))
    assert len(users.all()) == 0


# ── SystemSetting seeding ─────────────────────────────────────────────────────

def test_inserts_setting_when_key_missing(session):
    s = _make_settings(DOKOPS_AI_PROVIDER="OPENAI")
    asyncio.run(seed_from_env(session, s))

    row = asyncio.run(session.exec(select(SystemSetting).where(SystemSetting.key == "ai_provider")))
    row = row.first()
    assert row is not None
    assert row.value == "OPENAI"


def test_skips_setting_when_key_exists_no_force(session):
    session.add(SystemSetting(key="ai_provider", value="GEMINI"))
    asyncio.run(session.commit())

    s = _make_settings(DOKOPS_AI_PROVIDER="OPENAI", DOKOPS_FORCE_SEED=False)
    asyncio.run(seed_from_env(session, s))

    row = asyncio.run(session.exec(select(SystemSetting).where(SystemSetting.key == "ai_provider")))
    row = row.first()
    assert row.value == "GEMINI"  # unchanged


def test_overwrites_setting_when_key_exists_and_force_seed(session):
    session.add(SystemSetting(key="ai_provider", value="GEMINI"))
    asyncio.run(session.commit())

    s = _make_settings(DOKOPS_AI_PROVIDER="AZURE", DOKOPS_FORCE_SEED=True)
    asyncio.run(seed_from_env(session, s))

    row = asyncio.run(session.exec(select(SystemSetting).where(SystemSetting.key == "ai_provider")))
    row = row.first()
    assert row.value == "AZURE"


def test_skips_none_values(session):
    s = _make_settings()  # all None
    asyncio.run(seed_from_env(session, s))

    rows = asyncio.run(session.exec(select(SystemSetting)))
    assert len(rows.all()) == 0


def test_bool_settings_stored_as_lowercase_string(session):
    s = _make_settings(DOKOPS_RAG_ENABLED=True, DOKOPS_SIGNUP_ENABLED=False)
    asyncio.run(seed_from_env(session, s))

    rag = asyncio.run(session.exec(select(SystemSetting).where(SystemSetting.key == "rag_enabled")))
    signup = asyncio.run(session.exec(select(SystemSetting).where(SystemSetting.key == "signup_enabled")))
    assert rag.first().value == "true"
    assert signup.first().value == "false"


def test_seeds_all_tier2_keys(session):
    s = _make_settings(
        DOKOPS_AI_BASE_URL="https://api.openai.com/v1",
        DOKOPS_AI_API_VERSION="2023-05-15",
        DOKOPS_RAG_CHROMA_HOST="chroma-svc",
        DOKOPS_RAG_CHROMA_PORT="8001",
        DOKOPS_SIGNUP_DEFAULT_ROLE="user",
    )
    asyncio.run(seed_from_env(session, s))

    expected = {
        "ai_base_url": "https://api.openai.com/v1",
        "ai_api_version": "2023-05-15",
        "rag_chroma_host": "chroma-svc",
        "rag_chroma_port": "8001",
        "signup_default_role": "user",
    }
    for key, expected_value in expected.items():
        result = asyncio.run(session.exec(select(SystemSetting).where(SystemSetting.key == key)))
        row = result.first()
        assert row is not None, f"Missing key: {key}"
        assert row.value == expected_value, f"{key}: expected {expected_value!r}, got {row.value!r}"


def test_seeds_all_tier3_keys(session):
    s = _make_settings(
        DOKOPS_RAG_EMBEDDING_PROVIDER="openai",
        DOKOPS_RAG_EMBEDDING_API_KEY="sk-embed",
        DOKOPS_RAG_EMBEDDING_MODEL="text-embedding-3-small",
        DOKOPS_RAG_EMBEDDING_BASE_URL="https://api.openai.com/v1",
    )
    asyncio.run(seed_from_env(session, s))

    expected = {
        "rag_embedding_provider": "openai",
        "rag_embedding_api_key": "sk-embed",
        "rag_embedding_model": "text-embedding-3-small",
        "rag_embedding_base_url": "https://api.openai.com/v1",
    }
    for key, expected_value in expected.items():
        result = asyncio.run(session.exec(select(SystemSetting).where(SystemSetting.key == key)))
        row = result.first()
        assert row is not None, f"Missing key: {key}"
        assert row.value == expected_value
