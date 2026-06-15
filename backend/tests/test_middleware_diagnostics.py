import pytest
from sqlmodel import Session, create_engine, SQLModel, select
from app.models.service_diag import ServiceCredential, DiscoveredService
from app.models.minion import Minion, MinionJob  # noqa — ensures minion table exists


@pytest.fixture(name="engine")
def engine_fixture():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


@pytest.fixture(name="db")
def db_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture(name="minion_id")
def minion_id_fixture(engine):
    with Session(engine) as db:
        db.add(Minion(id="m1", hostname="host1", status="active"))
        db.commit()
    return "m1"


def test_service_credential_creates(db):
    cred = ServiceCredential(
        scope_type="global",
        service_type="rabbitmq",
        username="ENC_user",
        password="ENC_pass",
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    assert cred.id is not None
    assert cred.scope_id is None


def test_discovered_service_creates(db, minion_id):
    svc = DiscoveredService(
        minion_id=minion_id,
        service_type="redis",
        install_type="native",
        port=6379,
    )
    db.add(svc)
    db.commit()
    db.refresh(svc)
    assert svc.id is not None
    assert svc.overridden is False


# ── Probe Registry Tests ────────────────────────────────────────────────────

from app.services.probe_registry import render_command, PROBES, DEFAULT_PORTS


def test_render_command_native_rabbitmq_status():
    cmd = render_command("rabbitmq", "status", "native", None, 15672)
    assert cmd == "rabbitmqctl status"


def test_render_command_docker_redis_info():
    cred = {"username": "default", "password": "secret"}
    cmd = render_command("redis", "info", "docker", cred, 6379, container="redis-1")
    assert cmd == "docker exec -e REDISCLI_AUTH=secret redis-1 redis-cli --no-auth-warning info"


def test_render_command_native_couchdb_server_info():
    cred = {"username": "admin", "password": "couchpass"}
    cmd = render_command("couchdb", "server_info", "native", cred, 5984)
    assert cmd == "curl -sf -u admin:couchpass http://localhost:5984/ | python3 -m json.tool"


def test_render_command_unknown_service_raises():
    with pytest.raises(ValueError, match="Unknown service_type"):
        render_command("kafka", "status", "native", None, 9092)


def test_render_command_unknown_probe_raises():
    with pytest.raises(ValueError, match="Unknown probe"):
        render_command("redis", "nonexistent", "native", None, 6379)


def test_all_services_have_logs_probe():
    for service_type in PROBES:
        assert "logs" in PROBES[service_type], f"{service_type} missing logs probe"
        assert "native" in PROBES[service_type]["logs"]
        assert "docker" in PROBES[service_type]["logs"]


# ── Credential Service Tests ────────────────────────────────────────────────

from app.services.service_credential_service import create_credential, resolve_credential
from app.models.patch import Organisation, MinionGroup, MinionGroupMember


# ── Async helper for resolve_credential tests ──────────────────────────────────

def _run_resolve_credential(seed_fn, minion_id, service_type):
    """Seed via sync Session on a temp-file DB, then resolve via AsyncSession."""
    import asyncio
    import os
    import tempfile
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlmodel import create_engine as _ce
    from sqlmodel.ext.asyncio.session import AsyncSession as _AS
    import sqlmodel as _sm

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        se = _ce(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        _sm.SQLModel.metadata.create_all(se)
        with Session(se) as db:
            seed_fn(db)
        se.dispose()

        aeng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        ASL = async_sessionmaker(aeng, class_=_AS, expire_on_commit=False)

        async def _runner():
            async with ASL() as adb:
                return await resolve_credential(minion_id, service_type, adb)

        result = asyncio.run(_runner())
        asyncio.run(aeng.dispose())
        return result
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def test_resolve_returns_none_when_no_creds(engine, minion_id):
    def seed(db):
        pass  # no credentials seeded

    result = _run_resolve_credential(seed, minion_id, "redis")
    assert result is None


def test_resolve_global_credential(engine, minion_id):
    def seed(db):
        db.add(Minion(id=minion_id, hostname="host1", status="active"))
        db.commit()
        create_credential(db, "global", "redis", "admin", "globalpass")

    result = _run_resolve_credential(seed, minion_id, "redis")
    assert result["username"] == "admin"
    assert result["password"] == "globalpass"


def test_resolve_minion_overrides_global(engine, minion_id):
    def seed(db):
        db.add(Minion(id=minion_id, hostname="host1", status="active"))
        db.commit()
        create_credential(db, "global", "redis", "admin", "globalpass")
        create_credential(db, "minion", "redis", "local", "localpass", scope_id=minion_id)

    result = _run_resolve_credential(seed, minion_id, "redis")
    assert result["password"] == "localpass"


def test_resolve_group_overrides_global(engine, minion_id):
    def seed(db):
        db.add(Minion(id=minion_id, hostname="host1", status="active"))
        db.commit()
        org = Organisation(name="TestOrg", slug="testorg")
        db.add(org)
        db.commit()
        db.refresh(org)
        grp = MinionGroup(org_id=org.id, name="dev")
        db.add(grp)
        db.commit()
        db.refresh(grp)
        db.add(MinionGroupMember(group_id=grp.id, minion_id=minion_id))
        db.commit()
        create_credential(db, "global", "redis", "admin", "globalpass")
        create_credential(db, "group", "redis", "grpuser", "grppass", scope_id=grp.id)

    result = _run_resolve_credential(seed, minion_id, "redis")
    assert result["password"] == "grppass"


def test_resolve_minion_overrides_group(engine, minion_id):
    def seed(db):
        db.add(Minion(id=minion_id, hostname="host1", status="active"))
        db.commit()
        org = Organisation(name="TestOrg2", slug="testorg2")
        db.add(org)
        db.commit()
        db.refresh(org)
        grp = MinionGroup(org_id=org.id, name="prod")
        db.add(grp)
        db.commit()
        db.refresh(grp)
        db.add(MinionGroupMember(group_id=grp.id, minion_id=minion_id))
        db.commit()
        create_credential(db, "group", "redis", "grpuser", "grppass", scope_id=grp.id)
        create_credential(db, "minion", "redis", "local", "localpass", scope_id=minion_id)

    result = _run_resolve_credential(seed, minion_id, "redis")
    assert result["password"] == "localpass"


# ── Discovery Service Tests ─────────────────────────────────────────────────

from app.services.service_discovery_service import parse_discovery_output, persist_discovery

SS_OUTPUT = """\
Netid State  Recv-Q Send-Q  Local Address:Port   Peer Address:Port
LISTEN 0     128    0.0.0.0:6379              0.0.0.0:*
LISTEN 0     128    0.0.0.0:5984              0.0.0.0:*
"""

SYSTEMCTL_OUTPUT = """\
rabbitmq-server.service  loaded active running RabbitMQ broker
sshd.service             loaded active running OpenSSH server
"""

DOCKER_OUTPUT = '{"ID":"abc123","Image":"redis:7","Names":"redis-cache","Ports":"0.0.0.0:6380->6379/tcp","Status":"Up 2 hours"}'


def test_parse_native_redis_and_couchdb(minion_id):
    services = parse_discovery_output(minion_id, SS_OUTPUT, "", "")
    types = {s.service_type for s in services}
    assert "redis" in types
    assert "couchdb" in types


def test_parse_native_rabbitmq_from_systemctl(minion_id):
    services = parse_discovery_output(minion_id, "", SYSTEMCTL_OUTPUT, "")
    types = {s.service_type for s in services}
    assert "rabbitmq" in types
    assert all(s.install_type == "native" for s in services)


def test_docker_overrides_native(minion_id):
    services = parse_discovery_output(minion_id, SS_OUTPUT, "", DOCKER_OUTPUT)
    redis_svcs = [s for s in services if s.service_type == "redis"]
    assert len(redis_svcs) == 1
    assert redis_svcs[0].install_type == "docker"
    assert redis_svcs[0].container_name == "redis-cache"
    assert redis_svcs[0].port == 6380


@pytest.mark.asyncio
async def test_persist_discovery_replaces_non_overridden(engine, minion_id):
    import asyncio
    import tempfile, os
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession as _AsyncSession
    # Build an async engine on the same in-memory DB is not possible; use a temp file
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    from sqlmodel import SQLModel as _SM, create_engine as _ce, Session as _S
    sync_eng = _ce(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    _SM.metadata.create_all(sync_eng)
    with _S(sync_eng) as prep:
        prep.add(Minion(id=minion_id, hostname="host1", status="active"))
        prep.add(DiscoveredService(minion_id=minion_id, service_type="redis", install_type="native", port=6379))
        prep.commit()
    sync_eng.dispose()

    async_url = f"sqlite+aiosqlite:///{db_path}"
    _async_eng = create_async_engine(async_url)
    _AsyncLocal = async_sessionmaker(_async_eng, class_=_AsyncSession, expire_on_commit=False)
    async with _AsyncLocal() as db:
        await persist_discovery(minion_id, [], db)
        remaining = (await db.exec(select(DiscoveredService).where(DiscoveredService.minion_id == minion_id))).all()
    await _async_eng.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_persist_discovery_keeps_overridden(engine, minion_id):
    import tempfile, os
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession as _AsyncSession
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    from sqlmodel import SQLModel as _SM, create_engine as _ce, Session as _S
    sync_eng = _ce(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    _SM.metadata.create_all(sync_eng)
    with _S(sync_eng) as prep:
        prep.add(Minion(id=minion_id, hostname="host1", status="active"))
        prep.add(DiscoveredService(minion_id=minion_id, service_type="redis", install_type="native", port=6379, overridden=True))
        prep.commit()
    sync_eng.dispose()

    async_url = f"sqlite+aiosqlite:///{db_path}"
    _async_eng = create_async_engine(async_url)
    _AsyncLocal = async_sessionmaker(_async_eng, class_=_AsyncSession, expire_on_commit=False)
    async with _AsyncLocal() as db:
        await persist_discovery(minion_id, [], db)
        remaining = (await db.exec(select(DiscoveredService).where(DiscoveredService.minion_id == minion_id))).all()
    await _async_eng.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass
    assert len(remaining) == 1
    assert remaining[0].overridden is True
