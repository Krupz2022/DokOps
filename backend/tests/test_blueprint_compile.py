# backend/tests/test_blueprint_compile.py
import asyncio
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.blueprint import Blueprint, BlueprintSource, BlueprintAssignment  # noqa: F401
from app.models.minion import Minion  # noqa: F401
from app.models.patch import Organisation, MinionGroup, MinionGroupMember  # noqa: F401
from app.services.blueprint_service import compile_blueprint


@pytest.fixture
def async_session(isolated_session):
    url = str(isolated_session.bind.url).replace("sqlite://", "sqlite+aiosqlite://", 1)
    engine = create_async_engine(url, connect_args={"check_same_thread": False})
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield maker
    asyncio.run(engine.dispose())


def test_compile_merges_org_then_group(isolated_session, async_session):
    org = Organisation(name="acme", slug="acme")
    isolated_session.add(org); isolated_session.commit(); isolated_session.refresh(org)
    grp = MinionGroup(org_id=org.id, name="branch-mumbai")
    isolated_session.add(grp); isolated_session.commit(); isolated_session.refresh(grp)
    m = Minion(id="web-01", hostname="web-01", status="active")
    isolated_session.add(m); isolated_session.commit()
    isolated_session.add(MinionGroupMember(group_id=grp.id, minion_id="web-01"))

    sf_org = Blueprint(name="base", yaml_body="resources:\n  - id: pkg\n    type: pkg\n    name: nginx\n    ensure: present\n  - id: conf\n    type: file\n    path: /x\n    source: nginx.conf")
    sf_grp = Blueprint(name="mumbai", yaml_body="resources:\n  - id: conf\n    type: file\n    path: /x\n    source: nginx.conf\n    mode: '0640'")
    isolated_session.add(sf_org); isolated_session.add(sf_grp); isolated_session.commit()
    isolated_session.refresh(sf_org); isolated_session.refresh(sf_grp)
    isolated_session.add(BlueprintSource(blueprint_id=sf_org.id, name="nginx.conf", content="ORG"))
    isolated_session.add(BlueprintSource(blueprint_id=sf_grp.id, name="nginx.conf", content="MUM"))
    isolated_session.add(BlueprintAssignment(blueprint_id=sf_org.id, scope_type="org", scope_id=org.id))
    isolated_session.add(BlueprintAssignment(blueprint_id=sf_grp.id, scope_type="group", scope_id=grp.id))
    isolated_session.commit()

    async def run():
        async with async_session() as db:
            return await compile_blueprint("web-01", db)

    states, sources = asyncio.run(run())
    assert [s["id"] for s in states] == ["pkg", "conf"]
    assert next(s for s in states if s["id"] == "conf")["mode"] == "0640"  # group won
    assert sources == {"nginx.conf": {"encoding": "utf-8", "content": "MUM"}}  # group source bundled (its file-state survived)


def test_compile_global_is_overridable_base(isolated_session, async_session):
    org = Organisation(name="acme", slug="acme")
    isolated_session.add(org); isolated_session.commit(); isolated_session.refresh(org)
    grp = MinionGroup(org_id=org.id, name="g1")
    isolated_session.add(grp); isolated_session.commit(); isolated_session.refresh(grp)
    m = Minion(id="web-01", hostname="web-01", status="active")
    isolated_session.add(m); isolated_session.commit()
    isolated_session.add(MinionGroupMember(group_id=grp.id, minion_id="web-01"))

    # global: a base resource everyone gets + one the org overrides by id
    sf_glob = Blueprint(name="common", yaml_body="resources:\n  - id: base\n    type: pkg\n    name: curl\n    ensure: present\n  - id: shared\n    type: pkg\n    name: vim\n    ensure: present")
    sf_org = Blueprint(name="acme", yaml_body="resources:\n  - id: shared\n    type: pkg\n    name: vim\n    ensure: absent")
    isolated_session.add(sf_glob); isolated_session.add(sf_org); isolated_session.commit()
    isolated_session.refresh(sf_glob); isolated_session.refresh(sf_org)
    isolated_session.add(BlueprintAssignment(blueprint_id=sf_glob.id, scope_type="global", scope_id="*"))
    isolated_session.add(BlueprintAssignment(blueprint_id=sf_org.id, scope_type="org", scope_id=org.id))
    isolated_session.commit()

    async def run():
        async with async_session() as db:
            return await compile_blueprint("web-01", db)

    states, _ = asyncio.run(run())
    assert [s["id"] for s in states] == ["base", "shared"]  # base from global survives
    assert next(s for s in states if s["id"] == "shared")["ensure"] == "absent"  # org overrode global


def test_compile_unknown_minion_returns_empty(isolated_session, async_session):
    async def run():
        async with async_session() as db:
            return await compile_blueprint("nonexistent-id", db)

    states, sources = asyncio.run(run())
    assert states == []
    assert sources == {}
