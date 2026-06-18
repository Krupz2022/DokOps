import asyncio
import logging
import re
from typing import Any, Optional

_log = logging.getLogger("dokops.cached_ai_client")
_CHARS_PER_TOKEN = 4

_DEFAULT_FAST_MODELS: dict[str, str] = {
    "OPENAI": "gpt-4o-mini",
    "AZURE": "gpt-4o-mini",
    "GEMINI": "gemini-2.0-flash",
    "ANTHROPIC": "claude-haiku-4-5-20251001",
}


def trim_messages(messages: list[dict[str, Any]], keep_tool_results: int, token_cap: int) -> list[dict[str, Any]]:
    """
    Trim stale tool result messages to stay within token budget.

    System and assistant messages are never trimmed.
    The most recent `keep_tool_results` tool results are kept verbatim.
    Older ones are replaced with a one-line summary.
    If total estimated tokens still exceeds token_cap, oldest tool results are dropped entirely.
    """
    tool_result_indices = [
        i for i, m in enumerate(messages) if m.get("role") == "tool"
    ]
    n_to_summarize = max(0, len(tool_result_indices) - keep_tool_results)
    summarize_set = set(tool_result_indices[:n_to_summarize])

    result = []
    for i, m in enumerate(messages):
        if i in summarize_set:
            content = str(m.get("content") or "")
            result.append({
                **m,
                "content": f"[trimmed] {m.get('tool_call_id', 'tool')} returned {len(content)} chars",
            })
        else:
            result.append(dict(m))

    total_chars = sum(len(str(m.get("content") or "")) for m in result)
    if total_chars > token_cap * _CHARS_PER_TOKEN:
        for i, m in enumerate(result):
            if total_chars <= token_cap * _CHARS_PER_TOKEN:
                break
            if m.get("role") == "tool" and not str(m.get("content", "")).startswith("[dropped]"):
                old_len = len(str(m.get("content") or ""))
                result[i] = {**m, "content": "[dropped]"}
                total_chars -= old_len - len("[dropped]")

    return result


