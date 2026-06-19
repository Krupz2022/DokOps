import json
from types import SimpleNamespace
import pytest

from app.services.cached_ai_client import CachingAIClient


@pytest.mark.asyncio
async def test_complete_gemini_returns_text(monkeypatch):
    captured = {}

    def fake_generate(client, model, contents, tools=None):
        captured["model"] = model
        return SimpleNamespace(text="hello world", function_calls=[])

    monkeypatch.setattr("app.services.gemini_compat.generate", fake_generate)
    monkeypatch.setattr("app.services.gemini_compat.extract_function_calls", lambda r: [])

    c = CachingAIClient(provider="GEMINI", client=object(), model="gemini-2.5-pro",
                        fast_model=None, fast_client=object(), tiering_enabled=False)
    text, calls = await c._complete_gemini([{"role": "user", "content": "hi"}], [], object(), "gemini-2.5-pro")
    assert text == "hello world"
    assert calls is None
    assert captured["model"] == "gemini-2.5-pro"
