import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.blueprint import Blueprint, BlueprintAssignment, BlueprintSource  # noqa: F401
from app.models.patch import Organisation  # noqa: F401
from app.core.blueprint_seed import seed_blueprints_from_dir


def _maker(isolated_session):
    url = str(isolated_session.bind.url).replace("sqlite://", "sqlite+aiosqlite://", 1)
    engine = create_async_engine(url, connect_args={"check_same_thread": False})
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def test_seed_org_scope(tmp_path, isolated_session):
    org = Organisation(name="acme", slug="acme")
    isolated_session.add(org); isolated_session.commit()

    d = tmp_path / "orgs" / "acme"
    (d / "files").mkdir(parents=True)
    (d / "web.yaml").write_text("resources:\n  - id: pkg\n    type: pkg\n    name: nginx")
    (d / "files" / "nginx.conf").write_text("server {}")

    maker = _maker(isolated_session)

    async def go():
        async with maker() as db:
            return await seed_blueprints_from_dir(str(tmp_path), db)

    n = asyncio.run(go())
    assert n == 1

    sf = isolated_session.exec(select(Blueprint)).first()
    assert sf is not None
    asn = isolated_session.exec(select(BlueprintAssignment)).first()
    assert asn.scope_type == "org" and asn.scope_id == org.id
    src = isolated_session.exec(select(BlueprintSource)).first()
    assert src.name == "nginx.conf" and src.content == "server {}"


def test_seed_is_idempotent(tmp_path, isolated_session):
    d = tmp_path / "minions" / "web-01"
    d.mkdir(parents=True)
    (d / "tweaks.yaml").write_text("resources: []")
    maker = _maker(isolated_session)

    async def go():
        async with maker() as db:
            await seed_blueprints_from_dir(str(tmp_path), db)
        async with maker() as db:
            await seed_blueprints_from_dir(str(tmp_path), db)

    asyncio.run(go())
    files = isolated_session.exec(select(Blueprint)).all()
    assert len(files) == 1  # upsert, not duplicate
