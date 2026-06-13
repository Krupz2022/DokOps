import pytest
from sqlmodel import Session, create_engine, SQLModel, select
from app.models.service_diag import ServiceCredential  # noqa: F401 — registers table
from app.models.minion import Minion, MinionJob  # noqa: F401 — FK dependency


@pytest.fixture(name="engine")
def engine_fixture():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


def test_service_credential_has_host_field(engine):
    with Session(engine) as db:
        cred = ServiceCredential(
            scope_type="cluster",
            scope_id="cluster-abc",
            service_type="rabbitmq",
            username="",
            password="",
            host="rabbitmq.infra.svc",
        )
        db.add(cred)
        db.commit()
        db.refresh(cred)
        assert cred.host == "rabbitmq.infra.svc"
        assert cred.scope_type == "cluster"


from app.services.service_credential_service import create_credential, resolve_cluster_credential
from app.core.encryption import encrypt


def test_create_credential_with_host(engine):
    with Session(engine) as db:
        cred = create_credential(
            db,
            scope_type="cluster",
            scope_id="cluster-abc",
            service_type="rabbitmq",
            username="admin",
            password="secret",
            host="rabbitmq.infra.svc",
            port=5672,
            extra='{"vhost": "/prod"}',
        )
        assert cred.id is not None
        assert cred.host == "rabbitmq.infra.svc"


def test_resolve_cluster_credential_returns_decrypted(engine):
    import asyncio, os, tempfile
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession as _AsyncSession

    # Seed via sync engine
    with Session(engine) as db:
        create_credential(
            db,
            scope_type="cluster",
            scope_id="cluster-xyz",
            service_type="redis",
            username="",
            password="r3dis_pass",
            host="redis.infra.svc",
            port=6379,
        )

    # Use a shared temp-file DB for async round-trip
    _fd, _db_path = tempfile.mkstemp(suffix=".db")
    os.close(_fd)
    try:
        from sqlmodel import create_engine as _ce
        _se = _ce(f"sqlite:///{_db_path}", connect_args={"check_same_thread": False})
        import sqlmodel as _sm
        _sm.SQLModel.metadata.create_all(_se)
        with Session(_se) as db2:
            create_credential(db2, scope_type="cluster", scope_id="cluster-xyz",
                              service_type="redis", username="", password="r3dis_pass",
                              host="redis.infra.svc", port=6379)
        _se.dispose()

        _aeng = create_async_engine(f"sqlite+aiosqlite:///{_db_path}")
        _ASL = async_sessionmaker(_aeng, class_=_AsyncSession, expire_on_commit=False)

        async def _run():
            async with _ASL() as adb:
                return await resolve_cluster_credential("cluster-xyz", "redis", adb)

        result = asyncio.run(_run())
        asyncio.run(_aeng.dispose())
    finally:
        try:
            os.unlink(_db_path)
        except OSError:
            pass

    assert result is not None
    assert result["password"] == "r3dis_pass"
    assert result["host"] == "redis.infra.svc"
    assert result["port"] == 6379


def test_resolve_cluster_credential_returns_none_when_missing(engine):
    import asyncio, os, tempfile
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession as _AsyncSession

    _fd, _db_path = tempfile.mkstemp(suffix=".db")
    os.close(_fd)
    try:
        from sqlmodel import create_engine as _ce
        _se = _ce(f"sqlite:///{_db_path}", connect_args={"check_same_thread": False})
        import sqlmodel as _sm
        _sm.SQLModel.metadata.create_all(_se)
        _se.dispose()

        _aeng = create_async_engine(f"sqlite+aiosqlite:///{_db_path}")
        _ASL = async_sessionmaker(_aeng, class_=_AsyncSession, expire_on_commit=False)

        async def _run():
            async with _ASL() as adb:
                return await resolve_cluster_credential("nonexistent-cluster", "rabbitmq", adb)

        result = asyncio.run(_run())
        asyncio.run(_aeng.dispose())
    finally:
        try:
            os.unlink(_db_path)
        except OSError:
            pass

    assert result is None


