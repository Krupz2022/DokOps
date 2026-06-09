import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, SQLModel
from sqlmodel.pool import StaticPool
from unittest.mock import patch

# Import models to register tables
from app.models.patch import (  # noqa: F401
    Organisation,
    MinionGroup,
    MinionGroupMember,
)
from app.models.minion import Minion  # noqa: F401

TEST_DB = "sqlite://"

_FAKE_HASH = "FAKE_BCRYPT_HASH_FOR_TESTING"


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    from app.main import app
    from app.api import deps
    from app.models.user import User

    def get_session_override():
        return session

    def user_override():
        return User(
            id="u1",
            username="admin",
            email="a@b.com",
            hashed_password="x",
            is_superuser=True,
            role="admin",
            is_active=True,
        )

    async def god_override():
        return User(
            id="u1",
            username="admin",
            email="a@b.com",
            hashed_password="x",
            is_superuser=True,
            role="admin",
            is_active=True,
        )

    app.dependency_overrides[deps.get_db] = get_session_override
    app.dependency_overrides[deps.get_current_user] = user_override
    app.dependency_overrides[deps.require_god_mode] = god_override

    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_and_list_org(client):
    r = client.post("/api/v1/organisations/", json={"name": "Acme", "slug": "acme"})
    assert r.status_code == 200
    assert r.json()["slug"] == "acme"

    r2 = client.get("/api/v1/organisations/")
    assert r2.status_code == 200
    assert any(o["slug"] == "acme" for o in r2.json())


def test_create_group_in_org(client):
    r = client.post("/api/v1/organisations/", json={"name": "Corp", "slug": "corp"})
    org_id = r.json()["id"]
    r2 = client.post(
        f"/api/v1/organisations/{org_id}/groups", json={"name": "dev-web"}
    )
    assert r2.status_code == 200
    assert r2.json()["name"] == "dev-web"
