# backend/app/core/settings_cache.py
"""Process-wide cache for SystemSetting rows.

Loads the entire (small) settings table in one query and caches it as a dict
for a short TTL. Per-key reads then avoid a DB round-trip. Setting-write
endpoints must call invalidate() after committing so UI changes are reflected
immediately; the TTL is a safety net for multi-process deployments.
"""
from typing import Dict, Optional

from app.core.ttl_cache import TTLCache

_ALL_KEY = "__all_settings__"
_cache = TTLCache(ttl_seconds=10.0)


def _load_all() -> Dict[str, str]:
    from sqlmodel import Session, select
    from app.core.db import sync_engine
    from app.models.setting import SystemSetting

    # NOTE: intentionally synchronous against sync_engine — called from non-event-loop
    # contexts and hot caches. See async-db-migration plan, Recipe R8.
    with Session(sync_engine) as session:
        rows = session.exec(select(SystemSetting)).all()
        return {row.key: row.value for row in rows}


def get_setting(key: str) -> Optional[str]:
    settings_map = _cache.get(_ALL_KEY)
    if settings_map is None:
        settings_map = _load_all()
        _cache.set(_ALL_KEY, settings_map)
    return settings_map.get(key)


def invalidate() -> None:
    """Drop the cached settings snapshot. Call after any SystemSetting write."""
    _cache.invalidate(_ALL_KEY)
