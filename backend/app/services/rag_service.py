"""
RAG Service — embed, ingest, and retrieve documents via ChromaDB.
"""
import json
import re
import uuid
from datetime import datetime
from typing import List, Optional

# Safety caps — prevent single large pages from saturating RAM/CPU
_MAX_URL_CHARS = 40_000   # ~10k tokens after HTML strip
_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB upload cap

from sqlmodel import Session, select

from app.core.db import engine
from app.models.rag import RagDocument
from app.models.setting import SystemSetting


# ── Chunking ──────────────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_size: int = 2000, overlap: int = 200) -> List[str]:
    """Recursive character-based text splitter (≈500 tokens / 50-token overlap)."""
    if len(text) <= chunk_size:
        return [text]

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        # Try to break at paragraph, then sentence, then space
        if end < len(text):
            for sep in ["\n\n", "\n", ". ", " "]:
                idx = text.rfind(sep, start, end)
                if idx != -1 and idx > start:
                    end = idx + len(sep)
                    break
        chunks.append(text[start:end].strip())
        start = end - overlap
        if start >= len(text):
            break
    return [c for c in chunks if c]


# ── Embedding Providers ───────────────────────────────────────────────────────

class _LocalEmbeddingProvider:
    def __init__(self) -> None:
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._model = SentenceTransformer("all-MiniLM-L6-v2")

    def embed(self, text: str) -> List[float]:
        self._load()
        return self._model.encode(text).tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        self._load()
        if not texts:
            return []
        return [emb.tolist() for emb in self._model.encode(texts, batch_size=32, show_progress_bar=False)]


class _OpenAIEmbeddingProvider:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        self._api_key = api_key
        self._model = model

    def embed(self, text: str) -> List[float]:
        from openai import OpenAI
        client = OpenAI(api_key=self._api_key)
        resp = client.embeddings.create(input=text, model=self._model)
        return resp.data[0].embedding

    def embed_batch(self, texts: List[str], _sub_batch: int = 16) -> List[List[float]]:
        if not texts:
            return []
        import time
        from openai import OpenAI, RateLimitError
        client = OpenAI(api_key=self._api_key)
        results: List[List[float]] = []
        for i in range(0, len(texts), _sub_batch):
            batch = texts[i:i + _sub_batch]
            for attempt in range(5):
                try:
                    resp = client.embeddings.create(input=batch, model=self._model)
                    results.extend(item.embedding for item in sorted(resp.data, key=lambda x: x.index))
                    break
                except RateLimitError:
                    if attempt < 4:
                        time.sleep(60)
                    else:
                        raise
        return results


class _AzureEmbeddingProvider:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model

    def embed(self, text: str) -> List[float]:
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=self._api_key,
            azure_endpoint=self._base_url,
            api_version="2023-05-15",
        )
        resp = client.embeddings.create(input=text, model=self._model)
        return resp.data[0].embedding

    def embed_batch(self, texts: List[str], _sub_batch: int = 16) -> List[List[float]]:
        if not texts:
            return []
        import time
        from openai import AzureOpenAI, RateLimitError
        client = AzureOpenAI(
            api_key=self._api_key,
            azure_endpoint=self._base_url,
            api_version="2023-05-15",
        )
        results: List[List[float]] = []
        for i in range(0, len(texts), _sub_batch):
            batch = texts[i:i + _sub_batch]
            for attempt in range(5):
                try:
                    resp = client.embeddings.create(input=batch, model=self._model)
                    results.extend(item.embedding for item in sorted(resp.data, key=lambda x: x.index))
                    break
                except RateLimitError:
                    if attempt < 4:
                        time.sleep(60)
                    else:
                        raise
        return results


# ── RAG Service ───────────────────────────────────────────────────────────────

