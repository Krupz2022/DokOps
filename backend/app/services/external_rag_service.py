"""
ExternalRAGService — manage external knowledge source connections and fan-out retrieval.
"""
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

    def test_source(self, source_id: str) -> bool:
        source = self.get_source(source_id)
        if not source:
            return False
        config = self._decrypt_config(source)
        from app.services.connectors.azure_ai_search_connector import retrieve
        retrieve(config, "connection test")
        return True

    def test_config(self, config_dict: dict) -> bool:
        """Test a config dict directly — used by the UI before saving."""
        from app.services.connectors.azure_ai_search_connector import retrieve
        retrieve(config_dict, "connection test")
        return True

    def retrieve_all(self, query: str) -> str:
        sources = [s for s in self.list_sources() if s.enabled]
        if not sources:
            return ""

        from app.services.connectors.azure_ai_search_connector import retrieve

        lines: List[str] = []
        for source in sources:
            try:
                config = self._decrypt_config(source)
                chunks = retrieve(config, query)
                for i, chunk in enumerate(chunks, 1):
                    lines.append(
                        f'<retrieved_document index="{i}" source="{source.name} (Azure AI Search)">\n{chunk}\n</retrieved_document>'
                    )
            except Exception as exc:
                _log.warning("[ExternalRAG] source=%s failed: %s", source.name, exc)

        return "\n\n".join(lines)


external_rag_service = ExternalRAGService()
