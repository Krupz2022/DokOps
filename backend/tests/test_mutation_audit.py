import time
import pytest
import json as _json
from sqlmodel import SQLModel, create_engine, Session


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    import app.models.audit  # noqa
    import app.models.user   # noqa
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr("app.core.db.engine", test_engine)
    yield test_engine


@pytest.fixture(autouse=True)
def clean_store():
    yield
    from app.api.v1.operations import pending_operations_store
    pending_operations_store.clear()


def test_derive_resource_scale_deployment():
    from app.api.v1.operations import _derive_resource
    assert _derive_resource("scale_deployment", {"deployment_name": "nginx", "namespace": "default"}) == "deployment/nginx (default)"


def test_derive_resource_delete_namespace():
    from app.api.v1.operations import _derive_resource
    assert _derive_resource("delete_namespace", {"namespace": "prod"}) == "namespace/prod"


def test_derive_resource_patch_secret():
    from app.api.v1.operations import _derive_resource
    assert _derive_resource("patch_secret", {"name": "db-creds", "namespace": "staging"}) == "secret/db-creds (staging)"


def test_derive_resource_apply_manifest():
    from app.api.v1.operations import _derive_resource
    assert _derive_resource("apply_manifest", {"manifest_yaml": "...", "reason": "deploy"}) == "manifest/apply"


def test_derive_resource_unknown_tool():
    from app.api.v1.operations import _derive_resource
    result = _derive_resource("some_unknown_tool", {"foo": "bar"})
    assert result.startswith("some_unknown_tool:")


def test_write_mutation_audit_persists_record(isolated_db):
    from app.api.v1.operations import _write_mutation_audit
    _write_mutation_audit(
        actor="alice",
        tool_name="scale_deployment",
        inputs={"deployment_name": "api", "namespace": "prod", "replicas": 3},
        result="SUCCESS",
        details={"inputs": {"deployment_name": "api"}, "outcome": {"success": True}},
    )
    with Session(isolated_db) as db:
        from sqlmodel import select
        from app.models.audit import AuditLog
        logs = db.exec(select(AuditLog)).all()
        assert len(logs) == 1
        log = logs[0]
        assert log.actor == "alice"
        assert log.action == "scale_deployment"
        assert log.resource == "deployment/api (prod)"
        assert log.result == "SUCCESS"
        assert log.mode == "GOD"
        assert log.source == "K8S"
        assert _json.loads(log.details) == {"inputs": {"deployment_name": "api"}, "outcome": {"success": True}}


def test_approve_writes_success_audit(isolated_db):
    import asyncio
    from unittest.mock import patch
    from app.api.v1.operations import approve_pending_operation, pending_operations_store
    from app.models.user import User

    op_id = "test-approve-001"
    pending_operations_store[op_id] = {
        "id": op_id,
        "session_id": "sess1",
        "tool_name": "scale_deployment",
        "tool_inputs": {"deployment_name": "nginx", "namespace": "default", "replicas": 2},
        "confirmation_message": "Scale nginx",
        "risk_level": "medium",
        "created_at": time.time(),
        "status": "pending",
        "executed_at": None,
        "result": None,
    }
    mock_user = User(id=1, username="bob", hashed_password="x", is_superuser=True, role="admin", is_active=True)

    from unittest.mock import AsyncMock
    with patch("app.api.v1.operations.execute_tool_async", new=AsyncMock(return_value={"success": True, "data": {}})):
        result = asyncio.run(approve_pending_operation(op_id, current_user=mock_user))

    assert result["status"] == "approved"
    with Session(isolated_db) as db:
        from sqlmodel import select
        from app.models.audit import AuditLog
        logs = db.exec(select(AuditLog)).all()
        assert len(logs) == 1
        assert logs[0].result == "SUCCESS"
        assert logs[0].actor == "bob"
        assert logs[0].source == "K8S"


