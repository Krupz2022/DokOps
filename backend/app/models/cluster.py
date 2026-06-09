from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel
import uuid


def _uuid() -> str:
    return str(uuid.uuid4())


class ClusterConnection(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str = Field(index=True)
    provider: str = Field(default="generic")   # aks | eks | gke | generic
    api_server: str
    token: str = Field(default="")              # Fernet-encrypted bearer token (empty for cert auth)
    ca_cert: Optional[str] = None               # base64 PEM, optional
    client_cert_data: Optional[str] = None      # base64 PEM client cert (AKS admin / cert auth)
    client_key_data: Optional[str] = None       # base64 PEM client key, Fernet-encrypted
    namespace: str = Field(default="default")
    added_by: Optional[str] = None              # username FK (soft reference)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_verified: Optional[datetime] = None


class CloudCredential(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    provider: str                               # aks | eks | gke
    credential_blob: str                        # Fernet-encrypted JSON
    added_by: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
