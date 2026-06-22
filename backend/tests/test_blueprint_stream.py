import asyncio
from app.models.blueprint import BlueprintRun, ResourceResult  # noqa: F401
from app.models.minion import Minion  # noqa: F401
from app.services.minion_service import MinionConnectionManager
from sqlmodel import select


def _async_maker(isolated_session):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession
    url = str(isolated_session.bind.url).replace("sqlite://", "sqlite+aiosqlite://", 1)
    engine = create_async_engine(url, connect_args={"check_same_thread": False})
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def test_done_event_persists_results(isolated_session, monkeypatch):
    from app.services import minion_service as ms
    monkeypatch.setattr(ms, "AsyncSessionLocal", _async_maker(isolated_session))

    isolated_session.add(Minion(id="m1", hostname="m1", status="active"))
    isolated_session.add(BlueprintRun(id="r1", minion_id="m1", actor="ui", test=False, status="running"))
    isolated_session.commit()

    mgr = MinionConnectionManager()

    async def go():
        await mgr.handle_blueprint_event("r1", {"kind": "resource_start", "id": "a"})
        await mgr.handle_blueprint_event("r1", {"kind": "log", "id": "a", "line": "x"})
        await mgr.handle_blueprint_event("r1", {"kind": "done", "results": [
            {"id": "a", "result": True, "changes": {"new": "installed"}, "comment": "installed", "output": "logs"},
        ]})

    asyncio.run(go())

    rows = isolated_session.exec(select(ResourceResult).where(ResourceResult.run_id == "r1")).all()
    assert len(rows) == 1 and rows[0].output == "logs"
    assert isolated_session.get(BlueprintRun, "r1").status == "done"


def test_error_event_marks_failed(isolated_session, monkeypatch):
    from app.services import minion_service as ms
    monkeypatch.setattr(ms, "AsyncSessionLocal", _async_maker(isolated_session))
    isolated_session.add(BlueprintRun(id="r2", minion_id="m1", actor="ui", test=True, status="running"))
    isolated_session.commit()
    mgr = MinionConnectionManager()

    asyncio.run(
        mgr.handle_blueprint_event("r2", {"kind": "error", "message": "boom"}))
    assert isolated_session.get(BlueprintRun, "r2").status == "failed"
