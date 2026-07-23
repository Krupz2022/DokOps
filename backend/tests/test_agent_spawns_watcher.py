import pytest
from unittest.mock import AsyncMock, patch

from app.services import rollout_watcher as rw


@pytest.mark.asyncio
async def test_start_rollout_watch_inserts_row_and_spawns():
    captured = {}

    class _Sess:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def add(self, obj): captured["row"] = obj
        async def commit(self): pass
        async def refresh(self, obj): obj.id = 99

    with patch("app.services.rollout_watcher.AsyncSessionLocal", lambda: _Sess()), \
         patch("app.services.rollout_watcher.spawn", new=AsyncMock()) as mock_spawn:
        obs = await rw.start_rollout_watch("conv-1", 1, "ns", "deployment/x")

    assert captured["row"].status == "watching"
    assert captured["row"].conversation_id == "conv-1"
    assert captured["row"].user_id == 1
    mock_spawn.assert_awaited_once_with(99)
    assert "watch" in obs.lower() and "do not" in obs.lower()
