import asyncio, os, tempfile, pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

import app.main  # noqa: F401  (registers all SQLModel tables so create_all resolves FKs)
from app.models.minion import Minion        # noqa: F401  (register tables)
from app.models.setting import SystemSetting # noqa: F401


@pytest.fixture(name="session")
def session_fixture():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(name="client")
def client_fixture(session: Session):
    from app.main import app
    from app.api import deps
    from app.models.user import User

    db_url = str(session.bind.url)
    async_url = db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    _async_engine = create_async_engine(async_url, connect_args={"check_same_thread": False})
    _AsyncSessionLocal = async_sessionmaker(_async_engine, class_=AsyncSession, expire_on_commit=False)

    async def get_async_session_override():
        async with _AsyncSessionLocal() as s:
            yield s

    def user_override():
        return User(id="u1", username="admin", email="a@b.com", hashed_password="x",
                    is_superuser=True, role="admin", is_active=True)

    app.dependency_overrides[deps.get_async_db] = get_async_session_override
    app.dependency_overrides[deps.get_current_user] = user_override
    yield TestClient(app)
    app.dependency_overrides.clear()
    asyncio.run(_async_engine.dispose())


def test_portainer_config_roundtrip_redacts_key(client):
    # Unset → not configured
    r = client.get("/api/v1/minions/m1/portainer")
    assert r.status_code == 200
    assert r.json() == {"configured": False, "base_url": None, "endpoint_id": None}

    # Set
    r = client.put("/api/v1/minions/m1/portainer", json={
        "base_url": "https://host:9443", "api_key": "ptr_secret", "endpoint_id": 2,
    })
    assert r.status_code == 200

    # Get → configured, key never returned
    r = client.get("/api/v1/minions/m1/portainer")
    body = r.json()
    assert body == {"configured": True, "base_url": "https://host:9443", "endpoint_id": 2}
    assert "api_key" not in body
