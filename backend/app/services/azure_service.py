import base64
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _kql_escape(value: str) -> str:
    """Escape single quotes for safe interpolation into KQL string literals."""
    return value.replace("'", "''")

from azure.identity.aio import ClientSecretCredential
from azure.mgmt.resource.resources.aio import ResourceManagementClient
from cryptography.fernet import Fernet
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.integration import AzureConnection, AzureFeatureConfig

logger = logging.getLogger(__name__)

VALID_FEATURE_KEYS = {
    "cost_optimization",
    "resource_discovery",
    "azure_monitor",
    "cost_anomaly_alerting",
    "ai_cost_recommendations",
}


# --- Encryption helpers ---

def _get_fernet() -> Fernet:
    """Derive a Fernet key from AUTH_SECRET_KEY using SHA-256."""
    raw = settings.AUTH_SECRET_KEY.encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()


# --- Credential builder ---

def _build_credential(connection: AzureConnection) -> ClientSecretCredential:
    return ClientSecretCredential(
        tenant_id=connection.tenant_id,
        client_id=connection.client_id,
        client_secret=decrypt_secret(connection.client_secret),
    )


# --- Connection management ---

async def get_connection() -> Optional[AzureConnection]:
    async with AsyncSessionLocal() as session:
        return await session.get(AzureConnection, 1)


async def connect(
    tenant_id: str,
    subscription_id: str,
    client_id: str,
    client_secret: str,
    resource_group: Optional[str] = None,
    aks_cluster_name: Optional[str] = None,
) -> AzureConnection:
    """
    Validate credentials against Azure, encrypt the secret, and persist the connection.
    Raises ValueError if the credentials are invalid or the RG does not exist.
    """
    credential = ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )
    try:
        async with credential, ResourceManagementClient(credential, subscription_id) as rm_client:
            if resource_group:
                await rm_client.resource_groups.get(resource_group)
            else:
                # No RG — validate credentials by listing resource groups (just first page)
                async for _rg in rm_client.resource_groups.list():
                    break
    except Exception as e:
        raise ValueError(f"Azure connection failed: {e}")

    encrypted = encrypt_secret(client_secret)
    async with AsyncSessionLocal() as session:
        # Upsert the single (id=1) connection row in place.
        conn = await session.get(AzureConnection, 1)
        if conn is None:
            conn = AzureConnection(id=1)
            session.add(conn)
        conn.tenant_id = tenant_id
        conn.subscription_id = subscription_id
        conn.client_id = client_id
        conn.client_secret = encrypted
        conn.resource_group = resource_group
        conn.aks_cluster_name = aks_cluster_name
        conn.is_connected = True
        conn.connected_at = datetime.now(timezone.utc)
        # Seed default feature configs if they don't exist
        for key in VALID_FEATURE_KEYS:
            if not await session.get(AzureFeatureConfig, key):
                session.add(AzureFeatureConfig(feature_key=key))
        await session.commit()
        await session.refresh(conn)
    return conn


async def test_connection() -> bool:
    """Re-test the stored connection. Updates is_connected in DB. Returns True/False."""
    conn = await get_connection()
    if not conn:
        return False
    try:
        credential = _build_credential(conn)
        async with credential, ResourceManagementClient(credential, conn.subscription_id) as rm_client:
            await rm_client.resource_groups.get(conn.resource_group)
        async with AsyncSessionLocal() as session:
            stored = await session.get(AzureConnection, 1)
            if stored:
                stored.is_connected = True
                session.add(stored)
                await session.commit()
        return True
    except Exception as e:
        logger.warning(f"Azure connection test failed: {e}")
        async with AsyncSessionLocal() as session:
            stored = await session.get(AzureConnection, 1)
            if stored:
                stored.is_connected = False
                session.add(stored)
                await session.commit()
        return False


