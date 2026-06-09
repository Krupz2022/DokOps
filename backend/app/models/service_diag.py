from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


def _uuid() -> str:
    return str(uuid.uuid4())


class ServiceCredential(SQLModel, table=True):
    __tablename__ = "servicecredential"
    id: str = Field(default_factory=_uuid, primary_key=True)
    scope_type: str                    # global | group | minion | cluster
    scope_id: Optional[str] = None    # null for global; cluster.id for cluster scope
    service_type: str                  # rabbitmq | redis | couchdb | mongodb | mysql | postgres
    username: str                      # Fernet-encrypted
    password: str                      # Fernet-encrypted
    port: Optional[int] = None
    host: Optional[str] = None         # host/endpoint for the service
    instance_name: str = Field(default="")  # named instance, e.g. "cache", "sessions"; "" = default
    extra: str = Field(default="{}")         # JSON text — vhost, db index, etc.
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DiscoveredService(SQLModel, table=True):
    __tablename__ = "discoveredservice"
    id: str = Field(default_factory=_uuid, primary_key=True)
    minion_id: str = Field(foreign_key="minion.id", index=True)
    service_type: str
    install_type: str                   # native | docker
    container_name: Optional[str] = None
    port: int
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    overridden: bool = False