def test_approve_writes_failure_audit(isolated_db):
    import asyncio
    from unittest.mock import patch
    from app.api.v1.operations import approve_pending_operation, pending_operations_store
    from app.models.user import User

    op_id = "test-approve-002"
    pending_operations_store[op_id] = {
        "id": op_id,
        "session_id": "sess1",
        "tool_name": "delete_deployment",
        "tool_inputs": {"deployment_name": "api", "namespace": "prod"},
        "confirmation_message": "Delete api",
        "risk_level": "high",
        "created_at": time.time(),
        "status": "pending",
        "executed_at": None,
        "result": None,
    }
    mock_user = User(id=1, username="carol", hashed_password="x", is_superuser=True, role="admin", is_active=True)

    from unittest.mock import AsyncMock
    with patch("app.api.v1.operations.execute_tool_async", new=AsyncMock(side_effect=RuntimeError("K8s error"))):
        result = asyncio.run(approve_pending_operation(op_id, current_user=mock_user))

    assert result["status"] == "failed"
    with Session(isolated_db) as db:
        from sqlmodel import select
        from app.models.audit import AuditLog
        logs = db.exec(select(AuditLog)).all()
        assert len(logs) == 1
        assert logs[0].result == "FAILURE"


def test_reject_writes_rejected_audit(isolated_db):
    import asyncio
    from app.api.v1.operations import reject_pending_operation, pending_operations_store
    from app.models.user import User

    op_id = "test-reject-001"
    pending_operations_store[op_id] = {
        "id": op_id,
        "session_id": "sess1",
        "tool_name": "delete_namespace",
        "tool_inputs": {"namespace": "prod"},
        "confirmation_message": "Delete prod namespace",
        "risk_level": "high",
        "created_at": time.time(),
        "status": "pending",
        "executed_at": None,
        "result": None,
    }
    mock_user = User(id=1, username="dave", hashed_password="x", is_superuser=True, role="admin", is_active=True)

    result = asyncio.run(reject_pending_operation(op_id, current_user=mock_user))

    assert result["status"] == "rejected"
    with Session(isolated_db) as db:
        from sqlmodel import select
        from app.models.audit import AuditLog
        logs = db.exec(select(AuditLog)).all()
        assert len(logs) == 1
        assert logs[0].result == "REJECTED"
        assert logs[0].actor == "dave"
        assert logs[0].action == "delete_namespace"
        assert logs[0].resource == "namespace/prod"


def test_expiry_on_list_writes_expired_audit(isolated_db):
    import asyncio
    from app.api.v1.operations import list_pending_operations, pending_operations_store
    from app.models.user import User

    op_id = "test-expire-001"
    pending_operations_store[op_id] = {
        "id": op_id,
        "session_id": "sess-expire",
        "tool_name": "cordon_node",
        "tool_inputs": {"node_name": "worker-1"},
        "confirmation_message": "Cordon worker-1",
        "risk_level": "low",
        "created_at": time.time() - 400,  # 400s ago — past the 300s threshold
        "status": "pending",
        "executed_at": None,
        "result": None,
        "audit_written": False,
    }
    mock_user = User(id=1, username="system", hashed_password="x", is_superuser=True, role="admin", is_active=True)

    result = asyncio.run(list_pending_operations(session_id="sess-expire", current_user=mock_user))

    assert any(op["status"] == "expired" for op in result)
    assert pending_operations_store[op_id]["audit_written"] is True
    with Session(isolated_db) as db:
        from sqlmodel import select
        from app.models.audit import AuditLog
        logs = db.exec(select(AuditLog)).all()
        assert len(logs) == 1
        assert logs[0].result == "EXPIRED"
        assert logs[0].action == "cordon_node"


def test_expiry_no_duplicate_audit(isolated_db):
    import asyncio
    from app.api.v1.operations import list_pending_operations, pending_operations_store
    from app.models.user import User

    op_id = "test-expire-002"
    pending_operations_store[op_id] = {
        "id": op_id,
        "session_id": "sess-expire2",
        "tool_name": "cordon_node",
        "tool_inputs": {"node_name": "worker-2"},
        "confirmation_message": "Cordon worker-2",
        "risk_level": "low",
        "created_at": time.time() - 400,
        "status": "pending",
        "executed_at": None,
        "result": None,
        "audit_written": False,
    }
    mock_user = User(id=1, username="system", hashed_password="x", is_superuser=True, role="admin", is_active=True)

    asyncio.run(list_pending_operations(session_id="sess-expire2", current_user=mock_user))
    asyncio.run(list_pending_operations(session_id="sess-expire2", current_user=mock_user))

    with Session(isolated_db) as db:
        from sqlmodel import select
        from app.models.audit import AuditLog
        logs = db.exec(select(AuditLog)).all()
        assert len(logs) == 1  # must NOT be 2
