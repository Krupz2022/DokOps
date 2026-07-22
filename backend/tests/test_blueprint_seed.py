import asyncio
import builtins
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.blueprint import Blueprint, BlueprintAssignment, BlueprintSource  # noqa: F401
from app.models.patch import Organisation  # noqa: F401
from app.core.blueprint_seed import backfill_disk_sources, seed_blueprints_from_dir


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
    # Seeded sources are disk-backed: the row references the file, bytes stay on disk.
    assert src.name == "nginx.conf"
    assert src.origin == "disk"
    assert src.rel_path == "orgs/acme/files/nginx.conf"
    assert src.size == len("server {}")
    assert src.content == ""


def test_seed_common_scope(tmp_path, isolated_session):
    d = tmp_path / "common"
    (d / "files").mkdir(parents=True)
    (d / "baseline.yaml").write_text("resources:\n  - id: pkg\n    type: pkg\n    name: curl")
    (d / "files" / "motd").write_text("hello")

    maker = _maker(isolated_session)

    async def go():
        async with maker() as db:
            return await seed_blueprints_from_dir(str(tmp_path), db)

    assert asyncio.run(go()) == (1, 0)
    sf = isolated_session.exec(select(Blueprint)).first()
    assert sf.name == "common/baseline.yaml"
    asn = isolated_session.exec(select(BlueprintAssignment)).first()
    assert asn.scope_type == "global" and asn.scope_id == "*"
    src = isolated_session.exec(select(BlueprintSource)).first()
    assert src.name == "motd"
    assert src.origin == "disk"
    assert src.rel_path == "common/files/motd"
    assert src.size == len("hello")


def test_seed_never_reads_artifacts(tmp_path, isolated_session, monkeypatch):
    """The whole point of disk-backing: a 5.8GB folder must cost stat(), not reads.

    Blueprint YAML is still read; anything under a files/ dir must not be opened.
    """
    d = tmp_path / "common"
    (d / "files").mkdir(parents=True)
    (d / "baseline.yaml").write_text("resources: []")
    (d / "files" / "big.bin").write_bytes(b"\x00\x01\xff\xfe binary \x80")

    real_open = builtins.open
    opened: list[str] = []

    def spy(file, *a, **kw):
        opened.append(str(file))
        return real_open(file, *a, **kw)

    monkeypatch.setattr(builtins, "open", spy)

    maker = _maker(isolated_session)

    async def go():
        async with maker() as db:
            return await seed_blueprints_from_dir(str(tmp_path), db)

    assert asyncio.run(go()) == (1, 0)
    assert not [p for p in opened if "files" in p.replace("\\", "/").split("/")], \
        f"artifacts were read during seed: {opened}"

    src = isolated_session.exec(select(BlueprintSource)).first()
    assert src.origin == "disk"
    assert src.size == len(b"\x00\x01\xff\xfe binary \x80")
    assert src.content == ""


def test_reseed_clears_cached_hash_when_file_changes(tmp_path, isolated_session):
    d = tmp_path / "common"
    (d / "files").mkdir(parents=True)
    (d / "baseline.yaml").write_text("resources: []")
    artifact = d / "files" / "app.bin"
    artifact.write_bytes(b"v1")

    maker = _maker(isolated_session)

    async def seed():
        async with maker() as db:
            return await seed_blueprints_from_dir(str(tmp_path), db)

    asyncio.run(seed())

    # Pretend a dispatch has already hashed it.
    src = isolated_session.exec(select(BlueprintSource)).first()
    src.sha256 = "cached"
    isolated_session.add(src); isolated_session.commit()

    # Unchanged file keeps the cached hash.
    asyncio.run(seed())
    isolated_session.expire_all()
    assert isolated_session.exec(select(BlueprintSource)).first().sha256 == "cached"

    # Changed file invalidates it.
    artifact.write_bytes(b"v2-longer")
    asyncio.run(seed())
    isolated_session.expire_all()
    assert isolated_session.exec(select(BlueprintSource)).first().sha256 is None


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