class RAGService:
    def _get_setting(self, key: str) -> Optional[str]:
        with Session(engine) as session:
            s = session.get(SystemSetting, key)
            return s.value if s else None

    def _get_embedding_provider(self):
        provider = (self._get_setting("rag_embedding_provider") or "local").lower()
        if provider == "openai":
            api_key = self._get_setting("rag_embedding_api_key") or ""
            model = self._get_setting("rag_embedding_model") or "text-embedding-3-small"
            return _OpenAIEmbeddingProvider(api_key=api_key, model=model)
        elif provider == "azure":
            api_key = self._get_setting("rag_embedding_api_key") or ""
            base_url = self._get_setting("rag_embedding_base_url") or ""
            model = self._get_setting("rag_embedding_model") or "text-embedding-ada-002"
            return _AzureEmbeddingProvider(api_key=api_key, base_url=base_url, model=model)
        else:
            return _LocalEmbeddingProvider()

    def _get_chroma_client(self):
        import chromadb  # type: ignore
        host = self._get_setting("rag_chroma_host") or "localhost"
        port = int(self._get_setting("rag_chroma_port") or "8001")
        return chromadb.HttpClient(host=host, port=port)

    def is_enabled(self) -> bool:
        return (self._get_setting("rag_enabled") or "false").lower() == "true"

    def test_connection(self) -> bool:
        client = self._get_chroma_client()
        client.heartbeat()
        return True

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def ingest_text(
        self,
        text: str,
        title: str,
        source_type: str,
        source_ref: str,
        collection_name: str = "knowledge_base",
        doc_id: Optional[str] = None,
        max_chars: int = 0,
    ) -> RagDocument:
        if max_chars:
            text = text[:max_chars]
        doc_id = doc_id or str(uuid.uuid4())
        embedder = self._get_embedding_provider()
        client = self._get_chroma_client()
        collection = client.get_or_create_collection(collection_name)

        chunks = _chunk_text(text)
        chroma_ids: List[str] = []
        documents: List[str] = []
        embeddings: List[List[float]] = []
        metadatas: List[dict] = []

        all_embeddings = embedder.embed_batch(chunks)
        for i, (chunk, embedding) in enumerate(zip(chunks, all_embeddings)):
            chunk_id = f"{doc_id}_{i}"
            chroma_ids.append(chunk_id)
            documents.append(chunk)
            embeddings.append(embedding)
            if collection_name == "incidents":
                metadatas.append({
                    "conversation_id": source_ref,
                    "conversation_title": title,
                    "created_at": datetime.utcnow().isoformat(),
                })
            else:
                metadatas.append({
                    "source_type": source_type,
                    "source_ref": source_ref,
                    "title": title,
                    "chunk_index": i,
                })

        # Upsert idempotently
        collection.upsert(
            ids=chroma_ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        # Save/update SQLite record
        with Session(engine) as session:
            existing = session.get(RagDocument, doc_id)
            if existing:
                # Delete old chunks from Chroma before re-indexing
                old_ids = json.loads(existing.chroma_ids or "[]")
                if old_ids:
                    try:
                        collection.delete(ids=old_ids)
                    except Exception:
                        pass
                existing.chroma_ids = json.dumps(chroma_ids)
                existing.chunk_count = len(chunks)
                existing.indexed_at = datetime.utcnow()
                existing.status = "indexed"
                session.add(existing)
                session.commit()
                session.refresh(existing)
                return existing
            else:
                doc = RagDocument(
                    id=doc_id,
                    title=title,
                    source_type=source_type,
                    source_ref=source_ref,
                    chroma_ids=json.dumps(chroma_ids),
                    chunk_count=len(chunks),
                    indexed_at=datetime.utcnow(),
                    status="indexed",
                )
                session.add(doc)
                session.commit()
                session.refresh(doc)
                return doc

    def ingest_url(self, url: str) -> RagDocument:
        from app.core.ssrf import validate_url
        validate_url(url)
        import requests  # type: ignore
        resp = requests.get(url, timeout=15, stream=True)
        resp.raise_for_status()
        raw = resp.content[:_MAX_FILE_BYTES]
        content_type = resp.headers.get("content-type", "")
        if "html" in content_type:
            text = _strip_html(raw.decode("utf-8", errors="replace"))
        else:
            text = raw.decode("utf-8", errors="replace")
        text = text[:_MAX_URL_CHARS]
        title = url.split("/")[-1] or url
        return self.ingest_text(
            text=text,
            title=title,
            source_type="external_url",
            source_ref=url,
            collection_name="knowledge_base",
            max_chars=_MAX_URL_CHARS,
        )

    def ingest_file(self, filename: str, content: bytes) -> RagDocument:
        text = _extract_file_text(filename, content)
        return self.ingest_text(
            text=text,
            title=filename,
            source_type="upload",
            source_ref=filename,
            collection_name="knowledge_base",
        )

    def ingest_incident(self, conversation_id: str, conversation_title: str, text: str) -> RagDocument:
        doc_id = f"incident_{conversation_id}"
        return self.ingest_text(
            text=text,
            title=conversation_title,
            source_type="incident",
            source_ref=conversation_id,
            collection_name="incidents",
            doc_id=doc_id,
        )

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def retrieve(self, query: str, collection_name: str, n_results: int = 3) -> str:
        try:
            embedder = self._get_embedding_provider()
            client = self._get_chroma_client()
            collection = client.get_or_create_collection(collection_name)
            query_embedding = embedder.embed(query)
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(n_results, collection.count() or 1),
            )
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            if not docs:
                return "No relevant documents found."
            lines = []
            for i, (doc, meta) in enumerate(zip(docs, metas), 1):
                title = meta.get("title") or meta.get("conversation_title") or "Unknown"
                excerpt = doc[:500]
                lines.append(
                    f'<retrieved_document index="{i}" source="{title}">\n{excerpt}\n</retrieved_document>'
                )
            return "\n\n".join(lines)
        except Exception as e:
            return f"Knowledge base unavailable: {e}"

    # ── Deletion ─────────────────────────────────────────────────────────────

    def delete_document(self, doc_id: str) -> bool:
        with Session(engine) as session:
            doc = session.get(RagDocument, doc_id)
            if not doc:
                return False
            chroma_ids = json.loads(doc.chroma_ids or "[]")
            if chroma_ids:
                try:
                    client = self._get_chroma_client()
                    coll_name = "incidents" if doc.source_type == "incident" else "knowledge_base"
                    collection = client.get_or_create_collection(coll_name)
                    collection.delete(ids=chroma_ids)
                except Exception:
                    pass
            session.delete(doc)
            session.commit()
            return True

    def list_documents(self) -> List[RagDocument]:
        with Session(engine) as session:
            return session.exec(
                select(RagDocument).order_by(RagDocument.indexed_at.desc())
            ).all()



# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_file_text(filename: str, content: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        try:
            from pypdf import PdfReader  # type: ignore
            import io
            reader = PdfReader(io.BytesIO(content))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            raise ValueError(f"Failed to parse PDF: {e}")
    else:
        # Markdown / TXT
        return content.decode("utf-8", errors="replace")


rag_service = RAGService()
