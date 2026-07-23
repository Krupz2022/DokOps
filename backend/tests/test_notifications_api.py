"""Per-user notification feed API tests.

Uses the shared dual-engine fixtures from conftest.py (isolated_session /
isolated_client) rather than the plain ASGITransport + global AsyncSessionLocal
approach, so seeded rows (written via the sync session) are visible to the
router's overridden async DB session — both point at the same temp-file
SQLite DB.
"""
from sqlmodel import Session

from app.main import app
from app.api import deps
from app.models.notification import Notification


class _U:
    """Minimal stand-in for `User` — only `.id` is used by the router."""

    def __init__(self, uid: int) -> None:
        self.id = uid


def _seed(session: Session, user_id: int, status: str = "watching") -> int:
    n = Notification(
        user_id=user_id,
        conversation_id="c1",
        kind="rollout_watch",
        namespace="ns",
        target="deployment/x",
        status=status,
        message="m",
    )
    session.add(n)
    session.commit()
    session.refresh(n)
    assert n.id is not None
    return n.id


def test_list_is_scoped_to_current_user(isolated_session: Session, isolated_client) -> None:
    mine = _seed(isolated_session, 1)
    theirs = _seed(isolated_session, 2)
    app.dependency_overrides[deps.get_current_user] = lambda: _U(1)
    try:
        r = isolated_client.get("/api/v1/notifications/")
        assert r.status_code == 200
        ids = [n["id"] for n in r.json()]
        assert mine in ids and theirs not in ids
    finally:
        app.dependency_overrides.pop(deps.get_current_user, None)


def test_mark_read(isolated_session: Session, isolated_client) -> None:
    nid = _seed(isolated_session, 1)
    app.dependency_overrides[deps.get_current_user] = lambda: _U(1)
    try:
        r = isolated_client.post(f"/api/v1/notifications/{nid}/read")
        assert r.status_code == 200
        r2 = isolated_client.get("/api/v1/notifications/", params={"unread_only": "true"})
        assert nid not in [n["id"] for n in r2.json()]
    finally:
        app.dependency_overrides.pop(deps.get_current_user, None)
