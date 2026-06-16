import uuid
from datetime import datetime
from sqlmodel import Field, SQLModel


class ExternalKnowledgeSource(SQLModel, table=True):
    id: str = Field(primary_key=True, default_factory=lambda: str(uuid.uuid4()))
    name: str
    provider: str  # "azure_ai_search"
    enabled: bool = True
    config: str   # Fernet-encrypted JSON blob
    created_at: datetime = Field(default_factory=datetime.utcnow)
