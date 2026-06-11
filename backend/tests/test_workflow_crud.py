import os
import tempfile
import pytest
from sqlmodel import Session, create_engine, SQLModel
from app.models.workflow import Workflow, WorkflowRun

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

def test_workflow_model_persists(db):
    wf = Workflow(
        name="Jenkins Troubleshooter",
        description="Diagnose Jenkins failures",
        trigger_type="manual",
        input_schema={"jenkins_url": "string"},
        steps=[{"id": "abc", "name": "Fetch Log", "connector_type": "jenkins"}],
        created_by="admin",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    assert wf.id is not None
    assert wf.webhook_token is not None
    assert len(wf.webhook_token) == 36  # UUID4

def test_workflow_run_model_persists(db):
    wf = Workflow(name="Test", trigger_type="manual", created_by="admin")
    db.add(wf)
    db.commit()
    run = WorkflowRun(
        workflow_id=wf.id,
        triggered_by="manual",
        trigger_input={"jenkins_url": "http://jenkins/job/1"},
        status="running",
        step_results=[],
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    assert run.id is not None
    assert run.status == "running"


# ---------------------------------------------------------------------------
# API-level tests
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient
from sqlmodel.pool import StaticPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.main import app
from app.api import deps
from app.models.user import User
from app.core import security


@pytest.fixture(name="session")
def session_fixture():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(name="client")
def client_fixture(session: Session):
    db_url = str(session.bind.url)
    async_url = db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    _async_engine = create_async_engine(async_url, connect_args={"check_same_thread": False})
    _AsyncSessionLocal = async_sessionmaker(_async_engine, class_=AsyncSession, expire_on_commit=False)

    def get_session_override():
        return session

    async def get_async_session_override():
        async with _AsyncSessionLocal() as async_session:
            yield async_session

    app.dependency_overrides[deps.get_db] = get_session_override
    app.dependency_overrides[deps.get_async_db] = get_async_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="auth_headers")
def auth_headers_fixture(session: Session, client: TestClient):
    user = User(
        username="wf_testuser",
        hashed_password=security.get_password_hash("testpass"),
        is_active=True,
        role="user",
    )
    session.add(user)
    session.commit()
    resp = client.post("/api/v1/login/access-token", data={"username": "wf_testuser", "password": "testpass"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_workflow(client: TestClient, auth_headers: dict):
    resp = client.post("/api/v1/workflows", json={
        "name": "My Workflow",
        "description": "test",
        "trigger_type": "manual",
        "input_schema": {"url": "string"},
        "steps": [],
    }, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "My Workflow"
    assert "webhook_token" in data


def test_list_workflows(client: TestClient, auth_headers: dict):
    resp = client.get("/api/v1/workflows", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_workflow(client: TestClient, auth_headers: dict):
    create = client.post("/api/v1/workflows", json={
        "name": "Get Test", "trigger_type": "manual", "steps": []
    }, headers=auth_headers)
    wf_id = create.json()["id"]
    resp = client.get(f"/api/v1/workflows/{wf_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == wf_id


def test_update_workflow(client: TestClient, auth_headers: dict):
    create = client.post("/api/v1/workflows", json={
        "name": "Update Test", "trigger_type": "manual", "steps": []
    }, headers=auth_headers)
    wf_id = create.json()["id"]
    resp = client.put(f"/api/v1/workflows/{wf_id}", json={"name": "Updated Name"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


def test_delete_workflow_requires_god_mode(client: TestClient, auth_headers: dict):
    create = client.post("/api/v1/workflows", json={
        "name": "Delete Test", "trigger_type": "manual", "steps": []
    }, headers=auth_headers)
    wf_id = create.json()["id"]
    resp = client.delete(f"/api/v1/workflows/{wf_id}", headers=auth_headers)
    assert resp.status_code == 403
