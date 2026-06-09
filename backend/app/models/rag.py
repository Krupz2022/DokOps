from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class RagDocument(SQLModel, table=True):
    id: str = Field(primary_key=True)
    title: str
    source_type: str  # runbook | upload | external_url | incident
    source_ref: str   # Runbook ID, file path, URL, or conversation_id
    chroma_ids: str   # JSON list of ChromaDB chunk IDs
    chunk_count: int = 0
    indexed_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "pending"  # indexed | failed | pending