def test_service_credentials_api_schema_accepts_cluster_scope():
    from app.api.v1.service_credentials import CredentialCreate
    body = CredentialCreate(
        scope_type="cluster",
        scope_id="cluster-abc",
        service_type="rabbitmq",
        username="admin",
        password="secret",
        host="rabbitmq.infra.svc",
        port=5672,
        extra='{"vhost": "/"}',
    )
    assert body.scope_type == "cluster"
    assert body.host == "rabbitmq.infra.svc"


from app.services.vault_resolver import VaultResolver, VaultCredentialNotFound, VaultFieldNotFound


def test_vault_resolver_substitutes_username(engine):
    with Session(engine) as db:
        create_credential(
            db, scope_type="cluster", scope_id="c1",
            service_type="rabbitmq", username="admin", password="s3cr3t",
            host="rabbit.svc", port=5672, extra='{"vhost": "/prod"}',
        )
        resolver = VaultResolver()
        result = resolver.resolve(
            "curl -u $VAULT:rabbitmq:username:$VAULT:rabbitmq:password http://$VAULT:rabbitmq:host:15672/api/queues",
            cluster_id="c1",
            db=db,
        )
        assert "admin" in result
        assert "s3cr3t" in result
        assert "rabbit.svc" in result
        assert "$VAULT:" not in result


def test_vault_resolver_substitutes_extra_field(engine):
    with Session(engine) as db:
        create_credential(
            db, scope_type="cluster", scope_id="c2",
            service_type="rabbitmq", username="u", password="p",
            host="h", extra='{"vhost": "/myvhost"}',
        )
        resolver = VaultResolver()
        result = resolver.resolve("vhost=$VAULT:rabbitmq:extra.vhost", cluster_id="c2", db=db)
        assert "vhost=/myvhost" in result


def test_vault_resolver_raises_when_no_credential(engine):
    with Session(engine) as db:
        resolver = VaultResolver()
        with pytest.raises(VaultCredentialNotFound) as exc:
            resolver.resolve("$VAULT:redis:password", cluster_id="no-such-cluster", db=db)
        assert "redis" in str(exc.value)


def test_vault_resolver_raises_for_unknown_field(engine):
    with Session(engine) as db:
        create_credential(
            db, scope_type="cluster", scope_id="c3",
            service_type="redis", username="", password="pass", host="redis.svc",
        )
        resolver = VaultResolver()
        with pytest.raises(VaultFieldNotFound):
            resolver.resolve("$VAULT:redis:extra.nonexistent_key", cluster_id="c3", db=db)


def test_vault_resolver_noop_when_no_tokens(engine):
    with Session(engine) as db:
        resolver = VaultResolver()
        cmd = "kubectl get pods -n default"
        assert resolver.resolve(cmd, cluster_id="any", db=db) == cmd


# ─── Task 6: Vault Coverage API ───────────────────────────────────────────────

def test_vault_coverage_groups_by_cluster():
    import asyncio
    import os
    import tempfile
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession
    from app.models.cluster import ClusterConnection

    # Use a temp file so sync setup and async query share the same DB.
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    sync_eng = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(sync_eng)

    cluster_id: str
    with Session(sync_eng) as db:
        cluster = ClusterConnection(
            name="test-cluster",
            provider="generic",
            api_server="https://k8s.test",
            token="",
            namespace="default",
            added_by="test",
        )
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        cluster_id = cluster.id

        create_credential(db, scope_type="cluster", scope_id=cluster_id,
                          service_type="rabbitmq", username="u", password="p", host="h")
        create_credential(db, scope_type="cluster", scope_id=cluster_id,
                          service_type="redis", username="", password="p", host="h")

    sync_eng.dispose()

    async def _run():
        async_eng = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        _AsyncSL = async_sessionmaker(async_eng, class_=AsyncSession, expire_on_commit=False)
        try:
            from app.api.v1.vault import get_vault_coverage
            async with _AsyncSL() as async_db:
                return await get_vault_coverage(db=async_db)
        finally:
            await async_eng.dispose()

    result = asyncio.run(_run())

    entry = next((r for r in result if r["cluster_id"] == cluster_id), None)
    assert entry is not None
    assert "rabbitmq" in entry["configured"]
    assert "redis" in entry["configured"]
    assert entry["total_services"] == 6

    try:
        os.unlink(db_path)
    except OSError:
        pass


