import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import rollout_watcher as rw


def _apps(state_seq):
    """state_seq: list of deployment-list items returned per poll."""
    apps = SimpleNamespace()
    apps.list_namespaced_deployment = AsyncMock(
        side_effect=[SimpleNamespace(items=items) for items in state_seq]
    )
    return apps


def _core(pods=()):
    core = SimpleNamespace()
    core.list_namespaced_pod = AsyncMock(return_value=SimpleNamespace(items=list(pods)))
    core.list_namespaced_event = AsyncMock(return_value=SimpleNamespace(items=[]))
    core.list_namespaced_endpoints = AsyncMock(return_value=SimpleNamespace(items=[]))
    core.list_namespaced_service = AsyncMock(return_value=SimpleNamespace(items=[]))
    core.read_namespaced_pod_log = AsyncMock(return_value="")
    return core


def _dep(name, ready, replicas, conditions=()):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        spec=SimpleNamespace(replicas=replicas),
        status=SimpleNamespace(ready_replicas=ready, conditions=list(conditions)),
    )


class _FakeSession:
    """Minimal async-session double: get() returns the tracked row, others no-op."""
    def __init__(self, row):
        self._row = row
        self.added = []
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, model, pk): return self._row
    def add(self, obj): self.added.append(obj)
    async def commit(self): pass


@pytest.mark.asyncio
async def test_watch_marks_succeeded_when_rollout_becomes_ready():
    row = SimpleNamespace(id=1, conversation_id="c1", namespace="ns", target="deployment/x",
                          status="watching", message="", resolved_at=None)
    sess = _FakeSession(row)
    apps = _apps([[_dep("x", 0, 1)], [_dep("x", 1, 1)]])   # unready then ready
    core = _core()
    with patch.object(rw, "AsyncSessionLocal", lambda: _FakeSession(row)) as _, \
         patch("app.services.rollout_watcher.k8s_service._get_api",
               side_effect=lambda k, context=None: core if k == "CoreV1Api" else apps):
        rw.WATCH_INTERVAL = 0.001
        await rw.watch(1)
    assert row.status == "succeeded"
    assert "up" in row.message.lower()
    assert row.resolved_at is not None


@pytest.mark.asyncio
async def test_watch_marks_failed_on_crashloop():
    row = SimpleNamespace(id=2, conversation_id="c1", namespace="ns", target="deployment/x",
                          status="watching", message="", resolved_at=None)
    crashing = SimpleNamespace(status=SimpleNamespace(container_statuses=[
        SimpleNamespace(name="app", state=SimpleNamespace(
            waiting=SimpleNamespace(reason="CrashLoopBackOff")))]),
        metadata=SimpleNamespace(name="x-1"))
    apps = _apps([[_dep("x", 0, 1)]])
    core = _core(pods=[crashing])
    with patch("app.services.rollout_watcher.AsyncSessionLocal", lambda: _FakeSession(row)), \
         patch("app.services.rollout_watcher.k8s_service._get_api",
               side_effect=lambda k, context=None: core if k == "CoreV1Api" else apps):
        rw.WATCH_INTERVAL = 0.001
        await rw.watch(2)
    assert row.status == "failed"
    assert "CrashLoopBackOff" in row.message


@pytest.mark.asyncio
async def test_resume_pending_respawns_only_watching_rows(monkeypatch):
    rows = [SimpleNamespace(id=10), SimpleNamespace(id=11)]

    class _ListSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def exec(self, *a, **k): return SimpleNamespace(all=lambda: rows)
    monkeypatch.setattr(rw, "AsyncSessionLocal", lambda: _ListSession())
    spawned = []
    async def _fake_spawn(nid): spawned.append(nid)
    monkeypatch.setattr(rw, "spawn", _fake_spawn)
    n = await rw.resume_pending()
    assert n == 2 and spawned == [10, 11]