async def disconnect() -> None:
    """Delete the stored connection and reset all feature configs."""
    async with AsyncSessionLocal() as session:
        conn = await session.get(AzureConnection, 1)
        if conn:
            await session.delete(conn)
        features = (await session.exec(select(AzureFeatureConfig))).all()
        for f in features:
            await session.delete(f)
        await session.commit()


async def get_status() -> Dict[str, Any]:
    """Return connection status and all feature states."""
    conn = await get_connection()
    async with AsyncSessionLocal() as session:
        features = (await session.exec(select(AzureFeatureConfig))).all()
    return {
        "connected": conn is not None and conn.is_connected,
        "tenant_id": conn.tenant_id if conn else None,
        "subscription_id": conn.subscription_id if conn else None,
        "resource_group": conn.resource_group if conn else None,
        "aks_cluster_name": conn.aks_cluster_name if conn else None,
        "connected_at": conn.connected_at.isoformat() if conn and conn.connected_at else None,
        "features": {
            f.feature_key: {
                "enabled": f.enabled,
                "last_synced_at": f.last_synced_at.isoformat() if f.last_synced_at else None,
            }
            for f in features
        },
    }


async def toggle_feature(feature_key: str, enabled: bool) -> AzureFeatureConfig:
    """Enable or disable a feature. Raises ValueError if feature_key is unknown."""
    if feature_key not in VALID_FEATURE_KEYS:
        raise ValueError(f"Unknown feature key: {feature_key}")
    async with AsyncSessionLocal() as session:
        feature = await session.get(AzureFeatureConfig, feature_key)
        if not feature:
            feature = AzureFeatureConfig(feature_key=feature_key)
        feature.enabled = enabled
        session.add(feature)
        await session.commit()
        await session.refresh(feature)
        return feature


# --- Data methods ---

async def _require_connection_and_feature(feature_key: str) -> AzureConnection:
    """
    Returns the active AzureConnection if connected and the feature is enabled.
    Raises ValueError otherwise (router maps this to HTTP errors).
    """
    conn = await get_connection()
    if not conn or not conn.is_connected:
        raise ValueError("Azure not connected")
    async with AsyncSessionLocal() as session:
        feature = await session.get(AzureFeatureConfig, feature_key)
        if not feature or not feature.enabled:
            raise ValueError(f"Feature '{feature_key}' is not enabled")
    return conn


def _build_scope(conn: AzureConnection) -> str:
    """Subscription-level scope when no RG set, RG-level scope otherwise."""
    base = f"/subscriptions/{conn.subscription_id}"
    if conn.resource_group:
        return f"{base}/resourceGroups/{conn.resource_group}"
    return base


async def _update_last_synced(feature_key: str) -> None:
    async with AsyncSessionLocal() as session:
        feature = await session.get(AzureFeatureConfig, feature_key)
        if feature:
            feature.last_synced_at = datetime.now(timezone.utc)
            session.add(feature)
            await session.commit()


async def get_cost_data() -> Dict[str, Any]:
    """
    Pull 30-day cost breakdown for all resources in the target resource group.
    Requires feature 'cost_optimization' to be enabled.
    """
    from azure.mgmt.costmanagement.aio import CostManagementClient
    from azure.mgmt.costmanagement.models import (
        QueryDefinition, QueryTimePeriod, QueryDataset,
        QueryAggregation, QueryGrouping, TimeframeType,
    )

    conn = await _require_connection_and_feature("cost_optimization")
    credential = _build_credential(conn)

    scope = _build_scope(conn)
    query = QueryDefinition(
        type="ActualCost",
        timeframe=TimeframeType.MONTH_TO_DATE,
        dataset=QueryDataset(
            granularity="None",
            aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
            grouping=[QueryGrouping(type="Dimension", name="ResourceId")],
        ),
    )
    try:
        async with credential, CostManagementClient(credential) as client:
            result = await client.query.usage(scope, query, api_version="2023-11-01")
    except Exception as e:
        err_str = str(e)
        if "not supported" in err_str.lower() or "BillingAccount" in err_str or "offer" in err_str.lower():
            raise ValueError(
                "Cost Management is not available for your subscription type. "
                "It requires Pay-As-You-Go, Enterprise Agreement, or Microsoft Customer Agreement."
            )
        raise

    rows = []
    if result.rows:
        cols = [c.name for c in result.columns] if result.columns else []
        for row in result.rows:
            rows.append(dict(zip(cols, row)))

    await _update_last_synced("cost_optimization")
    return {"scope": scope, "rows": rows, "column_names": [c.name for c in (result.columns or [])]}


