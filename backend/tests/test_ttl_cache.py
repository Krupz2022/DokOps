# backend/tests/test_ttl_cache.py
from app.core.ttl_cache import TTLCache


def test_get_returns_set_value():
    cache = TTLCache(ttl_seconds=10.0)
    cache.set("k", "v")
    assert cache.get("k") == "v"


def test_get_missing_returns_none():
    cache = TTLCache(ttl_seconds=10.0)
    assert cache.get("absent") is None


def test_value_expires_after_ttl():
    clock = {"t": 0.0}
    cache = TTLCache(ttl_seconds=10.0, time_func=lambda: clock["t"])
    cache.set("k", "v")
    clock["t"] = 9.9
    assert cache.get("k") == "v"        # still within TTL
    clock["t"] = 10.0
    assert cache.get("k") is None       # expired


def test_invalidate_drops_key():
    cache = TTLCache(ttl_seconds=10.0)
    cache.set("k", "v")
    cache.invalidate("k")
    assert cache.get("k") is None


def test_invalidate_all_clears_everything():
    cache = TTLCache(ttl_seconds=10.0)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.invalidate_all()
    assert cache.get("a") is None
    assert cache.get("b") is None
