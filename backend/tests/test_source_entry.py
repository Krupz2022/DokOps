import base64
from app.models.blueprint import BlueprintSource
from app.services.blueprint_service import source_entry, INLINE_MAX_BYTES, collect_referenced_sources


def test_text_entry():
    s = BlueprintSource(blueprint_id="b", name="a.conf", content="hello", encoding="utf-8")
    assert source_entry(s) == {"encoding": "utf-8", "content": "hello"}


def test_small_binary_inline():
    raw = b"\x00\x01\x02BIN"
    s = BlueprintSource(blueprint_id="b", name="a.bin", content=base64.b64encode(raw).decode(), encoding="base64")
    assert source_entry(s) == {"encoding": "base64", "content": base64.b64encode(raw).decode()}


def test_large_binary_fetch():
    raw = b"x" * (INLINE_MAX_BYTES + 10)
    s = BlueprintSource(id="src-9", blueprint_id="b", name="big.bin",
                        content=base64.b64encode(raw).decode(), encoding="base64")
    e = source_entry(s)
    assert e["fetch"] is True and e["id"] == "src-9" and e["size"] == len(raw)
    assert "content" not in e and len(e["sha256"]) == 64


def test_collect_filters_and_wraps():
    states = [{"id": "c", "type": "file", "source": "a.conf"}]
    pool = {
        "a.conf": BlueprintSource(blueprint_id="b", name="a.conf", content="data", encoding="utf-8"),
        "unused": BlueprintSource(blueprint_id="b", name="unused", content="x", encoding="utf-8"),
    }
    assert collect_referenced_sources(states, pool) == {"a.conf": {"encoding": "utf-8", "content": "data"}}