async def get_rg_resources() -> Dict[str, Any]:
    """
    List all resources in the target RG, plus subscription-wide resources whose
    names partially match the RG name (fuzzy-linked resources via Resource Graph).
    Requires feature 'resource_discovery' to be enabled.
    """
    from azure.mgmt.resource.resources.aio import ResourceManagementClient as RmClient
    from azure.mgmt.resourcegraph.aio import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest

    conn = await _require_connection_and_feature("resource_discovery")
    credential = _build_credential(conn)

    async with credential, RmClient(credential, conn.subscription_id) as rm_client, \
            ResourceGraphClient(credential) as graph_client:
        if conn.resource_group:
            # RG-scoped: list direct resources + fuzzy-linked across subscription
            direct = [
                {"id": r.id, "name": r.name, "type": r.type, "location": r.location, "linked": False}
                async for r in rm_client.resources.list_by_resource_group(conn.resource_group)
            ]
            rg_prefix = _kql_escape(conn.resource_group.split("-")[0])
            safe_rg = _kql_escape(conn.resource_group)
            graph_query = (
                f"Resources "
                f"| where name contains '{rg_prefix}' "
                f"| where resourceGroup != '{safe_rg}' "
                f"| project id, name, type, location, resourceGroup | limit 50"
            )
        else:
            # Subscription-wide: list all resources via Resource Graph
            direct = []
            graph_query = (
                "Resources | project id, name, type, location, resourceGroup | limit 200"
            )

        graph_result = await graph_client.resources(
            QueryRequest(subscriptions=[conn.subscription_id], query=graph_query)
        )
    fuzzy = [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "type": r.get("type"),
            "location": r.get("location"),
            "resource_group": r.get("resourceGroup"),
            "linked": bool(conn.resource_group),
        }
        for r in (graph_result.data or [])
    ]

    await _update_last_synced("resource_discovery")
    return {
        "resource_group": conn.resource_group or "subscription-wide",
        "direct_resources": direct,
        "linked_resources": fuzzy,
        "total_direct": len(direct),
        "total_linked": len(fuzzy),
    }


