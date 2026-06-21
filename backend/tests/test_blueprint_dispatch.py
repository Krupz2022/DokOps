# backend/tests/test_blueprint_dispatch.py
import asyncio
import json

from app.models.blueprint import BlueprintRun, ResourceResult  # noqa: F401
from app.models.minion import Minion  # noqa: F401
from app.services.minion_service import MinionConnectionManager


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


def test_handle_result_persists_state_results(isolated_session, monkeypatch):
    from app.services import minion_service as ms

    # Point the manager's DB writes at the test DB.
    url = str(isolated_session.bind.url).replace("sqlite://", "sqlite+aiosqlite://", 1)
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession
    engine = create_async_engine(url, connect_args={"check_same_thread": False})
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(ms, "AsyncSessionLocal", maker)

    run = BlueprintRun(id="r1", minion_id="web-01", actor="ui", test=True, status="running")
    isolated_session.add(Minion(id="web-01", hostname="web-01", status="active"))
    isolated_session.add(run)
    isolated_session.commit()

    mgr = MinionConnectionManager()

    async def go():
        await mgr.handle_blueprint_result("r1", [
            {"id": "pkg", "result": None, "changes": {"new": "installed"}, "comment": "would install"},
        ])

    asyncio.get_event_loop().run_until_complete(go())

    from sqlmodel import select as _select
    persisted = isolated_session.exec(_select(ResourceResult).where(ResourceResult.run_id == "r1")).all()
    assert len(persisted) == 1
    assert persisted[0].resource_id == "pkg"
    assert persisted[0].result is None
    refreshed = isolated_session.get(BlueprintRun, "r1")
    assert refreshed.status == "done"