def test_reseed_prunes_source_moved_to_another_path(tmp_path, isolated_session):
    """Moving an artifact must not leave the old path behind in the UI.

    The old row also points at a rel_path that no longer exists, so it would 404
    on fetch rather than serve anything.
    """
    d = tmp_path / "common"
    (d / "files" / "test" / "tmp").mkdir(parents=True)
    (d / "baseline.yaml").write_text("resources: []")
    old = d / "files" / "test" / "tmp" / "dokops.pem"
    old.write_text("CERT")

    maker = _maker(isolated_session)

    async def seed(prune):
        async with maker() as db:
            return await seed_blueprints_from_dir(str(tmp_path), db, prune=prune)

    asyncio.run(seed(False))
    isolated_session.expire_all()
    assert {s.name for s in isolated_session.exec(select(BlueprintSource)).all()} == {
        "test/tmp/dokops.pem"
    }

    # Move it to a different path under the same parent.
    new = d / "files" / "test" / "certs"
    new.mkdir(parents=True)
    old.rename(new / "dokops.pem")

    seeded, pruned = asyncio.run(seed(True))
    isolated_session.expire_all()
    names = {s.name for s in isolated_session.exec(select(BlueprintSource)).all()}
    assert names == {"test/certs/dokops.pem"}, f"stale row left behind: {names}"
    assert pruned == 1


def test_reseed_never_prunes_ui_created_sources(tmp_path, isolated_session):
    """A folder walk must not delete sources that were uploaded through the UI."""
    d = tmp_path / "common"
    d.mkdir(parents=True)
    (d / "baseline.yaml").write_text("resources: []")

    maker = _maker(isolated_session)

    async def seed(prune):
        async with maker() as db:
            return await seed_blueprints_from_dir(str(tmp_path), db, prune=prune)

    asyncio.run(seed(False))
    bp = isolated_session.exec(select(Blueprint)).first()
    isolated_session.add(BlueprintSource(
        blueprint_id=bp.id, name="uploaded.conf", origin="inline", content="x",
    ))
    isolated_session.commit()

    asyncio.run(seed(True))
    isolated_session.expire_all()
    rows = isolated_session.exec(select(BlueprintSource)).all()
    assert [r.name for r in rows] == ["uploaded.conf"]
    assert rows[0].content == "x"


def test_backfill_converts_legacy_row_with_backing_file(tmp_path, isolated_session):
    d = tmp_path / "common"
    (d / "files").mkdir(parents=True)
    (d / "baseline.yaml").write_text("resources: []")
    (d / "files" / "motd").write_text("hello")

    bp = Blueprint(name="common/baseline.yaml", yaml_body="resources: []")
    isolated_session.add(bp); isolated_session.commit()
    isolated_session.add(BlueprintSource(
        blueprint_id=bp.id, name="motd", origin="inline",
        content="aGVsbG8=", encoding="base64",
    ))
    isolated_session.commit()

    maker = _maker(isolated_session)

    async def go():
        async with maker() as db:
            return await backfill_disk_sources(str(tmp_path), db)

    assert asyncio.run(go()) == 1
    isolated_session.expire_all()
    src = isolated_session.exec(select(BlueprintSource)).first()
    assert src.origin == "disk"
    assert src.rel_path == "common/files/motd"
    assert src.size == len("hello")
    assert src.content == ""   # blob reclaimed


def test_backfill_leaves_rows_without_backing_file_alone(tmp_path, isolated_session):
    """Running with the blueprints folder unmounted must not destroy inline bytes."""
    (tmp_path / "common").mkdir(parents=True)

    bp = Blueprint(name="common/baseline.yaml", yaml_body="resources: []")
    isolated_session.add(bp); isolated_session.commit()
    isolated_session.add(BlueprintSource(
        blueprint_id=bp.id, name="motd", origin="inline",
        content="aGVsbG8=", encoding="base64",
    ))
    isolated_session.commit()

    maker = _maker(isolated_session)

    async def go():
        async with maker() as db:
            return await backfill_disk_sources(str(tmp_path), db)

    assert asyncio.run(go()) == 0
    isolated_session.expire_all()
    src = isolated_session.exec(select(BlueprintSource)).first()
    assert src.origin == "inline" and src.content == "aGVsbG8="


def test_backfill_ignores_ui_created_blueprints(tmp_path, isolated_session):
    bp = Blueprint(name="ui-made", yaml_body="resources: []")
    isolated_session.add(bp); isolated_session.commit()
    isolated_session.add(BlueprintSource(
        blueprint_id=bp.id, name="motd", origin="inline", content="hi", encoding="utf-8",
    ))
    isolated_session.commit()

    maker = _maker(isolated_session)

    async def go():
        async with maker() as db:
            return await backfill_disk_sources(str(tmp_path), db)

    assert asyncio.run(go()) == 0
    isolated_session.expire_all()
    assert isolated_session.exec(select(BlueprintSource)).first().content == "hi"


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