class CachingAIClient:
    """
    Provider-aware AI client wrapper.
    Handles model tiering (fast/full), fast-model fallback, and message trimming.
    Returns (text, tool_calls) — same shape as the old _call_model methods.
    """

    def __init__(
        self,
        provider: str,
        client: Any,
        model: str,
        fast_model: Optional[str] = None,
        fast_client: Any = None,
        tiering_enabled: bool = True,
    ):
        self._provider = provider
        self._client = client
        self._model = model
        self._fast_model = fast_model
        self._fast_client = fast_client if fast_client is not None else client
        self._tiering_enabled = tiering_enabled

    @property
    def full_model(self) -> str:
        return self._model

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list,
        tier: str = "full",
        disable_trimming: bool = False,
        trim_keep: int = 10,
        trim_token_cap: int = 16000,
    ) -> tuple:
        """
        Send messages to the configured provider.

        tier="fast" uses the cheaper fast model when tiering is enabled.
        Falls back to the full model silently if the fast model call fails.
        """
        msgs = messages if disable_trimming else trim_messages(messages, trim_keep, trim_token_cap)

        use_fast = (
            tier == "fast"
            and self._tiering_enabled
            and self._fast_model is not None
        )
        model = self._fast_model if use_fast else self._model
        client = self._fast_client if use_fast else self._client

        try:
            return await self._dispatch(msgs, tools, client, model)
        except Exception as exc:
            if use_fast:
                _log.warning(
                    "Fast model %s failed (%s) — falling back to %s", model, exc, self._model
                )
                return await self._dispatch(msgs, tools, self._client, self._model)
            raise

    async def _dispatch(self, messages: list[dict[str, Any]], tools: list, client, model: str) -> tuple:
        if self._provider == "GEMINI":
            return await self._complete_gemini(messages, tools, client)
        return await self._complete_openai(messages, tools, client, model)

    async def _complete_openai(self, messages: list[dict[str, Any]], tools: list, client, model: str) -> tuple:
        _TIMEOUT = 300  # seconds — prevents infinite hangs on slow/reasoning models
        try:
            kwargs: dict = {"model": model, "messages": messages}
            if tools:
                kwargs["tools"] = tools
                # Some reasoning models (o1, o3, gpt-5.x) don't support tool_choice; omit it and
                # let the model decide — "auto" is the default behaviour anyway.
                if not any(m in model.lower() for m in ("o1", "o3", "o4", "gpt-5")):
                    kwargs["tool_choice"] = "auto"
            _log.info("[OPENAI] POST chat/completions model=%s messages=%d tools=%d tool_choice=%s",
                      model, len(messages), len(tools), kwargs.get("tool_choice", "omitted"))
            response = await asyncio.wait_for(
                asyncio.to_thread(client.chat.completions.create, **kwargs),
                timeout=_TIMEOUT,
            )
            msg = response.choices[0].message
            _log.info("[OPENAI] response: tool_calls=%s content_len=%s finish_reason=%s",
                      len(msg.tool_calls) if msg.tool_calls else 0,
                      len(msg.content) if msg.content else 0,
                      response.choices[0].finish_reason)
            # Fire-and-forget token capture
            try:
                from app.core.token_context import _token_queue, ai_user_id, ai_source
                from datetime import datetime as _dt
                _usage = getattr(response, "usage", None)
                if _usage and (_usage.prompt_tokens or _usage.completion_tokens):
                    _cached = 0
                    _details = getattr(_usage, "prompt_tokens_details", None)
                    if _details is not None:
                        _cached = getattr(_details, "cached_tokens", 0) or 0
                    _token_queue.put_nowait({
                        "user_id": ai_user_id.get(),
                        "source": ai_source.get(),
                        "model": model,
                        "input_tokens": _usage.prompt_tokens,
                        "output_tokens": _usage.completion_tokens,
                        "cached_tokens": _cached,
                        "created_at": _dt.utcnow(),
                    })
            except Exception:
                pass
            if msg.tool_calls:
                return None, msg.tool_calls
            raw = msg.content or ""
            return self._strip_tool_echo(raw), None
        except asyncio.TimeoutError:
            _log.error("[OPENAI] TIMEOUT after %ds model=%s", _TIMEOUT, model)
            raise RuntimeError(f"AI call timed out after {_TIMEOUT}s (model={model})")
        except Exception as exc:
            _log.error("[OPENAI] EXCEPTION model=%s err=%s", model, exc)
            err = str(exc).lower()
            if tools and any(k in err for k in ("tool", "function", "tool_choice", "context", "token", "length")):
                _log.info("[OPENAI] retrying without tools model=%s", model)
                response = await asyncio.wait_for(
                    asyncio.to_thread(client.chat.completions.create, model=model, messages=messages),
                    timeout=_TIMEOUT,
                )
                # Fire-and-forget token capture
                try:
                    from app.core.token_context import _token_queue, ai_user_id, ai_source
                    from datetime import datetime as _dt
                    _usage = getattr(response, "usage", None)
                    if _usage and (_usage.prompt_tokens or _usage.completion_tokens):
                        _cached = 0
                        _details = getattr(_usage, "prompt_tokens_details", None)
                        if _details is not None:
                            _cached = getattr(_details, "cached_tokens", 0) or 0
                        _token_queue.put_nowait({
                            "user_id": ai_user_id.get(),
                            "source": ai_source.get(),
                            "model": model,
                            "input_tokens": _usage.prompt_tokens,
                            "output_tokens": _usage.completion_tokens,
                            "cached_tokens": _cached,
                            "created_at": _dt.utcnow(),
                        })
                except Exception:
                    pass
                return self._strip_tool_echo(response.choices[0].message.content or ""), None
            raise

    async def _complete_gemini(self, messages: list[dict[str, Any]], tools: list, client) -> tuple:
        import json
        from types import SimpleNamespace
        from app.tools.registry import build_gemini_tools_schema

        gemini_tools = build_gemini_tools_schema()
        text_prompt = "\n".join(
            f"{m['role'].upper()}: {m.get('content', '')}"
            for m in messages
            if m.get("content")
        )
        try:
            response = await asyncio.to_thread(client.generate_content, text_prompt, tools=gemini_tools)
            normalized = []
            for part in response.candidates[0].content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    normalized.append(SimpleNamespace(
                        id=f"gemini_{fc.name}",
                        function=SimpleNamespace(
                            name=fc.name,
                            arguments=json.dumps(dict(fc.args)),
                        ),
                    ))
            if normalized:
                return None, normalized
            return response.text, None
        except Exception as _gemini_exc:
            _log.warning("Gemini tool-calling failed (%s) — falling back to text-only", _gemini_exc)
            response = await asyncio.to_thread(client.generate_content, text_prompt)
            return response.text, None

    @staticmethod
    def _strip_tool_echo(text: str) -> str:
        if not text or "to=" not in text:
            return text
        cleaned = re.sub(r'(?:to=\w+\s+[^\n]*\n*)+', '', text, flags=re.DOTALL).strip()
        return cleaned if cleaned else text.strip()
