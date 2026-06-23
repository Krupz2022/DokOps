import logging as _logging

from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from app.core.config import settings
from app.core.security import get_password_hash
from app.models.user import User
from app.models.audit import AuditLog  # noqa: F401
from app.models.setting import SystemSetting
from app.models.chat import ChatConversation, ChatMessage  # noqa: F401
from app.models.rag import RagDocument  # noqa: F401
from app.models.integration import AzureConnection, AzureFeatureConfig, IntegrationSettings  # noqa: F401
from app.models.mcp import MCPServer, MCPTool  # noqa: F401
from app.models.oauth_state import OAuthState  # noqa: F401
from app.models.workflow import Workflow, WorkflowRun  # noqa: F401
from app.models.activation import Activation  # noqa: F401
from app.models.minion import Minion, MinionJob  # noqa: F401
from app.models.activation_key import ActivationKey, KeyBlueprint  # noqa: F401
from app.models.cluster import ClusterConnection, CloudCredential  # noqa: F401
from app.models.patch import (  # noqa: F401 — imported for SQLModel table creation
    Organisation, MinionGroup, MinionGroupMember, MinionPatch,
    PatchPipeline, PipelineStage, PatchPromotion, PatchSchedule,
    PatchAlertEvent,
)
from app.models.service_diag import ServiceCredential, DiscoveredService  # noqa: F401
from app.models.alert_incident import AlertIncident  # noqa: F401
from app.models.registry import RegistryConnection  # noqa: F401
from app.models.analytics import AITokenUsage  # noqa: F401
from app.models.external_knowledge_source import ExternalKnowledgeSource  # noqa: F401

_log = _logging.getLogger(__name__)

_db_url = settings.DATABASE_URL or settings.SQLITE_URL


def _engine_kwargs(url: str) -> dict:
    """Build create_engine kwargs with pool hardening per backend."""
    from sqlalchemy.pool import StaticPool

    if url.startswith("sqlite"):
        kw: dict = {
            "connect_args": {"check_same_thread": False},
            "pool_pre_ping": True,
        }
        if ":memory:" in url:
            # Single shared connection so in-memory DB survives across threads.
            kw["poolclass"] = StaticPool
        return kw
    return {
        "connect_args": {},
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
        "pool_recycle": 1800,
    }


