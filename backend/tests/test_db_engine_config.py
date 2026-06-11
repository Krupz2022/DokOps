# backend/tests/test_db_engine_config.py
from app.core.db import _engine_kwargs
from sqlalchemy.pool import StaticPool


def test_postgres_kwargs_enable_pooling_and_pre_ping():
    kw = _engine_kwargs("postgresql://user:pass@host:5432/db")
    assert kw["pool_pre_ping"] is True
    assert kw["pool_size"] >= 5
    assert kw["max_overflow"] >= 0
    assert kw["pool_recycle"] >= 300
    assert "connect_args" not in kw or kw["connect_args"] == {}


def test_sqlite_kwargs_set_check_same_thread_and_pre_ping():
    kw = _engine_kwargs("sqlite:///./dev.db")
    assert kw["connect_args"] == {"check_same_thread": False}
    assert kw["pool_pre_ping"] is True


def test_sqlite_memory_uses_static_pool():
    kw = _engine_kwargs("sqlite:///:memory:")
    assert kw.get("poolclass") is StaticPool
