import logging
from typing import Optional
from app.core import settings_cache

_log = logging.getLogger("dokops.context_manager")

_CHARS_PER_TOKEN = 4

_TIKTOKEN_ENC = None


def _get_tiktoken_enc():
    global _TIKTOKEN_ENC
    if _TIKTOKEN_ENC is None:
        import tiktoken
        _TIKTOKEN_ENC = tiktoken.get_encoding("cl100k_base")
    return _TIKTOKEN_ENC

CONTEXT_WINDOWS: dict[str, int] = {
    "OPENAI":  128_000,
    "AZURE":   128_000,
    "GEMINI":  900_000,
    "OLLAMA":   32_000,
}

TOOL_SUMMARIZATION_PROMPT = (
    "You are summarizing a DevOps tool output for an AI investigation. "
    "Preserve ALL of the following verbatim: error messages, exception types, "
    "stack trace first lines, resource names, pod names, namespaces, image names, "
    "node names, exit codes, HTTP status codes, memory limits, replica counts, "
    "timestamps of significant events. "
    "Drop: repeated identical lines, decorative ASCII borders, pagination metadata, empty lines. "
    "Output only the summary — no explanation, no preamble."
)

CONVERSATION_COMPACTION_PROMPT = (
    "You are summarizing an ongoing DevOps investigation conversation. "
    "Your output MUST include exactly these sections:\n"
    "ORIGINAL QUESTION: <quote the user's first question verbatim>\n"
    "TOOLS CALLED: <one line per tool: tool_name → key finding>\n"
    "CONFIRMED FACTS: <key: value pairs — pod name, namespace, error type, image, exit code, etc.>\n"
    "CURRENT HYPOTHESIS: <root cause hypothesis if one has emerged, else 'none yet'>\n"
    "NOT YET CHECKED: <what still needs investigation>\n"
    "Output only these sections — no extra commentary."
)


class ContextManager:
    def _get_setting(self, key: str) -> Optional[str]:
        # Stays synchronous (called from both sync and async contexts; tests mock it
        # as a sync MagicMock), but routes through the process-wide settings cache so
        # an event-loop call doesn't block on a per-call DB round-trip (Recipe R8).
        return settings_cache.get_setting(key)

    def count_tokens(self, text: str, provider: str) -> int:
        if provider in ("OPENAI", "AZURE"):
            try:
                enc = _get_tiktoken_enc()
                return len(enc.encode(text))
            except Exception:
                _log.warning("[CONTEXT] tiktoken unavailable, falling back to char estimate")
        return len(text) // _CHARS_PER_TOKEN

    def check_budget(self, messages: list, provider: str) -> tuple[int, int, float]:
        limit = CONTEXT_WINDOWS.get(provider, 32_000)
        used = sum(
            self.count_tokens(str(m.get("content") or ""), provider)
            for m in messages
        )
        pct = used / limit if limit else 0.0
        return used, limit, pct

    async def trim_tool_result(
        self,
        tool_name: str,
        result: str,
        provider: str,
        caching_client,
    ) -> str:
        budget = int(self._get_setting("ctx_tool_budget") or "3000")
        tokens = self.count_tokens(result, provider)
        if tokens <= budget:
            return result

        prompt = [
            {"role": "system", "content": TOOL_SUMMARIZATION_PROMPT},
            {"role": "user", "content": f"Tool: {tool_name}\n\nOutput:\n{result}"},
        ]
        try:
            summary, _ = await caching_client.complete(
                prompt, [], tier="fast", disable_trimming=True
            )
            summary_tokens = self.count_tokens(summary or "", provider)
            return f"[Summarized ~{tokens} → {summary_tokens} tokens]\n{summary or ''}"
        except Exception as exc:
            _log.warning("[CONTEXT] trim_tool_result failed (%s) — falling back to truncation", exc)
            chars = budget * _CHARS_PER_TOKEN
            return f"[Truncated — summarization unavailable, showing tail]\n...{result[-chars:]}"

    async def compact_conversation(
        self,
        messages: list,
        provider: str,
        caching_client,
    ) -> tuple[list, str]:
        keep_pairs = int(self._get_setting("ctx_keep_recent") or "6")
        keep_count = keep_pairs * 2  # user + assistant per pair

        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        if len(non_system) <= keep_count:
            return messages, ""

        candidates = non_system[:-keep_count]
        protected = non_system[-keep_count:]

        combined = "\n".join(
            f"{m['role'].upper()}: {str(m.get('content') or '')[:500]}"
            for m in candidates
        )
        prompt = [
            {"role": "system", "content": CONVERSATION_COMPACTION_PROMPT},
            {"role": "user", "content": combined},
        ]
        try:
            summary, _ = await caching_client.complete(
                prompt, [], tier="fast", disable_trimming=True
            )
        except Exception as exc:
            _log.warning("[CONTEXT] compact_conversation failed (%s) — keeping original", exc)
            return messages, ""

        summary_text = summary or ""
        summary_msg = {
            "role": "system",
            "content": f"[Investigation Summary]\n{summary_text}",
        }
        compacted = system_msgs + [summary_msg] + protected
        return compacted, summary_text


context_manager = ContextManager()
