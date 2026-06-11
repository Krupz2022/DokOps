import contextvars
from typing import Dict

# In-memory write-through cache so hot-path checks don't hit DB on every request
_god_mode_sessions: Dict[int, bool] = {}
_mcp_god_mode: contextvars.ContextVar[bool] = contextvars.ContextVar("mcp_god_mode", default=False)


def _set_db(user_id: int, active: bool) -> None:
    try:
        from sqlmodel import Session, select
        from app.core.db import sync_engine
        from app.models.user import User
        # NOTE: deliberately synchronous against sync_engine. Cache hit rate is ~100% after
        # warmup; a miss blocks the event loop for one short SQLite/PG round-trip, which we
        # accept to keep these callable from sync, non-event-loop contexts too (Recipe R8).
        with Session(sync_engine) as db:
            user = db.exec(select(User).where(User.id == user_id)).first()
            if user:
                user.god_mode_active = active
                db.add(user)
                db.commit()
    except Exception:
        pass  # DB write failure must not block toggle — in-memory state is still set


def _read_db(user_id: int) -> bool:
    try:
        from sqlmodel import Session, select
        from app.core.db import sync_engine
        from app.models.user import User
        # NOTE: deliberately synchronous against sync_engine. Cache hit rate is ~100% after
        # warmup; a miss blocks the event loop for one short SQLite/PG round-trip, which we
        # accept to keep these callable from sync, non-event-loop contexts too (Recipe R8).
        with Session(sync_engine) as db:
            user = db.exec(select(User).where(User.id == user_id)).first()
            return bool(user.god_mode_active) if user else False
    except Exception:
        return False


def enable_god_mode(user_id: int) -> None:
    _god_mode_sessions[user_id] = True
    _set_db(user_id, True)


def disable_god_mode(user_id: int) -> None:
    _god_mode_sessions[user_id] = False
    _set_db(user_id, False)


def is_god_mode_active(user_id: int) -> bool:
    if user_id in _god_mode_sessions:
        return _god_mode_sessions[user_id]
    # Cache miss (e.g. after hot-reload) — read from DB and re-populate cache
    active = _read_db(user_id)
    _god_mode_sessions[user_id] = active
    return active


def enable_mcp_god_mode() -> None:
    _mcp_god_mode.set(True)


def disable_mcp_god_mode() -> None:
    _mcp_god_mode.set(False)


def is_mcp_god_mode_active() -> bool:
    return _mcp_god_mode.get()