# ─── Task 7: ToolsetService Builtin Directory ────────────────────────────────

import os, tempfile, yaml as _yaml

def test_toolset_service_lists_builtin_toolsets():
    from app.services.toolset_service import ToolsetService

    with tempfile.TemporaryDirectory() as user_dir:
        builtin_dir = os.path.join(user_dir, "builtin")
        os.makedirs(builtin_dir)

        content = {
            "testtools": {
                "description": "Test builtin",
                "tools": [{"name": "test_tool", "description": "does stuff", "command": "echo hi"}],
            }
        }
        with open(os.path.join(builtin_dir, "testtools.yaml"), "w") as f:
            _yaml.dump(content, f)

        svc = ToolsetService(toolsets_dir=user_dir, builtin_dir=builtin_dir)
        builtins = svc.list_builtin_toolsets()
        assert len(builtins) == 1
        assert builtins[0]["id"] == "testtools"
        assert builtins[0]["builtin"] is True


# ─── Task 12: Cluster Deletion Cleanup ─────────────────────────────────────────

def test_cluster_deletion_removes_credentials():
    """_delete_cluster_credentials (now async) removes all cluster-scoped creds."""
    import asyncio
    import os
    import tempfile
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlmodel import create_engine as _create_engine
    from sqlmodel.ext.asyncio.session import AsyncSession as _AsyncSession
    from app.models.cluster import ClusterConnection
    from app.models.service_diag import ServiceCredential
    from app.api.v1.clusters import _delete_cluster_credentials

    # Use a temp-file so both sync and async engines share the same DB.
    _fd, _db_path = tempfile.mkstemp(suffix=".db")
    os.close(_fd)
    try:
        _sync_engine = _create_engine(
            f"sqlite:///{_db_path}", connect_args={"check_same_thread": False}
        )
        SQLModel.metadata.create_all(_sync_engine)

        # Seed via sync session
        with Session(_sync_engine) as db:
            cluster = ClusterConnection(
                name="delete-me",
                provider="generic",
                api_server="https://k8s.test",
                token="",
                namespace="default",
                added_by="test",
            )
            db.add(cluster)
            db.commit()
            db.refresh(cluster)
            cluster_id = cluster.id

            create_credential(db, scope_type="cluster", scope_id=cluster_id,
                              service_type="redis", username="", password="p", host="h")

        # Call the async helper
        _async_url = f"sqlite+aiosqlite:///{_db_path}"
        _aengine = create_async_engine(_async_url)
        _ASessionLocal = async_sessionmaker(_aengine, class_=_AsyncSession, expire_on_commit=False)

        async def _run():
            async with _ASessionLocal() as adb:
                await _delete_cluster_credentials(cluster_id, adb)
                await adb.commit()  # helper stages deletes; the caller owns the commit

        asyncio.run(_run())
        asyncio.run(_aengine.dispose())

        # Verify via sync session
        with Session(_sync_engine) as db:
            remaining = db.exec(
                select(ServiceCredential).where(
                    ServiceCredential.scope_type == "cluster",
                    ServiceCredential.scope_id == cluster_id,
                )
            ).all()
        _sync_engine.dispose()
        assert len(remaining) == 0
    finally:
        try:
            os.unlink(_db_path)
        except OSError:
            pass
