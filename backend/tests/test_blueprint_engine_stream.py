import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "minion"))
import blueprint as h  # noqa: E402


def test_run_blueprint_streams_events_for_cmd():
    events = []
    states = [{"id": "echo1", "type": "cmd", "name": "echo streaming-line"}]
    results = h.run_blueprint(states, {}, test=False, emit=events.append)

    kinds = [e["kind"] for e in events]
    assert kinds[0] == "resource_start" and events[0]["id"] == "echo1"
    assert kinds[-1] == "resource_result" and events[-1]["id"] == "echo1"
    # at least one streamed log line carrying the command output
    log_lines = [e["line"] for e in events if e["kind"] == "log"]
    assert any("streaming-line" in ln for ln in log_lines)
    # return value still the normal results list with captured output
    assert results[0]["result"] is True
    assert "streaming-line" in results[0]["output"]


def test_emit_none_is_unchanged():
    states = [{"id": "c", "type": "cmd", "name": "echo hi"}]
    results = h.run_blueprint(states, {}, test=False)  # no emit
    assert results[0]["result"] is True
    assert "hi" in results[0]["output"]