async def get_monitor_metrics() -> Dict[str, Any]:
    """
    Fetch standard AKS platform metrics (CPU %, memory %) from Azure Monitor.
    Requires feature 'azure_monitor' enabled and aks_cluster_name set on the connection.
    """
    from datetime import timedelta
    from azure.monitor.querymetrics.aio import MetricsClient
    from azure.monitor.querymetrics import MetricAggregationType
    from azure.mgmt.resourcegraph.aio import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest
    from azure.core.exceptions import HttpResponseError

    conn = await _require_connection_and_feature("azure_monitor")
    if not conn.aks_cluster_name:
        raise ValueError(
            "aks_cluster_name is not set on the Azure connection. "
            "Update the connection with the AKS cluster name to use Azure Monitor."
        )

    credential = _build_credential(conn)

    resource_uri = (
        f"/subscriptions/{conn.subscription_id}"
        f"/resourceGroups/{conn.resource_group}"
        f"/providers/Microsoft.ContainerService/managedClusters/{conn.aks_cluster_name}"
    )

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=1)

    try:
        async with credential:
            # MetricsClient needs a region-scoped endpoint; the cluster's region
            # isn't stored on the connection, so resolve it via Resource Graph.
            async with ResourceGraphClient(credential) as graph_client:
                region_result = await graph_client.resources(QueryRequest(
                    subscriptions=[conn.subscription_id],
                    query=(
                        f"Resources | where id =~ '{_kql_escape(resource_uri)}' "
                        f"| project location | limit 1"
                    ),
                ))
            if not region_result.data:
                raise ValueError(f"AKS cluster '{conn.aks_cluster_name}' not found in subscription.")
            region = region_result.data[0]["location"]

            endpoint = f"https://{region}.metrics.monitor.azure.com"
            async with MetricsClient(endpoint, credential) as client:
                results = await client.query_resources(
                    resource_ids=[resource_uri],
                    metric_namespace="Microsoft.ContainerService/managedClusters",
                    metric_names=["node_cpu_usage_percentage", "node_memory_rss_percentage"],
                    timespan=(start_time, end_time),
                    aggregations=[MetricAggregationType.AVERAGE],
                )
    except HttpResponseError as e:
        raise ValueError(f"Azure Monitor query failed: {e.message}")

    metrics = []
    for result in results:
        for metric in result.metrics:
            for ts in metric.timeseries:
                for dp in ts.data:
                    metrics.append({
                        "metric": metric.name,
                        "timestamp": dp.timestamp.isoformat() if dp.timestamp else None,
                        "average": dp.average,
                    })

    await _update_last_synced("azure_monitor")
    return {"resource_uri": resource_uri, "metrics": metrics}


async def get_cost_anomalies() -> Dict[str, Any]:
    """
    Retrieve cost anomaly alerts for the target resource group from Azure Cost Management.
    Requires feature 'cost_anomaly_alerting' enabled.
    """
    from azure.mgmt.costmanagement.aio import CostManagementClient
    from azure.core.exceptions import HttpResponseError

    conn = await _require_connection_and_feature("cost_anomaly_alerting")
    credential = _build_credential(conn)

    scope = _build_scope(conn)

    anomalies = []
    try:
        async with credential, CostManagementClient(credential) as client:
            alerts_result = await client.alerts.list(scope, api_version="2023-11-01")
            for alert in (alerts_result.value or []):
                if alert.properties and alert.properties.definition:
                    anomalies.append({
                        "id": alert.id,
                        "name": alert.name,
                        "status": str(alert.properties.status) if alert.properties.status else None,
                        "time_created": (
                            alert.properties.time_created.isoformat()
                            if alert.properties.time_created else None
                        ),
                        "details": str(alert.properties.details) if alert.properties.details else None,
                    })
    except HttpResponseError as e:
        raise ValueError(f"Cost anomaly fetch failed: {e.message}")

    await _update_last_synced("cost_anomaly_alerting")
    return {"scope": scope, "anomalies": anomalies, "count": len(anomalies)}


async def get_advisor_recommendations() -> Dict[str, Any]:
    """
    Fetch Azure Advisor Cost category recommendations for the subscription.
    Requires feature 'ai_cost_recommendations' enabled.
    """
    from azure.mgmt.advisor.aio import AdvisorManagementClient
    from azure.core.exceptions import HttpResponseError

    conn = await _require_connection_and_feature("ai_cost_recommendations")
    credential = _build_credential(conn)

    recommendations = []
    try:
        async with credential, AdvisorManagementClient(credential, conn.subscription_id) as client:
            async for rec in client.recommendations.list():
                if rec.category and str(rec.category).lower() == "cost":
                    recommendations.append({
                        "id": rec.id,
                        "name": rec.name,
                        "category": str(rec.category),
                        "impact": str(rec.impact) if rec.impact else None,
                        "short_description": (
                            rec.short_description.problem if rec.short_description else None
                        ),
                        "extended_properties": rec.extended_properties or {},
                    })
    except HttpResponseError as e:
        raise ValueError(f"Advisor recommendations fetch failed: {e.message}")

    await _update_last_synced("ai_cost_recommendations")
    return {
        "subscription_id": conn.subscription_id,
        "recommendations": recommendations,
        "count": len(recommendations),
    }
