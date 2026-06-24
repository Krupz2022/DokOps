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


from app.services.live_resources import services_command, parse_services


def test_services_command_picks_os():
    assert services_command("ubuntu").startswith("systemctl list-units")
    assert services_command("windows").startswith("Get-Service")


def test_parse_services_linux():
    out = (
        "ssh.service loaded active running OpenBSD Secure Shell server\n"
        "cron.service loaded active running Regular background program processing daemon\n"
    )
    svcs = parse_services("ubuntu", out)
    assert {"name": "ssh", "display_name": "OpenBSD Secure Shell server", "status": "running"} in svcs
    assert len(svcs) == 2


def test_parse_services_windows():
    out = '[{"Name":"Spooler","DisplayName":"Print Spooler","Status":"Running"}]'
    svcs = parse_services("windows", out)
    assert svcs == [{"name": "Spooler", "display_name": "Print Spooler", "status": "Running"}]


from unittest.mock import patch


def _seed_minion(session, os_id="ubuntu"):
    import json as _json
    from app.models.minion import Minion
    session.add(Minion(id="m1", hostname="h", status="active", grains=_json.dumps({"os": os_id})))
    session.commit()


def test_live_services_parses_dispatch_output(client, session):
    _seed_minion(session, "ubuntu")
    from app.services.minion_service import manager

    async def fake_dispatch(minion_id, cmd, actor, timeout=60, god_mode=False):
        return {"stdout": "ssh.service loaded active running OpenBSD Secure Shell server\n", "exit_code": 0}

    with patch.object(manager, "is_connected", return_value=True), \
         patch.object(manager, "dispatch_job", side_effect=fake_dispatch):
        r = client.get("/api/v1/minions/m1/resources/services")
    assert r.status_code == 200
    assert r.json()["services"][0]["name"] == "ssh"


def test_live_services_503_when_disconnected(client, session):
    _seed_minion(session)
    from app.services.minion_service import manager
    with patch.object(manager, "is_connected", return_value=False):
        r = client.get("/api/v1/minions/m1/resources/services")
    assert r.status_code == 503


def test_live_services_502_on_nonzero_exit(client, session):
    _seed_minion(session, "ubuntu")
    from app.services.minion_service import manager

    async def fake_dispatch(minion_id, cmd, actor, timeout=60, god_mode=False):
        return {"stdout": "Failed to connect to bus\n", "exit_code": 1}

    with patch.object(manager, "is_connected", return_value=True), \
         patch.object(manager, "dispatch_job", side_effect=fake_dispatch):
        r = client.get("/api/v1/minions/m1/resources/services")
    assert r.status_code == 502
    assert "Failed to connect to bus" in r.json()["detail"]


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


def test_docker_503_when_unconfigured(client, session):
    _seed_minion(session)
    r = client.get("/api/v1/minions/m1/resources/docker")
    assert r.status_code == 503


def test_docker_proxies_when_configured(client, session):
    _seed_minion(session)
    client.put("/api/v1/minions/m1/portainer", json={
        "base_url": "https://host:9443", "api_key": "k", "endpoint_id": 1,
    })
    from app.services import live_resources as lr

    async def fake_fetch(base_url, api_key, endpoint_id):
        return {"containers": [{"Id": "abc"}], "images": [], "volumes": {"Volumes": []}, "networks": []}

    with patch.object(lr, "fetch_docker_resources", side_effect=fake_fetch):
        r = client.get("/api/v1/minions/m1/resources/docker")
    assert r.status_code == 200
    assert r.json()["containers"][0]["Id"] == "abc"
