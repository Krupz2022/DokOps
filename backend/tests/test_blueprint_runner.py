# backend/tests/test_blueprint_runner.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "minion"))
import blueprint as h  # noqa: E402


def test_order_respects_require():
    states = [
        {"id": "svc", "type": "service", "name": "nginx", "require": ["pkg"]},
        {"id": "pkg", "type": "pkg", "name": "nginx"},
    ]
    ordered = [s["id"] for s in h.order_resources(states)]
    assert ordered.index("pkg") < ordered.index("svc")


def test_cycle_raises():
    states = [
        {"id": "a", "type": "cmd", "name": "x", "require": ["b"]},
        {"id": "b", "type": "cmd", "name": "y", "require": ["a"]},
    ]
    try:
        h.order_resources(states)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_failed_require_skips_dependent(monkeypatch):
    monkeypatch.setattr(h, "handle_pkg", lambda s, src, t: {"result": False, "changes": {}, "comment": "boom"})
    states = [
        {"id": "pkg", "type": "pkg", "name": "nginx"},
        {"id": "svc", "type": "service", "name": "nginx", "require": ["pkg"]},
    ]
    results = h.run_blueprint(states, {}, test=False)
    svc = next(r for r in results if r["id"] == "svc")
    assert svc["result"] is False
    assert "requisite" in svc["comment"].lower()


def test_watch_triggers_service_restart(monkeypatch):
    monkeypatch.setattr(h, "handle_file", lambda s, src, t: {"result": True, "changes": {"old": "a", "new": "b"}, "comment": ""})
    monkeypatch.setattr(h, "handle_service", lambda s, src, t: {"result": True, "changes": {}, "comment": "ok"})
    reacted = {}
    monkeypatch.setattr(h, "_service_react", lambda s, t: (reacted.setdefault(s["id"], True), {"result": True, "changes": {"restart": "x"}, "comment": "restarted"})[1])
    states = [
        {"id": "conf", "type": "file", "path": "/x", "source": "c"},
        {"id": "svc", "type": "service", "name": "nginx", "watch": ["conf"]},
    ]
    results = h.run_blueprint(states, {"c": "data"}, test=False)
    svc = next(r for r in results if r["id"] == "svc")
    assert reacted == {"svc": True}
    assert "restart" in svc["changes"]
