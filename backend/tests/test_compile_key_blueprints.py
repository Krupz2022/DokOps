import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.blueprint import Blueprint, BlueprintSource  # noqa: F401
from app.models.activation_key import ActivationKey, KeyBlueprint  # noqa: F401
from app.services.blueprint_service import compile_key_blueprints


def _maker(isolated_session):
    url = str(isolated_session.bind.url).replace("sqlite://", "sqlite+aiosqlite://", 1)
    engine = create_async_engine(url, connect_args={"check_same_thread": False})
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def test_compile_merges_key_blueprints_and_sources(isolated_session):
    bp = Blueprint(name="iis", yaml_body="resources:\n  - id: iis-pkg\n    type: pkg\n    name: IIS\n  - id: cfg\n    type: file\n    path: /x\n    source: web.config")
    isolated_session.add(bp); isolated_session.commit(); isolated_session.refresh(bp)
    isolated_session.add(BlueprintSource(blueprint_id=bp.id, name="web.config", content="<config/>"))
    k = ActivationKey(name="win-web", value_hash="H", created_by="a")
    isolated_session.add(k); isolated_session.commit(); isolated_session.refresh(k)
    isolated_session.add(KeyBlueprint(key_id=k.id, blueprint_id=bp.id, position=0))
    isolated_session.commit()

    async def go():
        async with _maker(isolated_session)() as db:
            return await compile_key_blueprints(k.id, db)

    resources, sources = asyncio.run(go())
    assert [r["id"] for r in resources] == ["iis-pkg", "cfg"]
    assert sources == {"web.config": "<config/>"}
