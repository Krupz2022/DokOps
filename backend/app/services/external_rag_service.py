"""
ExternalRAGService — manage external knowledge source connections and fan-out retrieval.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlmodel import Session, select

from app.core.db import engine
from app.core.encryption import decrypt, encrypt
from app.models.external_knowledge_source import ExternalKnowledgeSource

_log = logging.getLogger(__name__)

_VECTOR_PROVIDERS = {"qdrant", "pinecone"}
_VALID_PROVIDERS = {"azure_ai_search", "qdrant", "pinecone", "weaviate", "opensearch", "chroma"}


# ── Embedding helper ──────────────────────────────────────────────────────────

def _get_embedding_provider_sync():
    """Read embedding provider settings synchronously and return a provider instance."""
    from app.models.setting import SystemSetting

    def _setting(key: str) -> Optional[str]:
        with Session(engine) as s:
            row = s.get(SystemSetting, key)
            return row.value if row else None

    provider = (_setting("rag_embedding_provider") or "local").lower()
    if provider == "openai":
        from app.services.rag_service import _OpenAIEmbeddingProvider
        return _OpenAIEmbeddingProvider(
            api_key=_setting("rag_embedding_api_key") or "",
            model=_setting("rag_embedding_model") or "text-embedding-3-small",
        )
    elif provider == "azure":
        from app.services.rag_service import _AzureEmbeddingProvider
        return _AzureEmbeddingProvider(
            api_key=_setting("rag_embedding_api_key") or "",
            base_url=_setting("rag_embedding_base_url") or "",
            model=_setting("rag_embedding_model") or "",
        )
    else:
        from app.services.rag_service import _LocalEmbeddingProvider
        return _LocalEmbeddingProvider()


def _embed_query(query: str) -> Optional[List[float]]:
    """Embed query text using DokOps configured embedding service. Returns None on failure."""
    try:
        provider = _get_embedding_provider_sync()
        return provider.embed(query)
    except Exception as exc:
        _log.warning("[ExternalRAG] embedding failed, vector providers will be skipped: %s", exc)
        return None


# ── Connector dispatch ────────────────────────────────────────────────────────

async def _dispatch(
    provider: str,
    config: dict,
    query: str,
    query_vector: Optional[List[float]],
) -> List[str]:
    """Route to the correct connector based on provider string."""
    if provider == "azure_ai_search":
        from app.services.connectors.azure_ai_search_connector import retrieve
        return await retrieve(config, query)
    elif provider == "qdrant":
        if query_vector is None:
            raise ValueError("Embedding not available for Qdrant query")
        from app.services.connectors.qdrant_connector import retrieve
        return await retrieve(config, query_vector)
    elif provider == "pinecone":
        if query_vector is None:
            raise ValueError("Embedding not available for Pinecone query")
        from app.services.connectors.pinecone_connector import retrieve
        return await retrieve(config, query_vector)
    elif provider == "weaviate":
        from app.services.connectors.weaviate_connector import retrieve
        return await retrieve(config, query)
    elif provider == "opensearch":
        from app.services.connectors.opensearch_connector import retrieve
        return await retrieve(config, query)
    elif provider == "chroma":
        from app.services.connectors.chroma_connector import retrieve
        return await retrieve(config, query)
    else:
        raise ValueError(f"Unknown provider: {provider}")


async def _test_connectivity_for(provider: str, config: dict) -> None:
    """Call the provider's test_connectivity function. Raises on failure."""
    # Azure AI Search has no dedicated connectivity check; a no-op search serves as a probe.
    if provider == "azure_ai_search":
        from app.services.connectors.azure_ai_search_connector import retrieve
        await retrieve(config, "connection test")
    elif provider == "qdrant":
        from app.services.connectors.qdrant_connector import test_connectivity
        await test_connectivity(config)
    elif provider == "pinecone":
        from app.services.connectors.pinecone_connector import test_connectivity
        await test_connectivity(config)
    elif provider == "weaviate":
        from app.services.connectors.weaviate_connector import test_connectivity
        await test_connectivity(config)
    elif provider == "opensearch":
        from app.services.connectors.opensearch_connector import test_connectivity
        await test_connectivity(config)
    elif provider == "chroma":
        from app.services.connectors.chroma_connector import test_connectivity
        await test_connectivity(config)
    else:
        raise ValueError(f"Unknown provider: {provider}")


# ── Service ───────────────────────────────────────────────────────────────────

class ExternalRAGService:
    def list_sources(self) -> List[ExternalKnowledgeSource]:
        with Session(engine) as session:
            return list(session.exec(
                select(ExternalKnowledgeSource).order_by(ExternalKnowledgeSource.created_at)
            ).all())

    def get_source(self, source_id: str) -> Optional[ExternalKnowledgeSource]:
        with Session(engine) as session:
            return session.get(ExternalKnowledgeSource, source_id)

    def _decrypt_config(self, source: ExternalKnowledgeSource) -> dict:
        return json.loads(decrypt(source.config))

    def create_source(self, name: str, provider: str, config_dict: dict) -> ExternalKnowledgeSource:
        source = ExternalKnowledgeSource(
            id=str(uuid.uuid4()),
            name=name,
            provider=provider,
            enabled=True,
            config=encrypt(json.dumps(config_dict)),
            created_at=datetime.now(timezone.utc),
        )
        with Session(engine) as session:
            session.add(source)
            session.commit()
            session.refresh(source)
            return source

    def update_source(
        self,
        source_id: str,
        name: Optional[str] = None,
        enabled: Optional[bool] = None,
        config_dict: Optional[dict] = None,
    ) -> Optional[ExternalKnowledgeSource]:
        with Session(engine) as session:
            source = session.get(ExternalKnowledgeSource, source_id)
            if not source:
                return None
            if name is not None:
                source.name = name
            if enabled is not None:
                source.enabled = enabled
            if config_dict is not None:
                source.config = encrypt(json.dumps(config_dict))
            session.add(source)
            session.commit()
            session.refresh(source)
            return source

    def delete_source(self, source_id: str) -> bool:
        with Session(engine) as session:
            source = session.get(ExternalKnowledgeSource, source_id)
            if not source:
                return False
            session.delete(source)
            session.commit()
            return True

    async def test_source(self, source_id: str) -> bool:
        source = self.get_source(source_id)
        if not source:
            return False
        config = self._decrypt_config(source)
        await _test_connectivity_for(source.provider, config)
        return True

    async def test_config(self, provider: str, config_dict: dict) -> bool:
        """Test a provider config dict directly — used by the UI before saving."""
        await _test_connectivity_for(provider, config_dict)
        return True

    async def retrieve_all(self, query: str) -> str:
        sources = [s for s in self.list_sources() if s.enabled]
        if not sources:
            return ""

        needs_vector = any(s.provider in _VECTOR_PROVIDERS for s in sources)
        query_vector: Optional[List[float]] = _embed_query(query) if needs_vector else None

        async def _retrieve_source(source) -> List[str]:
            config = self._decrypt_config(source)
            return await _dispatch(source.provider, config, query, query_vector)

        results = await asyncio.gather(
            *[_retrieve_source(s) for s in sources],
            return_exceptions=True,
        )

        lines: List[str] = []
        for source, result in zip(sources, results):
            if isinstance(result, Exception):
                _log.warning("[ExternalRAG] source=%s failed: %s", source.name, result)
                continue
            for i, chunk in enumerate(result, 1):
                lines.append(
                    f'<retrieved_document index="{i}" source="{source.name} ({source.provider})">\n{chunk}\n</retrieved_document>'
                )

        return "\n\n".join(lines)


external_rag_service = ExternalRAGService()
