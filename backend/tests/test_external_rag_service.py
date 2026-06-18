import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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


def _make_source(name: str, enabled: bool = True) -> dict:
    from app.core.encryption import encrypt
    config = {"endpoint": "https://test.search.windows.net", "api_key": "k", "index_name": "idx", "top_k": 2, "semantic_config": ""}
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "provider": "azure_ai_search",
        "enabled": enabled,
        "config": encrypt(json.dumps(config)),
    }


@patch("app.services.external_rag_service.engine")
def test_create_source_encrypts_api_key(mock_engine):
    mock_session = MagicMock()
    mock_engine.__class__ = type(mock_engine)
    from app.services.external_rag_service import ExternalRAGService
    svc = ExternalRAGService()

    with patch("app.services.external_rag_service.Session") as MockSession:
        mock_ctx = MagicMock()
        MockSession.return_value.__enter__ = lambda s: mock_ctx
        MockSession.return_value.__exit__ = MagicMock(return_value=False)

        config_dict = {"endpoint": "https://x.search.windows.net", "api_key": "secret", "index_name": "idx", "top_k": 3, "semantic_config": ""}
        svc.create_source("Wiki", "azure_ai_search", config_dict)

        added = mock_ctx.add.call_args[0][0]
        # stored config must not be the raw api_key
        assert "secret" not in added.config
        # but must be decryptable
        from app.core.encryption import decrypt
        stored = json.loads(decrypt(added.config))
        assert stored["api_key"] == "secret"


@patch("app.services.connectors.azure_ai_search_connector.retrieve", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_retrieve_all_returns_xml_chunks(mock_retrieve):
    mock_retrieve.return_value = ["chunk A", "chunk B"]

    from app.services.external_rag_service import ExternalRAGService
    svc = ExternalRAGService()

    from app.models.external_knowledge_source import ExternalKnowledgeSource
    from app.core.encryption import encrypt
    config = {"endpoint": "https://x.search.windows.net", "api_key": "k", "index_name": "i", "top_k": 2, "semantic_config": ""}
    source = ExternalKnowledgeSource(
        id="s1", name="Wiki", provider="azure_ai_search", enabled=True,
        config=encrypt(json.dumps(config))
    )
    with patch.object(svc, "list_sources", return_value=[source]):
        result = await svc.retrieve_all("pod crash")

    assert '<retrieved_document' in result
    assert 'chunk A' in result
    assert 'Wiki (azure_ai_search)' in result


@patch("app.services.connectors.azure_ai_search_connector.retrieve", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_retrieve_all_skips_disabled_sources(mock_retrieve):
    mock_retrieve.return_value = ["chunk"]

    from app.services.external_rag_service import ExternalRAGService
    svc = ExternalRAGService()

    from app.models.external_knowledge_source import ExternalKnowledgeSource
    from app.core.encryption import encrypt
    config = {"endpoint": "https://x.search.windows.net", "api_key": "k", "index_name": "i", "top_k": 2, "semantic_config": ""}
    disabled = ExternalKnowledgeSource(
        id="d1", name="Disabled", provider="azure_ai_search", enabled=False,
        config=encrypt(json.dumps(config))
    )
    with patch.object(svc, "list_sources", return_value=[disabled]):
        result = await svc.retrieve_all("query")

    assert result == ""
    mock_retrieve.assert_not_called()


@patch("app.services.connectors.azure_ai_search_connector.retrieve", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_retrieve_all_catches_connector_exception(mock_retrieve):
    mock_retrieve.side_effect = Exception("network error")

    from app.services.external_rag_service import ExternalRAGService
    svc = ExternalRAGService()

    from app.models.external_knowledge_source import ExternalKnowledgeSource
    from app.core.encryption import encrypt
    config = {"endpoint": "https://x.search.windows.net", "api_key": "k", "index_name": "i", "top_k": 2, "semantic_config": ""}
    source = ExternalKnowledgeSource(
        id="s1", name="Broken", provider="azure_ai_search", enabled=True,
        config=encrypt(json.dumps(config))
    )
    with patch.object(svc, "list_sources", return_value=[source]):
        result = await svc.retrieve_all("query")  # must not raise

    assert result == ""


@pytest.mark.asyncio
async def test_retrieve_all_no_sources_returns_empty():
    from app.services.external_rag_service import ExternalRAGService
    svc = ExternalRAGService()
    with patch.object(svc, "list_sources", return_value=[]):
        assert await svc.retrieve_all("query") == ""
