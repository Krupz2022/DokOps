import pytest
from sqlmodel import SQLModel, select
from app.core.db import _to_async_url, AsyncSessionLocal, async_engine
from app.models.user import User
from app.core import security


def test_to_async_url_sqlite():
    assert _to_async_url("sqlite:///./sql_app.db") == "sqlite+aiosqlite:///./sql_app.db"


def test_to_async_url_postgres():
    assert _to_async_url("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert _to_async_url("postgresql+psycopg2://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"


@pytest.mark.asyncio
async def test_async_session_roundtrip():
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSessionLocal() as db:
        db.add(User(username="async_rt", hashed_password=security.get_password_hash("x")))
        await db.commit()
        found = (await db.exec(select(User).where(User.username == "async_rt"))).first()
        assert found is not None and found.username == "async_rt"
