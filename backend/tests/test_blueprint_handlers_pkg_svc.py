import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "minion"))
import blueprint as h  # noqa: E402


def test_pkg_present_installs_when_missing(monkeypatch):
    monkeypatch.setattr(h, "IS_WINDOWS", False)
    monkeypatch.setattr(h, "_pkg_manager", lambda: "dpkg")
    monkeypatch.setattr(h, "_pkg_installed", lambda name: False)
    installed = {}
    monkeypatch.setattr(h, "_pkg_install", lambda name: (installed.setdefault(name, True), (0, "ok"))[1])
    res = h.handle_pkg({"type": "pkg", "name": "nginx", "ensure": "present"}, {}, test=False)
    assert res["result"] is True
    assert res["changes"] == {"old": "absent", "new": "installed"}
    assert installed == {"nginx": True}


def test_pkg_present_test_mode(monkeypatch):
    monkeypatch.setattr(h, "_pkg_installed", lambda name: False)
    res = h.handle_pkg({"type": "pkg", "name": "nginx", "ensure": "present"}, {}, test=True)
    assert res["result"] is None


def test_pkg_present_noop_when_installed(monkeypatch):
    monkeypatch.setattr(h, "_pkg_installed", lambda name: True)
    res = h.handle_pkg({"type": "pkg", "name": "nginx", "ensure": "present"}, {}, test=False)
    assert res["result"] is True
    assert res["changes"] == {}


def test_service_running_starts_when_inactive(monkeypatch):
    monkeypatch.setattr(h, "_svc_is_active", lambda name: False)
    monkeypatch.setattr(h, "_svc_is_enabled", lambda name: True)
    started = {}
    monkeypatch.setattr(h, "_svc_start", lambda name: (started.setdefault(name, True), (0, ""))[1])
    res = h.handle_service({"type": "service", "name": "nginx", "ensure": "running"}, {}, test=False)
    assert res["result"] is True
    assert "start" in str(res["changes"]).lower() or started == {"nginx": True}
