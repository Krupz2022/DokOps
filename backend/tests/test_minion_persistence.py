import asyncio
import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from sqlmodel import Session, create_engine, SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession as _AsyncSession
from app.services.minion_service import MinionConnectionManager
from app.models.minion import Minion, MinionJob


@pytest.fixture
def engine():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    sync_url = f"sqlite:///{db_path}"
    e = create_engine(sync_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(e)
    yield e
    e.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


def _make_async_factory(engine):
    """Create an AsyncSession factory pointing to the same file DB as *engine*."""
    db_url = str(engine.url)
    async_url = db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    async_eng = create_async_engine(async_url, connect_args={"check_same_thread": False})
    return async_eng, async_sessionmaker(async_eng, class_=_AsyncSession, expire_on_commit=False)

@pytest.fixture
def seeded_job(engine):
    with Session(engine) as db:
        minion = Minion(id="m1", hostname="test-host", status="active")
        job = MinionJob(id="job-1", minion_id="m1", command="docker ps", actor="test", status="running")
        db.add(minion)
        db.add(job)
        db.commit()
    return "job-1"

def test_handle_done_persists_exit_code_when_no_future(engine, seeded_job):
    """handle_done must write exit_code to DB even when no HTTP caller is waiting."""
    async_eng, session_factory = _make_async_factory(engine)
    mgr = MinionConnectionManager()
    # No future registered — simulates browser tab closed before job finished
    with patch("app.services.minion_service.AsyncSessionLocal", session_factory):
        asyncio.run(mgr.handle_done(seeded_job, exit_code=0))
    asyncio.run(async_eng.dispose())

    with Session(engine) as db:
        job = db.get(MinionJob, seeded_job)
        assert job.status == "done"
        assert job.exit_code == 0
        assert job.completed_at is not None

def test_handle_done_marks_failed_on_nonzero_exit(engine, seeded_job):
    """Non-zero exit code must set status=failed."""
    async_eng, session_factory = _make_async_factory(engine)
    mgr = MinionConnectionManager()
    with patch("app.services.minion_service.AsyncSessionLocal", session_factory):
        asyncio.run(mgr.handle_done(seeded_job, exit_code=1))
    asyncio.run(async_eng.dispose())

    with Session(engine) as db:
        job = db.get(MinionJob, seeded_job)
        assert job.status == "failed"
        assert job.exit_code == 1

def test_handle_done_resolves_future_when_caller_waiting(engine, seeded_job):
    """handle_done must still resolve the in-memory future if the HTTP caller is alive."""
    async_eng, session_factory = _make_async_factory(engine)
    mgr = MinionConnectionManager()

    async def _run():
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        mgr._pending_jobs[seeded_job] = future
        mgr._job_chunks[seeded_job] = ["line1\n", "line2\n"]
        with patch("app.services.minion_service.AsyncSessionLocal", session_factory):
            await mgr.handle_done(seeded_job, exit_code=0)
        assert future.done()
        result = future.result()
        assert result["stdout"] == "line1\nline2\n"
        assert result["exit_code"] == 0

    asyncio.run(_run())
    asyncio.run(async_eng.dispose())


@pytest.mark.asyncio
async def test_dispatch_job_does_not_write_stdout_to_db(engine):
    """dispatch_job must return stdout in the response but never write it to DB."""
    from unittest.mock import AsyncMock, patch
    from sqlmodel import select
    from app.models.minion import Minion, MinionJob

    with Session(engine) as db:
        minion = Minion(id="m2", hostname="host2", status="active")
        db.add(minion)
        db.commit()

    async_eng, session_factory = _make_async_factory(engine)
    mgr = MinionConnectionManager()

    mock_ws = AsyncMock()
    mgr._connections["m2"] = mock_ws

    async def fake_send(data):
        import json
        msg = data if isinstance(data, dict) else json.loads(data)
        if msg.get("type") == "job":
            job_id = msg["job_id"]
            mgr._job_chunks[job_id] = ["hello\n"]
            # Simulate the minion calling handle_done (as the WS handler would)
            with patch("app.services.minion_service.AsyncSessionLocal", session_factory):
                await mgr.handle_done(job_id, 0)

    mock_ws.send_json.side_effect = fake_send

    with patch("app.services.minion_service.AsyncSessionLocal", session_factory):
        result = await mgr.dispatch_job("m2", "echo hello", actor="test", timeout=5, god_mode=True)

    await async_eng.dispose()

    assert result["stdout"] == "hello\n"
    assert result["exit_code"] == 0

    # Stdout must NOT be written to the DB (field stays at its default empty string)
    with Session(engine) as db:
        jobs = db.exec(select(MinionJob).where(MinionJob.minion_id == "m2")).all()
        assert len(jobs) == 1
        assert jobs[0].stdout == ""   # default — never written by dispatch_job
        assert jobs[0].exit_code == 0
        assert jobs[0].status == "done"
