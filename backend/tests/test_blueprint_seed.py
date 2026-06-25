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
    assert n == (1, 0)   # (seeded, pruned)

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


def test_reseed_prune_removes_deleted_yaml_but_keeps_ui_blueprint(tmp_path, isolated_session):
    # A UI-created (plain-named) blueprint must survive pruning.
    isolated_session.add(Blueprint(name="ui-made", yaml_body="resources: []"))
    isolated_session.commit()

    d = tmp_path / "minions" / "web-01"
    d.mkdir(parents=True)
    (d / "a.yaml").write_text("resources: []")
    (d / "b.yaml").write_text("resources: []")
    maker = _maker(isolated_session)

    async def seed(prune):
        async with maker() as db:
            return await seed_blueprints_from_dir(str(tmp_path), db, prune=prune)

    assert asyncio.run(seed(False)) == (2, 0)

    # Remove one YAML from the folder, then reconcile.
    (d / "b.yaml").unlink()
    seeded, pruned = asyncio.run(seed(True))
    assert seeded == 1 and pruned == 1

    names = {b.name for b in isolated_session.exec(select(Blueprint)).all()}
    assert names == {"ui-made", "minions/web-01/a.yaml"}  # b pruned, ui-made kept
