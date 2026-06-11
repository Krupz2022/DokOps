# backend/app/core/ttl_cache.py
"""Thread-safe TTL cache for low-write / high-read data.

Intended for things like system settings and the active integration registry
that are read on every request but change rarely. Reads are lock-protected and
O(1); writers must call invalidate()/invalidate_all() to force a refresh.
"""
import threading
import time as _time
from typing import Any, Callable, Dict, Optional, Tuple


class TTLCache:
    def __init__(
        self,
        ttl_seconds: float = 10.0,
        time_func: Callable[[], float] = _time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._now = time_func
        self._lock = threading.RLock()
        self._store: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if self._now() >= expires_at:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (self._now() + self._ttl, value)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def invalidate_all(self) -> None:
        with self._lock:
            self._store.clear()
