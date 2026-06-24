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


def test_get_service_allowlist_blocks_chaining():
    from app.services.minion_service import is_read_allowed
    # the real feature command (single pipe) is allowed
    assert is_read_allowed("Get-Service | Where-Object {$_.Status -eq 'Running'}")
    assert is_read_allowed("systemctl list-units --type=service | grep ssh")
    # statement chaining / command substitution is rejected even behind a safe prefix
    assert not is_read_allowed("Get-Service; Remove-Item -Recurse C:/data")
    assert not is_read_allowed("Get-Service | Out-Null; Remove-Item C:/data")
    assert not is_read_allowed("docker ps && rm -rf /")
    assert not is_read_allowed("docker ps $(rm -rf /)")


def test_valid_service_name_rejects_shell_metachars():
    from app.services.live_resources import valid_service_name
    assert valid_service_name("ssh")
    assert valid_service_name("getty@tty1")
    assert valid_service_name("AdobeARMservice")
    assert not valid_service_name("ssh; rm -rf /")
    assert not valid_service_name("foo|bar")
    assert not valid_service_name("foo bar")
    assert not valid_service_name("$(whoami)")
    assert not valid_service_name("")


def test_service_logs_400_on_bad_name(client, session):
    _seed_minion(session)
    r = client.get("/api/v1/minions/m1/resources/services/ssh%3Brm/logs")
    assert r.status_code == 400


def test_service_logs_returns_output(client, session):
    _seed_minion(session, "ubuntu")
    from app.services.minion_service import manager
    captured = {}

    async def fake_dispatch(minion_id, cmd, actor, timeout=60, god_mode=False):
        captured["cmd"] = cmd
        captured["god_mode"] = god_mode
        return {"stdout": "● ssh.service - OpenBSD Secure Shell\n  Active: active (running)", "exit_code": 0}

    with patch.object(manager, "is_connected", return_value=True), \
         patch.object(manager, "dispatch_job", side_effect=fake_dispatch):
        r = client.get("/api/v1/minions/m1/resources/services/ssh/logs")
    assert r.status_code == 200
    assert "Active: active" in r.json()["output"]
    assert captured["god_mode"] is True
    assert "systemctl status ssh" in captured["cmd"] and "journalctl -u ssh" in captured["cmd"]


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


def test_live_services_windows_bypasses_allowlist(client, session):
    # Regression: the Windows Get-Service command contains ';' inside @{N='Status';E={...}},
    # which is_read_allowed rejects as statement-chaining. The endpoint must dispatch it as a
    # trusted constant (god_mode=True) so it isn't blocked by the user-facing allowlist.
    from app.services.live_resources import services_command
    from app.services.minion_service import is_read_allowed, manager
    win_cmd = services_command("windows")
    assert ";" in win_cmd and not is_read_allowed(win_cmd)  # would be blocked on the user path

    _seed_minion(session, "windows")
    captured = {}

    async def fake_dispatch(minion_id, cmd, actor, timeout=60, god_mode=False):
        captured["god_mode"] = god_mode
        return {"stdout": "[]", "exit_code": 0}

    with patch.object(manager, "is_connected", return_value=True), \
         patch.object(manager, "dispatch_job", side_effect=fake_dispatch):
        r = client.get("/api/v1/minions/m1/resources/services")
    assert r.status_code == 200
    assert captured["god_mode"] is True


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
    assert r.json() == {"configured": False, "base_url": None, "endpoint_id": None, "via_agent": True}

    # Set (via_agent defaults to True)
    r = client.put("/api/v1/minions/m1/portainer", json={
        "base_url": "https://host:9443", "api_key": "ptr_secret", "endpoint_id": 2, "via_agent": False,
    })
    assert r.status_code == 200

    # Get → configured, key never returned
    r = client.get("/api/v1/minions/m1/portainer")
    body = r.json()
    assert body == {"configured": True, "base_url": "https://host:9443", "endpoint_id": 2, "via_agent": False}
    assert "api_key" not in body


