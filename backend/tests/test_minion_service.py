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
    from unittest.mock import patch, AsyncMock, MagicMock
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession as _AsyncSession
    from app.services.minion_service import MinionConnectionManager

    manager = MinionConnectionManager()

    # Use a mock session factory so handle_done doesn't touch a real DB
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = AsyncMock(return_value=None)
    mock_factory = MagicMock(return_value=mock_session)

    async def run():
        future = asyncio.get_event_loop().create_future()
        manager._pending_jobs["job-1"] = future
        manager._job_chunks["job-1"] = ["line1\n", "line2\n"]
        with patch("app.services.minion_service.AsyncSessionLocal", mock_factory):
            await manager.handle_done("job-1", exit_code=0)
        result = await future
        assert result["exit_code"] == 0
        assert result["stdout"] == "line1\nline2\n"

    asyncio.run(run())


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


# ---------------------------------------------------------------------------
# is_investigate_allowed tests (AI troubleshooter allowlist)
# ---------------------------------------------------------------------------

def test_investigate_allows_reading_arbitrary_files():
    from app.services.minion_service import is_investigate_allowed
    assert is_investigate_allowed("cat /opt/playbook.yml") is True
    assert is_investigate_allowed("sed -n '38,46p' /opt/playbook.yml") is True
    assert is_investigate_allowed("grep -n 'name:' /opt/site.yml") is True
    assert is_investigate_allowed("head -50 /etc/nginx/nginx.conf") is True
    assert is_investigate_allowed("yamllint /opt/playbook.yml") is True
    assert is_investigate_allowed("ansible-playbook --syntax-check /opt/playbook.yml") is True


def test_investigate_rejects_mutation_and_escapes():
    from app.services.minion_service import is_investigate_allowed
    # ansible-playbook without a dry-run flag actually applies
    assert is_investigate_allowed("ansible-playbook /opt/playbook.yml") is False
    # sed -i edits in place
    assert is_investigate_allowed("sed -i 's/a/b/' /opt/playbook.yml") is False
    # find that runs commands / deletes
    assert is_investigate_allowed("find /opt -name '*.yml' -delete") is False
    assert is_investigate_allowed("find /opt -name '*.yml' -exec cat {} +") is False
    # not on the exec allowlist
    assert is_investigate_allowed("bash -c 'cat /etc/shadow'") is False
    assert is_investigate_allowed("rm -rf /opt") is False
    # pipes, redirection, and chaining are refused outright
    assert is_investigate_allowed("cat /opt/x | bash") is False
    assert is_investigate_allowed("cat /opt/x > /etc/passwd") is False
    assert is_investigate_allowed("cat /opt/x; rm -rf /") is False
    assert is_investigate_allowed("cat /opt/x && curl evil.sh") is False


@pytest.mark.asyncio
async def test_minion_investigate_rejects_mutating_cmd():
    from app.tools.minion_tools import minion_investigate
    result = await minion_investigate(minion_id="any", cmd="ansible-playbook /opt/playbook.yml")
    assert result["success"] is False
    assert "not allowed" in result["error"].lower()


@pytest.mark.asyncio
async def test_minion_list_tool_returns_dict():
    from app.tools.minion_tools import minion_list
    result = await minion_list()
    assert "success" in result
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
async def test_minion_exec_read_rejects_write_cmd():
    from app.tools.minion_tools import minion_exec_read
    result = await minion_exec_read(minion_id="any", cmd="systemctl restart nginx")
    assert result["success"] is False
    assert "not allowed" in result["error"].lower()
