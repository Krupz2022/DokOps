"""
RAG Service — embed, ingest, and retrieve documents via ChromaDB.
"""
import asyncio
import json
import re
import uuid
from datetime import datetime
from typing import List, Optional

from app.core.datetimes import utcnow

# Safety caps — prevent single large pages from saturating RAM/CPU
_MAX_URL_CHARS = 40_000   # ~10k tokens after HTML strip
_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB upload cap

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import AsyncSessionLocal
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
        # Advance with overlap, but guarantee forward progress. When the chosen
        # break sits within `overlap` chars of `start` (e.g. a long run with no
        # whitespace, as in big PDFs), `end - overlap` would stall or move back,
        # looping forever and exhausting memory — so never let `start` regress.
        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start
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
    async def _get_setting(self, key: str) -> Optional[str]:
        async with AsyncSessionLocal() as session:
            s = await session.get(SystemSetting, key)
            return s.value if s else None

    async def _get_embedding_provider(self):
        provider = (await self._get_setting("rag_embedding_provider") or "local").lower()
        if provider == "openai":
            api_key = await self._get_setting("rag_embedding_api_key") or ""
            model = await self._get_setting("rag_embedding_model") or "text-embedding-3-small"
            return _OpenAIEmbeddingProvider(api_key=api_key, model=model)
        elif provider == "azure":
            api_key = await self._get_setting("rag_embedding_api_key") or ""
            base_url = await self._get_setting("rag_embedding_base_url") or ""
            model = await self._get_setting("rag_embedding_model") or "text-embedding-ada-002"
            return _AzureEmbeddingProvider(api_key=api_key, base_url=base_url, model=model)
        else:
            return _LocalEmbeddingProvider()

    async def _get_chroma_client(self):
        import chromadb  # type: ignore
        host = await self._get_setting("rag_chroma_host") or "localhost"
        port = int(await self._get_setting("rag_chroma_port") or "8001")
        return chromadb.HttpClient(host=host, port=port)

    async def is_enabled(self) -> bool:
        return (await self._get_setting("rag_enabled") or "false").lower() == "true"

    async def test_connection(self) -> bool:
        client = await self._get_chroma_client()
        client.heartbeat()
        return True

    # ── Ingestion ─────────────────────────────────────────────────────────────

    async def ingest_text(
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
        embedder = await self._get_embedding_provider()
        client = await self._get_chroma_client()
        # Opening the collection is a synchronous Chroma HTTP call; keep it off the loop.
        collection = await asyncio.to_thread(client.get_or_create_collection, collection_name)

        chunks = _chunk_text(text)
        chroma_ids: List[str] = []
        documents: List[str] = []
        embeddings: List[List[float]] = []
        metadatas: List[dict] = []

        # Offload the CPU-bound embedding call to a worker thread so it never
        # pins the event loop (a large doc otherwise freezes /health → SIGKILL).
        all_embeddings = await asyncio.to_thread(embedder.embed_batch, chunks)
        for i, (chunk, embedding) in enumerate(zip(chunks, all_embeddings)):
            chunk_id = f"{doc_id}_{i}"
            chroma_ids.append(chunk_id)
            documents.append(chunk)
            embeddings.append(embedding)
            if collection_name == "incidents":
                metadatas.append({
                    "conversation_id": source_ref,
                    "conversation_title": title,
                    "created_at": utcnow().isoformat(),
                })
            else:
                metadatas.append({
                    "source_type": source_type,
                    "source_ref": source_ref,
                    "title": title,
                    "chunk_index": i,
                })

        # Upsert idempotently. This is a synchronous Chroma HTTP call, so run it
        # off the event loop to keep the loop responsive on large documents.
        await asyncio.to_thread(
            collection.upsert,
            ids=chroma_ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        # Save/update SQLite record
        async with AsyncSessionLocal() as session:
            existing = await session.get(RagDocument, doc_id)
            if existing:
                # Delete old chunks from Chroma before re-indexing
                old_ids = json.loads(existing.chroma_ids or "[]")
                if old_ids:
                    try:
                        # Synchronous Chroma HTTP call — run off the loop.
                        await asyncio.to_thread(collection.delete, ids=old_ids)
                    except Exception:
                        pass
                existing.chroma_ids = json.dumps(chroma_ids)
                existing.chunk_count = len(chunks)
                existing.indexed_at = utcnow()
                existing.status = "indexed"
                session.add(existing)
                await session.commit()
                await session.refresh(existing)
                return existing
            else:
                doc = RagDocument(
                    id=doc_id,
                    title=title,
                    source_type=source_type,
                    source_ref=source_ref,
                    chroma_ids=json.dumps(chroma_ids),
                    chunk_count=len(chunks),
                    indexed_at=utcnow(),
                    status="indexed",
                )
                session.add(doc)
                await session.commit()
                await session.refresh(doc)
                return doc

    async def ingest_url(self, url: str) -> RagDocument:
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
        return await self.ingest_text(
            text=text,
            title=title,
            source_type="external_url",
            source_ref=url,
            collection_name="knowledge_base",
            max_chars=_MAX_URL_CHARS,
        )

    async def ingest_file(self, filename: str, content: bytes) -> RagDocument:
        # PDF parsing (pypdf) is CPU-bound; run it off the event loop.
        text = await asyncio.to_thread(_extract_file_text, filename, content)
        return await self.ingest_text(
            text=text,
            title=filename,
            source_type="upload",
            source_ref=filename,
            collection_name="knowledge_base",
        )

    async def ingest_incident(self, conversation_id: str, conversation_title: str, text: str) -> RagDocument:
        doc_id = f"incident_{conversation_id}"
        return await self.ingest_text(
            text=text,
            title=conversation_title,
            source_type="incident",
            source_ref=conversation_id,
            collection_name="incidents",
            doc_id=doc_id,
        )

    # ── Retrieval ─────────────────────────────────────────────────────────────

    async def retrieve(self, query: str, collection_name: str, n_results: int = 3) -> str:
        try:
            embedder = await self._get_embedding_provider()
            client = await self._get_chroma_client()
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
                lines.append(
                    f'<retrieved_document index="{i}" source="{title}">\n{doc}\n</retrieved_document>'
                )
            return "\n\n".join(lines)
        except Exception as e:
            return f"Knowledge base unavailable: {e}"

    # ── Deletion ─────────────────────────────────────────────────────────────

    async def delete_document(self, doc_id: str) -> bool:
        async with AsyncSessionLocal() as session:
            doc = await session.get(RagDocument, doc_id)
            if not doc:
                return False
            chroma_ids = json.loads(doc.chroma_ids or "[]")
            if chroma_ids:
                try:
                    client = await self._get_chroma_client()
                    coll_name = "incidents" if doc.source_type == "incident" else "knowledge_base"
                    collection = client.get_or_create_collection(coll_name)
                    collection.delete(ids=chroma_ids)
                except Exception:
                    pass
            await session.delete(doc)
            await session.commit()
            return True

    async def list_documents(self) -> List[RagDocument]:
        async with AsyncSessionLocal() as session:
            return (await session.exec(
                select(RagDocument).order_by(RagDocument.indexed_at.desc())
            )).all()



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