def _seed_minion_docker(session, os_id="ubuntu", docker="24.0.5"):
    import json as _json
    from app.models.minion import Minion
    session.add(Minion(id="m1", hostname="h", status="active",
                       grains=_json.dumps({"os": os_id, "docker": docker})))
    session.commit()


def test_parse_docker_cli_maps_to_portainer_shape():
    from app.services.live_resources import parse_docker_cli
    out = (
        '{"ID":"abc123","Names":"web","Image":"nginx:latest","State":"running","Status":"Up 2h"}\n'
        "@@IMAGES@@\n"
        '{"ID":"img1","Repository":"nginx","Tag":"latest"}\n'
        "@@VOLUMES@@\n"
        '{"Name":"vol1","Driver":"local"}\n'
        "@@NETWORKS@@\n"
        '{"ID":"net1","Name":"bridge","Driver":"bridge"}\n'
    )
    d = parse_docker_cli(out)
    assert d["containers"] == [{"Id": "abc123", "Names": ["/web"], "Image": "nginx:latest",
                               "State": "running", "Status": "Up 2h"}]
    assert d["images"] == [{"Id": "img1", "RepoTags": ["nginx:latest"]}]
    assert d["volumes"] == {"Volumes": [{"Name": "vol1", "Driver": "local"}]}
    assert d["networks"] == [{"Id": "net1", "Name": "bridge", "Driver": "bridge"}]


def test_docker_unconfigured_503_when_disconnected(client, session):
    # No Portainer config → fallback path → minion not connected → 503.
    _seed_minion(session)
    r = client.get("/api/v1/minions/m1/resources/docker")
    assert r.status_code == 503


def test_docker_fallback_502_when_host_has_no_docker(client, session):
    # No Portainer, connected, but grains report no docker → clear 502.
    _seed_minion(session, "windows")  # grains has no "docker" key
    from app.services.minion_service import manager
    with patch.object(manager, "is_connected", return_value=True):
        r = client.get("/api/v1/minions/m1/resources/docker")
    assert r.status_code == 502
    assert "Docker is not installed" in r.json()["detail"]


def test_container_logs_400_on_bad_name(client, session):
    _seed_minion(session)
    r = client.get("/api/v1/minions/m1/resources/docker/bad%3Bname/logs")
    assert r.status_code == 400


def test_container_logs_returns_output(client, session):
    _seed_minion_docker(session)
    from app.services.minion_service import manager
    captured = {}

    async def fake_dispatch(minion_id, cmd, actor, timeout=60, god_mode=False):
        captured["cmd"] = cmd
        captured["god_mode"] = god_mode
        return {"stdout": "2026-06-25T10:00:00Z hello from container", "exit_code": 0}

    with patch.object(manager, "is_connected", return_value=True), \
         patch.object(manager, "dispatch_job", side_effect=fake_dispatch):
        r = client.get("/api/v1/minions/m1/resources/docker/sleepy_bose/logs")
    assert r.status_code == 200
    assert "hello from container" in r.json()["output"]
    assert "docker logs" in captured["cmd"] and "sleepy_bose" in captured["cmd"]
    assert captured["god_mode"] is True


def test_container_analyze_returns_markdown(client, session):
    _seed_minion_docker(session)
    from app.services.minion_service import manager

    async def fake_dispatch(minion_id, cmd, actor, timeout=60, god_mode=False):
        return {"stdout": "ERROR connection refused\n", "exit_code": 0}

    async def fake_analyze(logs, query):
        assert "ERROR connection refused" in logs
        return "## Root cause\nThe service cannot reach the database."

    import app.services.ai_service as ai_mod
    with patch.object(manager, "is_connected", return_value=True), \
         patch.object(manager, "dispatch_job", side_effect=fake_dispatch), \
         patch.object(ai_mod.ai_service, "analyze_logs", side_effect=fake_analyze):
        r = client.post("/api/v1/minions/m1/resources/docker/sleepy_bose/analyze", json={})
    assert r.status_code == 200
    assert "Root cause" in r.json()["analysis"]


