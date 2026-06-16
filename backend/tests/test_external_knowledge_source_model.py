import uuid
from datetime import datetime
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def test_model_fields_and_defaults():
    from app.models.external_knowledge_source import ExternalKnowledgeSource
    source = ExternalKnowledgeSource(
        id=str(uuid.uuid4()),
        name="Company Wiki",
        provider="azure_ai_search",
        config='{"encrypted": "data"}',
    )
    assert source.enabled is True
    assert source.provider == "azure_ai_search"
    assert isinstance(source.created_at, datetime)


def test_pk_default_factory():
    """Constructing without an explicit id should auto-generate a non-empty UUID string."""
    from app.models.external_knowledge_source import ExternalKnowledgeSource
    source = ExternalKnowledgeSource(
        name="Auto ID Source",
        provider="azure_ai_search",
        config="encrypted",
    )
    assert source.id is not None
    assert isinstance(source.id, str)
    assert len(source.id) > 0


def test_model_roundtrips_in_sqlite():
    from app.models.external_knowledge_source import ExternalKnowledgeSource
    engine = _make_engine()
    source_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(ExternalKnowledgeSource(
            id=source_id,
            name="Test",
            provider="azure_ai_search",
            config="encrypted",
        ))
        session.commit()
    with Session(engine) as session:
        row = session.get(ExternalKnowledgeSource, source_id)
        assert row is not None
        assert row.name == "Test"
        assert row.enabled is True