def _to_async_url(url: str) -> str:
    """Rewrite a sync DB URL to its async-driver equivalent."""
    if url.startswith("sqlite+aiosqlite") or "+asyncpg" in url:
        return url
    if url.startswith("sqlite+pysqlite"):
        return url.replace("sqlite+pysqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith("sqlite"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith("postgresql+psycopg2"):
        return url.replace("postgresql+psycopg2", "postgresql+asyncpg", 1)
    if url.startswith("postgresql"):
        return url.replace("postgresql", "postgresql+asyncpg", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _async_engine_kwargs(url: str) -> dict:
    """Async pools: drop check_same_thread (aiosqlite handles threading)."""
    if "sqlite" in url:
        from sqlalchemy.pool import StaticPool
        kw: dict = {"pool_pre_ping": True}
        if ":memory:" in url:
            kw["poolclass"] = StaticPool
        return kw
    return {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20, "pool_recycle": 1800}


# Sync engine retained ONLY for startup DDL/seed + synchronous escape-hatch readers.
sync_engine = create_engine(_db_url, **_engine_kwargs(_db_url))
engine = sync_engine  # back-compat alias; removed in Phase 7

# Async engine — the runtime engine for all event-loop code paths.
_async_db_url = _to_async_url(_db_url)
async_engine = create_async_engine(_async_db_url, **_async_engine_kwargs(_async_db_url))
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


# Enable WAL on SQLite for better concurrent read/write behaviour in dev.
if _db_url.startswith("sqlite"):
    from sqlalchemy import event

    def _set_sqlite_wal(dbapi_conn, _rec):  # pragma: no cover - driver callback
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    event.listens_for(sync_engine, "connect")(_set_sqlite_wal)
    event.listens_for(async_engine.sync_engine, "connect")(_set_sqlite_wal)


async def create_db_and_tables() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def seed_from_env(db: AsyncSession, s) -> None:
    """Seed DB from DOKOPS_* env vars. Insert-if-missing unless DOKOPS_FORCE_SEED=true."""

    # --- Admin user ---
    if s.DOKOPS_ADMIN_USERNAME and s.DOKOPS_ADMIN_PASSWORD:
        user = (await db.exec(select(User).where(User.username == s.DOKOPS_ADMIN_USERNAME))).first()
        if not user:
            db.add(User(
                username=s.DOKOPS_ADMIN_USERNAME,
                hashed_password=get_password_hash(s.DOKOPS_ADMIN_PASSWORD),
                is_superuser=True,
                role="admin",
                is_active=True,
            ))
        elif s.DOKOPS_FORCE_SEED:
            user.hashed_password = get_password_hash(s.DOKOPS_ADMIN_PASSWORD)
            db.add(user)

    # --- SystemSetting keys ---
    # Bool values stored as "true"/"false" to match the rest of the app.
    # Int/str values stored as str(value).
    seed_map = {
        "ai_provider": s.DOKOPS_AI_PROVIDER,
        "ai_api_key": s.DOKOPS_AI_API_KEY,
        "ai_model": s.DOKOPS_AI_MODEL,
        "ai_base_url": s.DOKOPS_AI_BASE_URL,
        "ai_api_version": s.DOKOPS_AI_API_VERSION,
        "rag_enabled": None if s.DOKOPS_RAG_ENABLED is None else ("true" if s.DOKOPS_RAG_ENABLED else "false"),
        "rag_chroma_host": s.DOKOPS_RAG_CHROMA_HOST,
        "rag_chroma_port": s.DOKOPS_RAG_CHROMA_PORT,
        "signup_enabled": None if s.DOKOPS_SIGNUP_ENABLED is None else ("true" if s.DOKOPS_SIGNUP_ENABLED else "false"),
        "signup_default_role": s.DOKOPS_SIGNUP_DEFAULT_ROLE,
        "rag_embedding_provider": s.DOKOPS_RAG_EMBEDDING_PROVIDER,
        "rag_embedding_api_key": s.DOKOPS_RAG_EMBEDDING_API_KEY,
        "rag_embedding_model": s.DOKOPS_RAG_EMBEDDING_MODEL,
        "rag_embedding_base_url": s.DOKOPS_RAG_EMBEDDING_BASE_URL,
    }

    for key, value in seed_map.items():
        if not value:
            continue
        row = (await db.exec(select(SystemSetting).where(SystemSetting.key == key))).first()
        if not row:
            db.add(SystemSetting(key=key, value=value))
        elif s.DOKOPS_FORCE_SEED:
            row.value = value
            db.add(row)

    await db.commit()

    # --- Observability integrations ---
    await _seed_obs_integrations(db, s)


async def _seed_obs_integrations(db: AsyncSession, s) -> None:
    """Seed observability integrations from DOKOPS_ES_* env vars."""
    if not s.DOKOPS_ES_URL or not s.DOKOPS_ES_AUTH_TYPE:
        return

    from app.models.integration import IntegrationSettings
    from app.services.integrations.base import encrypt_credentials

    auth_type = s.DOKOPS_ES_AUTH_TYPE.lower()
    if auth_type == "api_key" and s.DOKOPS_ES_API_KEY:
        creds = {"api_key": s.DOKOPS_ES_API_KEY, "header_name": s.DOKOPS_ES_HEADER_NAME or "Authorization"}
    elif auth_type == "basic" and s.DOKOPS_ES_USERNAME and s.DOKOPS_ES_PASSWORD:
        creds = {"username": s.DOKOPS_ES_USERNAME, "password": s.DOKOPS_ES_PASSWORD}
    elif auth_type == "bearer" and s.DOKOPS_ES_API_KEY:
        creds = {"token": s.DOKOPS_ES_API_KEY}
    else:
        creds = None

    encrypted = encrypt_credentials(creds) if creds else None

    existing = (await db.exec(
        select(IntegrationSettings).where(IntegrationSettings.backend == "elasticsearch")
    )).first()

    if existing and not s.DOKOPS_FORCE_SEED:
        return  # already configured, don't overwrite

    if existing:
        existing.base_url = s.DOKOPS_ES_URL
        existing.auth_type = auth_type
        existing.encrypted_credentials = encrypted
        existing.is_active = True
        existing.display_name = "Elasticsearch"
        db.add(existing)
    else:
        db.add(IntegrationSettings(
            backend="elasticsearch",
            display_name="Elasticsearch",
            base_url=s.DOKOPS_ES_URL,
            auth_type=auth_type,
            encrypted_credentials=encrypted,
            is_active=True,
        ))
    await db.commit()
    _log.info("seed: elasticsearch integration seeded from env vars (url=%s)", s.DOKOPS_ES_URL)


async def _migrate_schema() -> None:
    """Add new columns to existing tables without dropping data (PostgreSQL + SQLite safe)."""
    from sqlalchemy import text

    is_postgres = not _db_url.startswith("sqlite")

    def _col(table: str, col: str, typedef: str) -> str:
        if is_postgres:
            return f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typedef}"
        return f"ALTER TABLE {table} ADD COLUMN {col} {typedef}"

    migrations = [
        _col("clusterconnection", "client_cert_data", "TEXT"),
        _col("clusterconnection", "client_key_data", "TEXT"),
        _col("workflows", "workflow_type", "TEXT DEFAULT 'scripted'"),
        _col("workflows", "agent_goal", "TEXT"),
        _col("workflows", "agent_approved_tools", "TEXT DEFAULT '[]'"),
        _col("workflows", "agent_cluster_ids", "TEXT DEFAULT '[]'"),
        _col("workflows", "agent_minion_ids", "TEXT DEFAULT '[]'"),
        _col("workflows", "agent_max_retries", "INTEGER DEFAULT 3"),
        _col("workflows", "agent_timeout_seconds", "INTEGER DEFAULT 900"),
        _col("workflows", "agent_approval_timeout_seconds", "INTEGER DEFAULT 600"),
        _col("workflows", "trigger_config", "TEXT"),
        _col("patchschedule", "auto_reboot", "INTEGER DEFAULT 0"),
        _col("patchschedule", "week_of_month", "INTEGER"),
        _col("servicecredential", "host", "TEXT"),
        _col("servicecredential", "instance_name", "TEXT DEFAULT ''"),
        _col("user", "god_mode_active", "INTEGER DEFAULT 0"),
    ]

    # All timestamp columns are timezone-aware UTC (see app.core.datetimes).
    # On PostgreSQL, convert any pre-existing naive `TIMESTAMP WITHOUT TIME ZONE`
    # columns to `timestamptz`, interpreting stored values as UTC. Idempotent:
    # re-running on an already-converted column is a no-op. SQLite has no real
    # timestamptz type and stores ISO strings, so this is skipped there.
    if is_postgres:
        tz_columns: dict[str, list[str]] = {
            "workflows": ["created_at", "updated_at"],
            "workflow_runs": ["started_at", "completed_at"],
            "servicecredential": ["created_at", "updated_at"],
            "discoveredservice": ["detected_at"],
            "registryconnection": ["created_at"],
            "external_knowledge_sources": ["created_at"],
            "ragdocument": ["indexed_at"],
            "organisation": ["created_at"],
            "miniongroup": ["created_at"],
            "minionpatch": ["scanned_at"],
            "patchpipeline": ["created_at"],
            "patchpromotion": ["triggered_at", "completed_at"],
            "patchschedule": ["next_run_at"],
            "patchalertevent": ["fired_at", "acknowledged_at"],
            "patchpromotionresult": ["created_at"],
            "clusterconnection": ["created_at", "last_verified"],
            "cloudcredential": ["created_at"],
            "oauthstate": ["created_at"],
            "chatconversation": ["created_at", "updated_at"],
            "chatmessage": ["created_at"],
            "minion": ["last_seen", "last_patch_scan", "created_at"],
            "minionjob": ["created_at", "completed_at"],
            "alert_incidents": ["notification_sent_at", "created_at", "resolved_at"],
            "activation": ["activated_at", "last_heartbeat_at"],
            "ai_token_usage": ["created_at"],
            "mcpserver": ["last_connected_at", "created_at"],
            "mcptool": ["last_synced_at"],
            "auditlog": ["timestamp"],
            "azureconnection": ["connected_at"],
            "azurefeatureconfig": ["last_synced_at"],
            "integrationsettings": ["connected_at", "last_checked_at"],
        }
        for table, cols in tz_columns.items():
            for col in cols:
                migrations.append(
                    f"ALTER TABLE {table} ALTER COLUMN {col} "
                    f"TYPE TIMESTAMP WITH TIME ZONE USING {col} AT TIME ZONE 'UTC'"
                )

    async with async_engine.connect() as conn:
        for stmt in migrations:
            try:
                await conn.execute(text(stmt))
                await conn.commit()
            except Exception:
                await conn.rollback()  # PostgreSQL: reset aborted transaction before next statement


async def init_db() -> None:
    await create_db_and_tables()
    await _migrate_schema()
    async with AsyncSessionLocal() as db:
        try:
            await seed_from_env(db, settings)
        except Exception:
            _log.critical("seed_from_env failed during startup — check DOKOPS_* env vars", exc_info=True)
            raise
