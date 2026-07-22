import asyncio
import base64

from app.models.blueprint import BlueprintSource
from app.services.blueprint_service import source_entry, INLINE_MAX_BYTES, collect_referenced_sources


def test_text_entry():
    s = BlueprintSource(blueprint_id="b", name="a.conf", content="hello", encoding="utf-8")
    assert asyncio.run(source_entry(s)) == {"encoding": "utf-8", "content": "hello"}


def test_small_binary_inline():
    raw = b"\x00\x01\x02BIN"
    s = BlueprintSource(blueprint_id="b", name="a.bin", content=base64.b64encode(raw).decode(), encoding="base64")
    assert asyncio.run(source_entry(s)) == {"encoding": "base64", "content": base64.b64encode(raw).decode()}


def test_large_binary_fetch():
    raw = b"x" * (INLINE_MAX_BYTES + 10)
    s = BlueprintSource(id="src-9", blueprint_id="b", name="big.bin",
                        content=base64.b64encode(raw).decode(), encoding="base64")
    e = asyncio.run(source_entry(s))
    assert e["fetch"] is True and e["id"] == "src-9" and e["size"] == len(raw)
    assert "content" not in e and len(e["sha256"]) == 64


def test_collect_filters_and_wraps():
    states = [{"id": "c", "type": "file", "source": "a.conf"}]
    pool = {
        "a.conf": BlueprintSource(blueprint_id="b", name="a.conf", content="data", encoding="utf-8"),
        "unused": BlueprintSource(blueprint_id="b", name="unused", content="x", encoding="utf-8"),
    }
    assert asyncio.run(collect_referenced_sources(states, pool)) == {
        "a.conf": {"encoding": "utf-8", "content": "data"}
    }


# ── disk-backed sources ───────────────────────────────────────────────────────

def _disk_src(tmp_path, rel, blob, **kw):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(blob)
    return BlueprintSource(blueprint_id="b", name=p.name, origin="disk",
                           rel_path=rel, size=len(blob), **kw)


def test_disk_small_text_inlines(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.blueprint_service.resolve_source_path",
                        lambda rel, root=None: tmp_path / rel)
    s = _disk_src(tmp_path, "common/files/motd", b"hello")
    assert asyncio.run(source_entry(s)) == {"encoding": "utf-8", "content": "hello"}


def test_disk_small_binary_inlines_as_base64(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.blueprint_service.resolve_source_path",
                        lambda rel, root=None: tmp_path / rel)
    blob = b"\x00\xffBIN"
    s = _disk_src(tmp_path, "common/files/a.bin", blob)
    assert asyncio.run(source_entry(s)) == {
        "encoding": "base64", "content": base64.b64encode(blob).decode()
    }


def test_disk_large_never_reads_file(tmp_path, monkeypatch):
    """A multi-GB artifact must be measured from src.size, not by reading it."""
    monkeypatch.setattr("app.services.blueprint_service.resolve_source_path",
                        lambda rel, root=None: tmp_path / rel)
    s = _disk_src(tmp_path, "common/files/big.bin", b"tiny-on-disk")
    s.size = INLINE_MAX_BYTES + 1        # claims to be huge
    s.sha256 = "a" * 64                  # already cached, so no hashing either

    e = asyncio.run(source_entry(s))
    assert e["fetch"] is True and e["size"] == INLINE_MAX_BYTES + 1
    assert e["sha256"] == "a" * 64 and "content" not in e


def test_disk_large_always_ships_a_checksum(tmp_path, monkeypatch):
    """The agent only verifies when sha256 is present — a fetch ref must never omit it."""
    monkeypatch.setattr("app.services.blueprint_service.resolve_source_path",
                        lambda rel, root=None: tmp_path / rel)
    blob = b"y" * (INLINE_MAX_BYTES + 5)
    s = _disk_src(tmp_path, "common/files/big.bin", blob)
    assert s.sha256 is None              # never hashed during seed

    e = asyncio.run(source_entry(s))
    import hashlib
    assert e["sha256"] == hashlib.sha256(blob).hexdigest()
    assert s.sha256 == e["sha256"]       # cached back onto the row
