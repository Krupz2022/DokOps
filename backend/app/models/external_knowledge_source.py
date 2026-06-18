import uuid
from datetime import datetime
from sqlmodel import Field, SQLModel

from app.core.datetimes import utc_field


class ExternalKnowledgeSource(SQLModel, table=True):
    __tablename__ = "external_knowledge_sources"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid.uuid4()))
    name: str
    provider: str  # "azure_ai_search"
    enabled: bool = True
    config: str   # Fernet-encrypted JSON blob
    created_at: datetime = utc_field()
