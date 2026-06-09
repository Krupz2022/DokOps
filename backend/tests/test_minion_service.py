import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlmodel import SQLModel, create_engine, Session
from app.models.minion import Minion, MinionJob  # noqa: F401 — registers tables in metadata


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


def test_minion_model_creates_and_retrieves(engine):
    from datetime import datetime
    with Session(engine) as session:
        m = Minion(
            id="test-uuid-1234",
            hostname="prod-worker-01",
            status="pending",
            grains='{"os": "Ubuntu 22.04"}',
            created_at=datetime.utcnow(),
        )
        session.add(m)
        session.commit()
        session.refresh(m)
        assert m.hostname == "prod-worker-01"
        assert m.status == "pending"


def test_minion_job_model_creates(engine):
    from datetime import datetime
    with Session(engine) as session:
        m = Minion(id="m1", hostname="host1", status="active", grains="{}", created_at=datetime.utcnow())
        session.add(m)
        session.commit()
        j = MinionJob(
            id="job-uuid-1",
            minion_id="m1",
            command="docker ps",
            actor="admin",
            status="pending",
            stdout="",
            stderr="",
            created_at=datetime.utcnow(),
        )
        session.add(j)
        session.commit()
        session.refresh(j)
        assert j.command == "docker ps"
        assert j.exit_code is None


# ---------------------------------------------------------------------------
# MinionConnectionManager tests
# ---------------------------------------------------------------------------

def test_connection_manager_registers_connection():
    from app.services.minion_service import MinionConnectionManager
    manager = MinionConnectionManager()
    ws = AsyncMock()
    asyncio.run(manager.connect("minion-1", ws))
    assert manager.is_connected("minion-1")


def test_connection_manager_disconnects():
    from app.services.minion_service import MinionConnectionManager
    manager = MinionConnectionManager()
    ws = AsyncMock()
    asyncio.run(manager.connect("minion-1", ws))
    manager.disconnect("minion-1")
    assert not manager.is_connected("minion-1")


def test_handle_done_resolves_future():
    from app.services.minion_service import MinionConnectionManager
    manager = MinionConnectionManager()
    loop = asyncio.new_event_loop()

    async def run():
        future = loop.create_future()
        manager._pending_jobs["job-1"] = future
        manager._job_chunks["job-1"] = ["line1\n", "line2\n"]
        manager.handle_done("job-1", exit_code=0)
        result = await future
        assert result["exit_code"] == 0
        assert result["stdout"] == "line1\nline2\n"

    loop.run_until_complete(run())
    loop.close()


# ---------------------------------------------------------------------------
# is_read_allowed tests
# ---------------------------------------------------------------------------

def test_read_allowlist_accepts_docker_ps():
    from app.services.minion_service import is_read_allowed
    assert is_read_allowed("docker ps") is True
    assert is_read_allowed("docker ps -a --format json") is True


def test_read_allowlist_rejects_docker_rm():
    from app.services.minion_service import is_read_allowed
    assert is_read_allowed("docker rm mycontainer") is False


def test_read_allowlist_rejects_bash():
    from app.services.minion_service import is_read_allowed
    assert is_read_allowed("bash -c 'rm -rf /'") is False


def test_read_allowlist_accepts_systemctl_status():
    from app.services.minion_service import is_read_allowed
    assert is_read_allowed("systemctl status nginx") is True


def test_read_allowlist_rejects_systemctl_restart():
    from app.services.minion_service import is_read_allowed
    assert is_read_allowed("systemctl restart nginx") is False


def test_minion_list_tool_returns_dict():
    from app.tools.minion_tools import minion_list
    result = minion_list()
    assert "success" in result
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
async def test_minion_exec_read_rejects_write_cmd():
    from app.tools.minion_tools import minion_exec_read
    result = await minion_exec_read(minion_id="any", cmd="systemctl restart nginx")
    assert result["success"] is False
    assert "not allowed" in result["error"].lower()
