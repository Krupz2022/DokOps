from datetime import datetime
from typing import Optional
import uuid

from sqlmodel import Field, SQLModel

from app.core.datetimes import utc_field


def _uuid() -> str:
    return str(uuid.uuid4())


class RegistryConnection(SQLModel, table=True):
    __tablename__ = "registryconnection"
    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str
    url: str                         # e.g. mycompany.azurecr.io  (no trailing slash)
    username: Optional[str] = None
    password: Optional[str] = None   # Fernet-encrypted at rest
    added_by: Optional[str] = None
    created_at: datetime = utc_field()
