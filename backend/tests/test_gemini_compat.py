import json
from types import SimpleNamespace
import pytest

from app.services import gemini_compat


def test_resolve_model_default():
    assert gemini_compat.resolve_model(None) == "gemini-2.0-flash"
    assert gemini_compat.resolve_model("") == "gemini-2.0-flash"
    assert gemini_compat.resolve_model("gemini-2.5-pro") == "gemini-2.5-pro"


def test_to_gemini_tools_wraps_declarations():
    schema = [{"function_declarations": [
        {"name": "get_logs", "description": "d", "parameters": {"type": "object", "properties": {}}}
    ]}]
    tools = gemini_compat.to_gemini_tools(schema)
    assert len(tools) == 1
    # Each entry exposes the declarations it was built from.
    decls = tools[0].function_declarations
    assert decls[0].name == "get_logs"


def test_extract_function_calls_normalizes():
    fc = SimpleNamespace(name="get_logs", args={"namespace": "default"})
    part = SimpleNamespace(function_call=fc)
    candidate = SimpleNamespace(content=SimpleNamespace(parts=[part]))
    response = SimpleNamespace(candidates=[candidate], function_calls=[fc])
    calls = gemini_compat.extract_function_calls(response)
    assert calls[0].function.name == "get_logs"
    assert json.loads(calls[0].function.arguments) == {"namespace": "default"}
    assert calls[0].id == "gemini_get_logs"
