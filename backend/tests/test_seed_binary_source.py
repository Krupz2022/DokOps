import asyncio, base64
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.blueprint import BlueprintSource  # noqa: F401
from app.models.patch import Organisation  # noqa: F401
from app.core.blueprint_seed import seed_blueprints_from_dir


def _maker(isolated_session):
    url = str(isolated_session.bind.url).replace("sqlite://", "sqlite+aiosqlite://", 1)
    engine = create_async_engine(url, connect_args={"check_same_thread": False})
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def test_seeds_binary_source_as_base64(tmp_path, isolated_session):
    org = Organisation(name="acme", slug="acme"); isolated_session.add(org); isolated_session.commit()
    d = tmp_path / "orgs" / "acme"; (d / "files").mkdir(parents=True)
    (d / "web.yaml").write_text("resources: []")
    raw = bytes(range(256))                              # non-UTF-8 binary
    (d / "files" / "blob.bin").write_bytes(raw)

    async def go():
        async with _maker(isolated_session)() as db:
            await seed_blueprints_from_dir(str(tmp_path), db)

    asyncio.run(go())
    src = isolated_session.exec(select(BlueprintSource).where(BlueprintSource.name == "blob.bin")).first()
    assert src.encoding == "base64"
    assert base64.b64decode(src.content) == raw
