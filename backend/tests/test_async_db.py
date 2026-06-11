import pytest
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.core.db import _to_async_url, AsyncSessionLocal, async_engine
from app.models.user import User
from app.core import security


def test_to_async_url_sqlite():
    assert _to_async_url("sqlite:///./sql_app.db") == "sqlite+aiosqlite:///./sql_app.db"


def test_to_async_url_postgres():
    assert _to_async_url("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert _to_async_url("postgresql+psycopg2://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"


def test_to_async_url_pysqlite_and_short_postgres():
    assert _to_async_url("sqlite+pysqlite:///./dev.db") == "sqlite+aiosqlite:///./dev.db"
    assert _to_async_url("postgres://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"


def test_async_engine_kwargs_postgres():
    from app.core.db import _async_engine_kwargs
    kw = _async_engine_kwargs("postgresql+asyncpg://u:p@h/db")
    assert kw["pool_size"] == 10 and kw["max_overflow"] == 20 and kw["pool_recycle"] == 1800 and kw["pool_pre_ping"] is True


@pytest.mark.asyncio
async def test_async_session_roundtrip():
    # Use a fresh in-memory engine so this test is fully isolated and idempotent.
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        pool_pre_ping=True,
    )
    TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with TestSessionLocal() as db:
        db.add(User(username="async_rt", hashed_password=security.get_password_hash("x")))
        await db.commit()
        found = (await db.exec(select(User).where(User.username == "async_rt"))).first()
        assert found is not None and found.username == "async_rt"

    await test_engine.dispose()


# Intentionally a live-session smoke test against the app's configured DB (type check only, no writes).
@pytest.mark.asyncio
async def test_get_async_db_yields_session():
    from app.api.deps import get_async_db
    gen = get_async_db()
    db = await gen.__anext__()
    from sqlmodel.ext.asyncio.session import AsyncSession
    assert isinstance(db, AsyncSession)
    await gen.aclose()
