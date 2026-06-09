from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlmodel import Session

from app.api import deps
from app.models.audit import AuditLog
from app.models.user import User
from app.core.db import engine
import app.services.azure_service as azure_service
from datetime import datetime, timezone

router = APIRouter()


# --- Request / Response models ---

class AzureConnectRequest(BaseModel):
    tenant_id: str
    subscription_id: str
    client_id: str
    client_secret: str
    resource_group: Optional[str] = None
    aks_cluster_name: Optional[str] = None

    @field_validator("tenant_id", "subscription_id", "client_id", "client_secret")
    @classmethod
    def must_not_be_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field must not be blank")
        return v.strip()

    @field_validator("resource_group", "aks_cluster_name", mode="before")
    @classmethod
    def empty_to_none(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            return None
        return v


class FeatureToggleRequest(BaseModel):
    enabled: bool


# --- Audit helper ---

def _audit(actor: str, action: str, resource: str, result: str, details: Optional[str] = None) -> None:
    entry = AuditLog(
        actor=actor,
        action=action,
        resource=resource,
        result=result,
        mode="NORMAL",
        source="AZURE",
        details=details,
    )
    with Session(engine) as session:
        session.add(entry)
        session.commit()


# --- Connection endpoints ---

@router.post("/connect")
def connect_azure(
    body: AzureConnectRequest,
    current_user: User = Depends(deps.get_current_user),
) -> Dict[str, Any]:
    try:
        azure_service.connect(
            tenant_id=body.tenant_id,
            subscription_id=body.subscription_id,
            client_id=body.client_id,
            client_secret=body.client_secret,
            resource_group=body.resource_group,
            aks_cluster_name=body.aks_cluster_name,
        )
        _audit(
            actor=current_user.username,
            action="AZURE_CONNECT",
            resource="azure/connection",
            result="SUCCESS",
            details=f"tenant={body.tenant_id} subscription={body.subscription_id}",
        )
        return {"status": "connected"}
    except ValueError as e:
        _audit(
            actor=current_user.username,
            action="AZURE_CONNECT",
            resource="azure/connection",
            result="FAILURE",
            details=str(e),
        )
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/test")
def test_azure_connection(
    current_user: User = Depends(deps.get_current_user),
) -> Dict[str, Any]:
    ok = azure_service.test_connection()
    _audit(
        actor=current_user.username,
        action="AZURE_TEST_CONNECTION",
        resource="azure/connection",
        result="SUCCESS" if ok else "FAILURE",
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Azure connection test failed")
    return {"status": "ok"}


@router.delete("/disconnect")
def disconnect_azure(
    current_user: User = Depends(deps.get_current_user),
) -> Dict[str, Any]:
    azure_service.disconnect()
    _audit(
        actor=current_user.username,
        action="AZURE_DISCONNECT",
        resource="azure/connection",
        result="SUCCESS",
    )
    return {"status": "disconnected"}


@router.get("/status")
def get_azure_status(
    current_user: User = Depends(deps.get_current_user),
) -> Dict[str, Any]:
    return azure_service.get_status()


# --- Feature toggle ---

@router.patch("/features/{feature_key}")
def toggle_feature(
    feature_key: str,
    body: FeatureToggleRequest,
    current_user: User = Depends(deps.get_current_user),
) -> Dict[str, Any]:
    try:
        feature = azure_service.toggle_feature(feature_key, body.enabled)
        action = "AZURE_FEATURE_ENABLE" if body.enabled else "AZURE_FEATURE_DISABLE"
        _audit(
            actor=current_user.username,
            action=action,
            resource=f"azure/feature/{feature_key}",
            result="SUCCESS",
        )
        return {
            "feature_key": feature.feature_key,
            "enabled": feature.enabled,
            "last_synced_at": feature.last_synced_at.isoformat() if feature.last_synced_at else None,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Data endpoints ---

def _guard(feature_key: str) -> None:
    """Shared guard — raises HTTPException if not connected or feature not enabled."""
    conn = azure_service.get_connection()
    if not conn or not conn.is_connected:
        raise HTTPException(status_code=400, detail="Azure not connected")
    from app.models.integration import AzureFeatureConfig
    with Session(engine) as session:
        feature = session.get(AzureFeatureConfig, feature_key)
        if not feature or not feature.enabled:
            raise HTTPException(status_code=403, detail=f"Feature '{feature_key}' is not enabled")


@router.get("/cost")
def get_cost(current_user: User = Depends(deps.get_current_user)) -> Dict[str, Any]:
    _guard("cost_optimization")
    try:
        data = azure_service.get_cost_data()
        _audit(current_user.username, "AZURE_COST_FETCH", "azure/cost", "SUCCESS")
        return data
    except ValueError as e:
        _audit(current_user.username, "AZURE_COST_FETCH", "azure/cost", "FAILURE", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/resources")
def get_resources(current_user: User = Depends(deps.get_current_user)) -> Dict[str, Any]:
    _guard("resource_discovery")
    try:
        data = azure_service.get_rg_resources()
        _audit(
            current_user.username, "AZURE_RESOURCE_DISCOVERY", "azure/resources", "SUCCESS",
            f"direct={data['total_direct']} linked={data['total_linked']}",
        )
        return data
    except ValueError as e:
        _audit(current_user.username, "AZURE_RESOURCE_DISCOVERY", "azure/resources", "FAILURE", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/monitor")
def get_monitor(current_user: User = Depends(deps.get_current_user)) -> Dict[str, Any]:
    _guard("azure_monitor")
    try:
        data = azure_service.get_monitor_metrics()
        _audit(current_user.username, "AZURE_MONITOR_FETCH", "azure/monitor", "SUCCESS")
        return data
    except ValueError as e:
        _audit(current_user.username, "AZURE_MONITOR_FETCH", "azure/monitor", "FAILURE", str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/anomalies")
def get_anomalies(current_user: User = Depends(deps.get_current_user)) -> Dict[str, Any]:
    _guard("cost_anomaly_alerting")
    try:
        data = azure_service.get_cost_anomalies()
        _audit(
            current_user.username, "AZURE_ANOMALY_CHECK", "azure/anomalies", "SUCCESS",
            f"count={data['count']}",
        )
        return data
    except ValueError as e:
        _audit(current_user.username, "AZURE_ANOMALY_CHECK", "azure/anomalies", "FAILURE", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recommendations")
def get_recommendations(
    current_user: User = Depends(deps.get_current_user),
    triggered_by: str = "ui",
) -> Dict[str, Any]:
    _guard("ai_cost_recommendations")
    try:
        data = azure_service.get_advisor_recommendations()
        _audit(
            current_user.username, "AZURE_RECOMMENDATIONS_FETCH", "azure/recommendations",
            "SUCCESS", f"count={data['count']} triggered_by={triggered_by}",
        )
        return data
    except ValueError as e:
        _audit(current_user.username, "AZURE_RECOMMENDATIONS_FETCH", "azure/recommendations", "FAILURE", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-resources")
def analyze_resources(
    current_user: User = Depends(deps.get_current_user),
) -> Dict[str, Any]:
    _guard("resource_discovery")
    try:
        # Fetch the resource list
        resource_data = azure_service.get_rg_resources()

        # Strip to name/type/location only — no IDs, no subscription/tenant data
        all_resources = [
            {"name": r["name"], "type": r["type"], "location": r["location"]}
            for r in resource_data.get("direct_resources", []) + resource_data.get("linked_resources", [])
        ]

        if not all_resources:
            return {
                "summary": "No resources found to analyse.",
                "orphaned": [],
                "anomalies": [],
                "recommendations": [],
            }

        from app.services.ai_service import AIService
        ai = AIService()
        result = ai.analyze_azure_resources(all_resources)

        _audit(
            current_user.username,
            "AZURE_RESOURCE_ANALYSIS",
            "azure/analyze-resources",
            "SUCCESS",
            f"resources_analysed={len(all_resources)}",
        )
        return result
    except ValueError as e:
        _audit(
            current_user.username,
            "AZURE_RESOURCE_ANALYSIS",
            "azure/analyze-resources",
            "FAILURE",
            str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))
