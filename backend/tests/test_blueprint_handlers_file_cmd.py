import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "minion"))
import blueprint as h  # noqa: E402


def test_file_creates_when_missing(tmp_path):
    target = tmp_path / "nginx.conf"
    st = {"type": "file", "path": str(target), "source": "nginx.conf"}
    res = h.handle_file(st, {"nginx.conf": "server {}"}, test=False)
    assert res["result"] is True
    assert res["changes"]  # old absent -> new present
    assert target.read_text() == "server {}"


def test_file_test_mode_does_not_write(tmp_path):
    target = tmp_path / "nginx.conf"
    st = {"type": "file", "path": str(target), "source": "nginx.conf"}
    res = h.handle_file(st, {"nginx.conf": "server {}"}, test=True)
    assert res["result"] is None  # would change
    assert not target.exists()


def test_file_no_change_when_identical(tmp_path):
    target = tmp_path / "nginx.conf"
    target.write_text("server {}")
    st = {"type": "file", "path": str(target), "source": "nginx.conf"}
    res = h.handle_file(st, {"nginx.conf": "server {}"}, test=False)
    assert res["result"] is True
    assert res["changes"] == {}


def test_cmd_unless_skips(monkeypatch):
    # unless probe returns 0 -> already satisfied -> skip
    monkeypatch.setattr(h, "_run", lambda cmd, shell=False: (0, ""))
    st = {"type": "cmd", "name": "touch /x", "unless": "test -f /x"}
    res = h.handle_cmd(st, {}, test=False)
    assert res["result"] is True
    assert res["changes"] == {}


def test_cmd_runs_when_unless_fails(monkeypatch):
    calls = []
    def fake_run(cmd, shell=False):
        calls.append(cmd)
        return (1, "") if "test -f" in str(cmd) else (0, "done")
    monkeypatch.setattr(h, "_run", fake_run)
    st = {"type": "cmd", "name": "touch /x", "unless": "test -f /x"}
    res = h.handle_cmd(st, {}, test=False)
    assert res["result"] is True
    assert res["changes"] == {"executed": "touch /x"}
