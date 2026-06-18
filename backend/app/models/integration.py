from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

from app.core.datetimes import utc_optional_field


class AzureConnection(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    tenant_id: str
    subscription_id: str
    client_id: str
    client_secret: str          # Fernet-encrypted, never returned in responses
    resource_group: Optional[str] = None
    aks_cluster_name: Optional[str] = None   # Used by Azure Monitor
    is_connected: bool = False
    connected_at: Optional[datetime] = utc_optional_field()


class AzureFeatureConfig(SQLModel, table=True):
    feature_key: str = Field(primary_key=True)  # "cost_optimization" | "resource_discovery" | "azure_monitor" | "cost_anomaly_alerting" | "ai_cost_recommendations"
    enabled: bool = False
    last_synced_at: Optional[datetime] = utc_optional_field()
    config_json: Optional[str] = None


class IntegrationSettings(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    backend: str
    display_name: str
    base_url: str
    auth_type: str = "none"
    encrypted_credentials: Optional[str] = None
    is_active: bool = False
    connected_at: Optional[datetime] = utc_optional_field()
    last_checked_at: Optional[datetime] = utc_optional_field()
    health_status: Optional[str] = None
