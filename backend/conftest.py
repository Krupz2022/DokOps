import sys
import os

# ── Per-worker DB isolation for pytest-xdist ──────────────────────────────────
# This block MUST run before any app.* imports so that app.core.config and
# app.core.db see the per-worker SQLITE_URL when they are first imported
# (which happens lazily, inside fixtures or at collection time).
_xdist_worker = os.environ.get("PYTEST_XDIST_WORKER")
if _xdist_worker:
    # Each xdist worker gets its own on-disk DB so workers never share sql_app.db.
    os.environ["SQLITE_URL"] = f"sqlite:///./test_db_{_xdist_worker}.db"
    os.environ.setdefault("DATABASE_URL", "")  # ensure SQLITE_URL wins

# Ensure the backend directory is on the path so `app` can be imported
sys.path.insert(0, os.path.dirname(__file__))

import pytest


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_worker_db():
    """Initialise the per-worker SQLite DB with all SQLModel tables.

    This runs once per worker process, after app modules can be imported
    (env vars are already set), so module-level helpers like settings_cache
    (which use sync_engine directly) don't hit "no such table" errors.
    Only active when running under pytest-xdist (PYTEST_XDIST_WORKER is set).
    """
    if not os.environ.get("PYTEST_XDIST_WORKER"):
        yield
        return
    try:
        from sqlmodel import SQLModel
        from app.core.db import sync_engine
        SQLModel.metadata.create_all(sync_engine)
    except Exception:
        pass  # best-effort; individual test fixtures will handle their own DDL
    yield


def pytest_sessionfinish(session, exitstatus):
    """Remove per-worker DB files (and WAL/SHM sidecars) after xdist worker finishes."""
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return
    import glob as _glob
    # Search in the backend directory (where conftest.py lives) and cwd.
    _here = os.path.dirname(os.path.abspath(__file__))
    for search_dir in {_here, os.getcwd()}:
        for path in _glob.glob(os.path.join(search_dir, f"test_db_{worker}.db*")):
            try:
                os.unlink(path)
            except OSError:
                pass  # best-effort; ignore locked files on Windows


# ── Shared dual-engine fixtures ───────────────────────────────────────────────
# Many test files repeat the same pattern:
#   1. session_fixture  — sync engine on a fresh temp-file SQLite DB
#   2. client_fixture   — async engine sharing the same file + FastAPI TestClient
#                         with get_db / get_async_db overrides
#
# Provide them here so individual test files can drop their local copies.
# Files with extra monkeypatches (e.g. patching a router's AsyncSessionLocal)
# or non-standard dependency overrides keep their own fixtures.

def _make_isolated_session():
    """Create a fresh temp-file SQLite sync engine and open a Session on it.

    Caller is responsible for teardown.  Returns (engine, session, db_path).
    """
    import asyncio as _asyncio
    import os as _os
    import tempfile as _tempfile
    from sqlmodel import SQLModel, create_engine, Session

    fd, db_path = _tempfile.mkstemp(suffix=".db")
    _os.close(fd)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    return engine, session, db_path


@pytest.fixture(name="isolated_session")
def isolated_session_fixture():
    """Shared session fixture: sync SQLite temp-file DB with all tables created."""
    import os as _os
    engine, session, db_path = _make_isolated_session()
    with session:
        yield session
    engine.dispose()
    try:
        _os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(name="isolated_client")
def isolated_client_fixture(isolated_session):
    """Shared client fixture: TestClient with get_db / get_async_db overrides.

    Uses the same temp-file DB as isolated_session so sync and async paths
    share data.  Does NOT apply any additional monkeypatches — files that need
    extra patches (e.g. patching a router's own AsyncSessionLocal) should keep
    their own client fixture.
    """
    import asyncio as _asyncio
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession

    # Lazy imports so app modules are not pulled in at module-level of conftest.
    from app.main import app as _app
    from app.api import deps as _deps

    db_url = str(isolated_session.bind.url)
    async_url = db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    _async_engine = create_async_engine(async_url, connect_args={"check_same_thread": False})
    _AsyncSessionLocal = async_sessionmaker(_async_engine, class_=AsyncSession, expire_on_commit=False)

    def _get_db_override():
        return isolated_session

    async def _get_async_db_override():
        async with _AsyncSessionLocal() as sess:
            yield sess

    _app.dependency_overrides[_deps.get_db] = _get_db_override
    _app.dependency_overrides[_deps.get_async_db] = _get_async_db_override

    client = TestClient(_app)
    yield client

    _app.dependency_overrides.clear()
    _asyncio.run(_async_engine.dispose())


@pytest.fixture(autouse=True)
def _reset_module_caches():
    """Clear process-wide caches before each test so DB swaps take effect."""
    try:
        from app.core import settings_cache
        settings_cache.invalidate()
    except Exception:
        pass
    try:
        from app.services import integration_manager as _im
        _im.invalidate_registry_cache()
    except Exception:
        pass
    yield
