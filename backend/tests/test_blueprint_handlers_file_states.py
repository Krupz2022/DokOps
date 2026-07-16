# New Uyuni-style file states: directory / absent / symlink / append / recurse,
# plus failhard abort and cmd cwd.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "minion"))
import blueprint as h  # noqa: E402


def test_directory_creates_with_parents(tmp_path):
    target = tmp_path / "a" / "b"
    res = h.handle_directory({"path": str(target)}, {}, test=False)
    assert res["result"] is True
    assert target.is_dir()


def test_directory_clean_empties(tmp_path):
    d = tmp_path / "opt"
    (d / "sub").mkdir(parents=True)
    (d / "junk.txt").write_text("x")
    res = h.handle_directory({"path": str(d), "clean": True}, {}, test=False)
    assert res["result"] is True
    assert list(d.iterdir()) == []


def test_directory_test_mode_touches_nothing(tmp_path):
    d = tmp_path / "opt"
    (d / "junk").mkdir(parents=True)
    res = h.handle_directory({"path": str(d), "clean": True}, {}, test=True)
    assert res["result"] is None
    assert (d / "junk").exists()


def test_absent_removes_tree(tmp_path):
    d = tmp_path / "gone"
    (d / "sub").mkdir(parents=True)
    res = h.handle_absent({"path": str(d)}, {}, test=False)
    assert res["result"] is True
    assert not d.exists()
    # idempotent second run
    res2 = h.handle_absent({"path": str(d)}, {}, test=False)
    assert res2["result"] is True and res2["changes"] == {}


def test_append_only_missing_lines(tmp_path):
    f = tmp_path / "hosts"
    f.write_text("one\n")
    st = {"path": str(f), "text": ["one", "two"]}
    res = h.handle_append(st, {}, test=False)
    assert res["result"] is True
    assert f.read_text() == "one\ntwo\n"
    assert h.handle_append(st, {}, test=False)["changes"] == {}


def test_recurse_delivers_tree(tmp_path):
    dest = tmp_path / "prereq"
    sources = {
        "prereq/run.sh": "echo hi",
        "prereq/bin/x.txt": {"encoding": "utf-8", "content": "data"},
        "other/skip.txt": "no",
    }
    st = {"type": "file.recurse", "path": str(dest), "source": "prereq"}
    res = h.handle_recurse(st, sources, test=False)
    assert res["result"] is True
    assert (dest / "run.sh").read_text() == "echo hi"
    assert (dest / "bin" / "x.txt").read_text() == "data"
    assert not (dest / "skip.txt").exists()
    # second run: no changes
    assert h.handle_recurse(st, sources, test=False)["changes"] == {}


def test_recurse_no_sources_fails(tmp_path):
    res = h.handle_recurse({"path": str(tmp_path), "source": "nope"}, {}, test=False)
    assert res["result"] is False


def test_name_accepted_as_path_alias(tmp_path):
    target = tmp_path / "via-name"
    res = h.handle_directory({"name": str(target)}, {}, test=False)
    assert res["result"] is True and target.is_dir()


def test_file_without_source_keeps_content(tmp_path):
    # attrs-only mode: no source must NEVER touch the file's content
    f = tmp_path / "script.py"
    f.write_text("print('hi')")
    st = {"type": "file.managed", "name": str(f), "mode": "0755"}
    res = h.handle_file(st, {}, test=False)
    assert res["result"] is True
    assert f.read_text() == "print('hi')"


def test_file_without_source_fails_if_missing(tmp_path):
    res = h.handle_file({"type": "file", "path": str(tmp_path / "nope")}, {}, test=False)
    assert res["result"] is False


def test_mode_accepts_int_and_string():
    assert h._mode("0755") == 0o755
    assert h._mode(0o755) == 0o755  # YAML `mode: 0755` arrives as octal int


def test_failhard_aborts_rest(monkeypatch):
    monkeypatch.setattr(h, "handle_pkg", lambda s, src, t: {"result": False, "changes": {}, "comment": "boom"})
    ran = []
    monkeypatch.setattr(h, "handle_cmd", lambda s, src, t: (ran.append(s["id"]), {"result": True, "changes": {}, "comment": ""})[1])
    states = [
        {"id": "bad", "type": "pkg", "name": "x", "failhard": True},
        {"id": "later", "type": "cmd", "name": "echo hi"},
    ]
    results = h.run_blueprint(states, {}, test=False)
    later = next(r for r in results if r["id"] == "later")
    assert later["result"] is False
    assert "failhard" in later["comment"]
    assert ran == []


def test_cmd_cwd_passed_through(monkeypatch):
    seen = {}
    def fake_run(cmd, shell=False, cwd=None):
        seen["cwd"] = cwd
        return 0, ""
    monkeypatch.setattr(h, "_run", fake_run)
    res = h.handle_cmd({"name": "unzip x.zip", "cwd": "/opt/prereq"}, {}, test=False)
    assert res["result"] is True
    assert seen["cwd"] == "/opt/prereq"


def test_collect_sources_prefix_match():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from app.services.blueprint_service import collect_referenced_sources

    class Src:
        def __init__(self, name):
            self.name, self.encoding, self.content = name, "utf-8", "x"

    pool = {n: Src(n) for n in ("prereq/a.sh", "prereq/bin/b", "other/c", "single.conf")}
    states = [
        {"type": "file.recurse", "source": "prereq", "path": "/opt/prereq"},
        {"type": "file.managed", "source": "single.conf", "path": "/etc/x"},
    ]
    out = collect_referenced_sources(states, pool)
    assert set(out) == {"prereq/a.sh", "prereq/bin/b", "single.conf"}
