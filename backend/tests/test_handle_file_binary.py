import os, sys, base64, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "minion"))
import blueprint as h  # noqa: E402


def test_inline_base64_writes_bytes(tmp_path):
    raw = bytes(range(256))
    target = tmp_path / "blob.bin"
    st = {"type": "file", "path": str(target), "source": "blob.bin"}
    src = {"blob.bin": {"encoding": "base64", "content": base64.b64encode(raw).decode()}}
    res = h.handle_file(st, src, test=False)
    assert res["result"] is True
    assert target.read_bytes() == raw


def test_inline_base64_idempotent(tmp_path):
    raw = b"\x00\x01binary"
    target = tmp_path / "b.bin"; target.write_bytes(raw)
    st = {"type": "file", "path": str(target), "source": "b.bin"}
    src = {"b.bin": {"encoding": "base64", "content": base64.b64encode(raw).decode()}}
    res = h.handle_file(st, src, test=False)
    assert res["result"] is True and res["changes"] == {}


def test_fetch_entry_downloads_and_verifies(tmp_path):
    raw = b"X" * 2048
    target = tmp_path / "big.bin"
    sha = hashlib.sha256(raw).hexdigest()
    src = {"big.bin": {"encoding": "base64", "fetch": True, "id": "src-1", "sha256": sha, "size": len(raw)}}
    # run_blueprint requires id in each state dict
    results = h.run_blueprint(
        [{"id": "c", "type": "file", "path": str(target), "source": "big.bin"}],
        src, test=False, fetch=lambda sid: raw,
    )
    r = results[0]
    assert r["result"] is True and target.read_bytes() == raw


def test_fetch_sha_mismatch_fails(tmp_path):
    target = tmp_path / "bad.bin"
    st = {"id": "c", "type": "file", "path": str(target), "source": "bad.bin"}
    src = {"bad.bin": {"encoding": "base64", "fetch": True, "id": "src-2", "sha256": "deadbeef", "size": 3}}
    results = h.run_blueprint([st], src, test=False, fetch=lambda sid: b"abc")
    assert results[0]["result"] is False and "checksum" in results[0]["comment"].lower()
    assert not target.exists()


def test_text_path_unchanged(tmp_path):
    target = tmp_path / "n.conf"
    st = {"type": "file", "path": str(target), "source": "n.conf"}
    res = h.handle_file(st, {"n.conf": {"encoding": "utf-8", "content": "server {}"}}, test=False)
    assert res["result"] is True and target.read_text() == "server {}"
    # bare-string entry still works (legacy)
    res2 = h.handle_file(st, {"n.conf": "server {}"}, test=False)
    assert res2["result"] is True and res2["changes"] == {}