def test_container_analyze_400_on_bad_name(client, session):
    _seed_minion(session)
    r = client.post("/api/v1/minions/m1/resources/docker/bad%3Bname/analyze", json={})
    assert r.status_code == 400


def test_docker_fallback_uses_agent_cli(client, session):
    _seed_minion_docker(session, "ubuntu", "24.0.5")
    from app.services.minion_service import manager
    captured = {}

    async def fake_dispatch(minion_id, cmd, actor, timeout=60, god_mode=False):
        captured["god_mode"] = god_mode
        return {"stdout": '{"ID":"c1","Names":"web","Image":"nginx","State":"running","Status":"Up"}\n'
                          "@@IMAGES@@\n@@VOLUMES@@\n@@NETWORKS@@\n", "exit_code": 0}

    with patch.object(manager, "is_connected", return_value=True), \
         patch.object(manager, "dispatch_job", side_effect=fake_dispatch):
        r = client.get("/api/v1/minions/m1/resources/docker")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "agent"
    assert body["containers"][0]["Id"] == "c1"
    assert captured["god_mode"] is True


def test_docker_proxies_when_configured(client, session):
    _seed_minion(session)
    client.put("/api/v1/minions/m1/portainer", json={
        "base_url": "https://host:9443", "api_key": "k", "endpoint_id": 1, "via_agent": False,
    })
    from app.services import live_resources as lr

    async def fake_fetch(base_url, api_key, endpoint_id):
        return {"containers": [{"Id": "abc"}], "images": [], "volumes": {"Volumes": []}, "networks": []}

    with patch.object(lr, "fetch_docker_resources", side_effect=fake_fetch):
        r = client.get("/api/v1/minions/m1/resources/docker")
    assert r.status_code == 200
    assert r.json()["containers"][0]["Id"] == "abc"
    assert r.json()["source"] == "portainer"


def test_docker_502_when_portainer_fails(client, session):
    _seed_minion(session)
    client.put("/api/v1/minions/m1/portainer", json={
        "base_url": "https://host:9443", "api_key": "k", "endpoint_id": 1, "via_agent": False,
    })
    import httpx
    from app.services import live_resources as lr

    async def boom(base_url, api_key, endpoint_id):
        raise httpx.ConnectError("connection refused")

    with patch.object(lr, "fetch_docker_resources", side_effect=boom):
        r = client.get("/api/v1/minions/m1/resources/docker")
    assert r.status_code == 502


def test_docker_via_agent_proxies_through_minion(client, session):
    # via_agent=True → backend asks the agent to query its local Portainer.
    _seed_minion(session)
    client.put("/api/v1/minions/m1/portainer", json={
        "base_url": "https://localhost:9443", "api_key": "k", "endpoint_id": 1, "via_agent": True,
    })
    from app.services.minion_service import manager

    async def fake_fetch_portainer(minion_id, base_url, api_key, endpoint_id):
        return {"containers": [{"Id": "edge1"}], "images": [], "volumes": {"Volumes": []}, "networks": []}

    with patch.object(manager, "is_connected", return_value=True), \
         patch.object(manager, "fetch_portainer", side_effect=fake_fetch_portainer):
        r = client.get("/api/v1/minions/m1/resources/docker")
    assert r.status_code == 200
    assert r.json()["containers"][0]["Id"] == "edge1"
    assert r.json()["source"] == "portainer-edge"


def test_docker_via_agent_503_when_disconnected(client, session):
    _seed_minion(session)
    client.put("/api/v1/minions/m1/portainer", json={
        "base_url": "https://localhost:9443", "api_key": "k", "endpoint_id": 1, "via_agent": True,
    })
    from app.services.minion_service import manager
    with patch.object(manager, "is_connected", return_value=False):
        r = client.get("/api/v1/minions/m1/resources/docker")
    assert r.status_code == 503
