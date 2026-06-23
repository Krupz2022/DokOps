import asyncio
from unittest.mock import AsyncMock, patch
from sqlmodel import select

from app.models.minion import Minion
from app.models.activation_key import ActivationKey, KeyBlueprint
from app.models.blueprint import Blueprint
from app.models.patch import Organisation, MinionGroup, MinionGroupMember
from app.models.audit import AuditLog  # noqa: F401
from app.services.minion_service import hash_token


def _async_maker(isolated_session):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession
    url = str(isolated_session.bind.url).replace("sqlite://", "sqlite+aiosqlite://", 1)
    engine = create_async_engine(url, connect_args={"check_same_thread": False})
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _seed(isolated_session, run_on_attach=True, enabled=True):
    org = Organisation(name="acme", slug="acme"); isolated_session.add(org); isolated_session.commit(); isolated_session.refresh(org)
    grp = MinionGroup(org_id=org.id, name="web"); isolated_session.add(grp); isolated_session.commit(); isolated_session.refresh(grp)
    bp = Blueprint(name="iis", yaml_body="resources:\n  - id: a\n    type: cmd\n    name: echo hi")
    isolated_session.add(bp); isolated_session.commit(); isolated_session.refresh(bp)
    isolated_session.add(Minion(id="m1", hostname="m1", status="active"))
    key = ActivationKey(name="win-web", value_hash=hash_token("SECRET"), group_id=grp.id,
                        run_on_attach=run_on_attach, enabled=enabled, created_by="a")
    isolated_session.add(key); isolated_session.commit(); isolated_session.refresh(key)
    isolated_session.add(KeyBlueprint(key_id=key.id, blueprint_id=bp.id, position=0))
    isolated_session.commit()
    return grp.id


def test_matching_key_places_and_bootstraps_once(isolated_session, monkeypatch):
    from app.services import minion_service as ms
    monkeypatch.setattr(ms, "AsyncSessionLocal", _async_maker(isolated_session))
    grp_id = _seed(isolated_session)
    dispatch = AsyncMock()
    monkeypatch.setattr(ms.manager, "dispatch_blueprint", dispatch)

    asyncio.run(ms.apply_enrollment_key("m1", "SECRET"))

    # placed in the key's group
    assert isolated_session.get(MinionGroupMember, ("%s" % grp_id, "m1")) is not None
    # bootstrapped once
    dispatch.assert_awaited_once()
    assert isolated_session.get(Minion, "m1").bootstrapped is True
    assert isolated_session.exec(select(AuditLog).where(AuditLog.action == "bootstrap_blueprint")).first() is not None

    # second enroll → no re-bootstrap
    dispatch.reset_mock()
    asyncio.run(ms.apply_enrollment_key("m1", "SECRET"))
    dispatch.assert_not_awaited()


def test_disabled_key_does_nothing(isolated_session, monkeypatch):
    from app.services import minion_service as ms
    monkeypatch.setattr(ms, "AsyncSessionLocal", _async_maker(isolated_session))
    _seed(isolated_session, enabled=False)
    dispatch = AsyncMock(); monkeypatch.setattr(ms.manager, "dispatch_blueprint", dispatch)
    asyncio.run(ms.apply_enrollment_key("m1", "SECRET"))
    dispatch.assert_not_awaited()
    assert isolated_session.get(Minion, "m1").bootstrapped is False


def test_unknown_key_value_noop(isolated_session, monkeypatch):
    from app.services import minion_service as ms
    monkeypatch.setattr(ms, "AsyncSessionLocal", _async_maker(isolated_session))
    _seed(isolated_session)
    dispatch = AsyncMock(); monkeypatch.setattr(ms.manager, "dispatch_blueprint", dispatch)
    asyncio.run(ms.apply_enrollment_key("m1", "WRONG"))
    dispatch.assert_not_awaited()
