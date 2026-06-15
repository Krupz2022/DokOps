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
