"""Compatibility layer over the `google-genai` SDK.

Single touch-point for the Gemini SDK so the rest of the codebase stays
SDK-agnostic. Replaces the deprecated `google-generativeai` package and its
retired `gemini-pro` model.
"""
import json
from types import SimpleNamespace
from typing import Any, List, Optional

from google import genai
from google.genai import types

_DEFAULT_MODEL = "gemini-2.0-flash"


def make_client(api_key: str) -> genai.Client:
    """Construct a google-genai client from an API key."""
    return genai.Client(api_key=api_key)


def resolve_model(configured: Optional[str]) -> str:
    """Return the configured model id, or the default if unset/blank."""
    return configured or _DEFAULT_MODEL


def to_gemini_tools(schema: List[dict]) -> List[types.Tool]:
    """Convert the legacy [{"function_declarations": [...]}] schema into
    a list of google-genai types.Tool objects."""
    tools: List[types.Tool] = []
    for entry in schema or []:
        decls = entry.get("function_declarations", [])
        if decls:
            tools.append(types.Tool(function_declarations=decls))
    return tools


def generate(client: genai.Client, model: str, contents: str,
             tools: Optional[List[dict]] = None) -> Any:
    """Synchronous generate_content call. Callers wrap in asyncio.to_thread."""
    config = None
    if tools:
        config = types.GenerateContentConfig(tools=to_gemini_tools(tools))
    return client.models.generate_content(model=model, contents=contents, config=config)


def extract_function_calls(response: Any) -> list:
    """Normalize Gemini function calls into the SimpleNamespace shape the
    agentic loop already consumes: .id, .function.name, .function.arguments."""
    normalized = []
    calls = getattr(response, "function_calls", None) or []
    for fc in calls:
        normalized.append(SimpleNamespace(
            id=f"gemini_{fc.name}",
            function=SimpleNamespace(
                name=fc.name,
                arguments=json.dumps(dict(fc.args or {})),
            ),
        ))
    return normalized
