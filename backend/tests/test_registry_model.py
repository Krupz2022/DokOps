# backend/tests/test_registry_model.py
from sqlmodel import SQLModel, create_engine, Session
from sqlmodel.pool import StaticPool

import app.models.registry  # noqa — registers table


def test_registry_connection_table_creates():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    from app.models.registry import RegistryConnection
    with Session(engine) as db:
        row = RegistryConnection(name="My ACR", url="mycompany.azurecr.io")
        db.add(row)
        db.commit()
        db.refresh(row)
    assert row.id is not None
    assert row.name == "My ACR"
    assert row.created_at is not None
    assert row.password is None
    assert row.username is None
