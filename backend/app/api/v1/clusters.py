# backend/app/api/v1/clusters.py
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api import deps
from app.core.db import engine
from app.core.encryption import decrypt
from app.models.cluster import CloudCredential, ClusterConnection
from app.models.user import User
from app.services.cluster_service import (
    ConnectTokenRequest,
    connect_from_kubeconfig,
    discover_aks_clusters,
    discover_eks_clusters,
    import_aks_cluster,
    import_eks_cluster,
    save_cloud_credential,
    verify_token_connection,
)
from app.services.k8s_service import k8s_service

router = APIRouter()

_MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "../../static/dokops-agent.yaml")


# ── Response models ──────────────────────────────────────────────────────────

class ClusterOut(BaseModel):
    id: str
    name: str
    provider: str
    api_server: str
    namespace: str
    added_by: Optional[str]
    created_at: datetime
    last_verified: Optional[datetime]


class CredentialOut(BaseModel):
    id: str
    provider: str
    added_by: Optional[str]
    created_at: datetime


# ── Request models ────────────────────────────────────────────────────────────

class TokenConnectRequest(BaseModel):
    name: str
    api_server: str
    token: str
    provider: str = "generic"
    ca_cert: Optional[str] = None
    namespace: str = "default"


class AzureCredentialRequest(BaseModel):
    subscription_id: str
    tenant_id: str
    client_id: str
    client_secret: str


class AwsCredentialRequest(BaseModel):
    access_key_id: str
    secret_access_key: str
    region: str = "us-east-1"


class ImportAksRequest(BaseModel):
    cluster_name: str
    resource_group: str


class ImportEksRequest(BaseModel):
    cluster_name: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[ClusterOut])
def list_clusters(current_user: User = Depends(deps.get_current_user)) -> List[ClusterOut]:
    with Session(engine) as db:
        rows = db.exec(select(ClusterConnection)).all()
    result = [ClusterOut(**row.model_dump()) for row in rows]

    # Surface local kubeconfig contexts: prefer clients dict, fall back to default_context
    from app.services.k8s_service import k8s_service
    db_names = {r.name for r in result}
    now = datetime.now(timezone.utc)
    local_ctx_names: set[str] = set(k8s_service.clients.keys())
    if not k8s_service.mock_mode and k8s_service.default_context:
        local_ctx_names.add(k8s_service.default_context)
    for ctx_name in local_ctx_names:
        if ctx_name not in db_names:
            result.append(ClusterOut(
                id=f"local-{ctx_name}",
                name=ctx_name,
                provider="local",
                api_server="(local kubeconfig)",
                namespace="default",
                added_by=None,
                created_at=now,
                last_verified=None,
            ))

    return result


@router.get("/manifest")
def get_manifest(current_user: User = Depends(deps.get_current_user)) -> FileResponse:
    path = os.path.abspath(_MANIFEST_PATH)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Manifest not found")
    return FileResponse(path, media_type="application/x-yaml", filename="dokops-agent.yaml")


@router.post("/upload/kubeconfig", response_model=ClusterOut)
async def upload_kubeconfig(
    file: UploadFile = File(...),
    current_user: User = Depends(deps.get_current_user),
) -> ClusterOut:
    content = await file.read()
    try:
        conn = await connect_from_kubeconfig(content, added_by=current_user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ClusterOut(**conn.model_dump())


@router.post("/connect/token", response_model=ClusterOut)
async def connect_token(
    body: TokenConnectRequest,
    current_user: User = Depends(deps.get_current_user),
) -> ClusterOut:
    from app.core.config import settings

    req = ConnectTokenRequest(
        name=body.name,
        api_server=body.api_server,
        token=body.token,
        provider=body.provider,
        ca_cert=body.ca_cert,
        namespace=body.namespace,
    )
    try:
        conn = await verify_token_connection(
            req,
            allow_private=settings.ALLOW_PRIVATE_CLUSTER_IPS,
            added_by=current_user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ClusterOut(**conn.model_dump())


@router.get("/{cluster_id}/verify", response_model=ClusterOut)
async def verify_cluster(
    cluster_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> ClusterOut:
    with Session(engine) as db:
        conn = db.get(ClusterConnection, cluster_id)
        if not conn:
            raise HTTPException(status_code=404, detail="Cluster not found")
        api_server = conn.api_server
        encrypted_token = conn.token
        ca_cert = conn.ca_cert
        client_cert_data = conn.client_cert_data
        client_key_data = decrypt(conn.client_key_data) if conn.client_key_data else None

    from app.services.cluster_service import _test_k8s_connectivity

    try:
        await _test_k8s_connectivity(
            api_server, decrypt(encrypted_token), ca_cert,
            client_cert_data=client_cert_data,
            client_key_data=client_key_data,
        )
        with Session(engine) as db:
            conn = db.get(ClusterConnection, cluster_id)
            conn.last_verified = datetime.now(timezone.utc)
            db.add(conn)
            db.commit()
            db.refresh(conn)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ClusterOut(**conn.model_dump())


def _delete_cluster_credentials(cluster_id: str, db: Session) -> None:
    """Remove all vault credentials scoped to this cluster before deletion."""
    from sqlmodel import select
    from app.models.service_diag import ServiceCredential
    creds = db.exec(
        select(ServiceCredential).where(
            ServiceCredential.scope_type == "cluster",
            ServiceCredential.scope_id == cluster_id,
        )
    ).all()
    for cred in creds:
        db.delete(cred)
    db.commit()


@router.delete("/{cluster_id}")
async def delete_cluster(
    cluster_id: str,
    current_user: User = Depends(deps.require_god_mode),
) -> Dict[str, str]:
    with Session(engine) as db:
        conn = db.get(ClusterConnection, cluster_id)
        if not conn:
            raise HTTPException(status_code=404, detail="Cluster not found")
        cluster_name = conn.name
        _delete_cluster_credentials(cluster_id, db)
        db.delete(conn)
        db.commit()
    await k8s_service.remove_connection(cluster_name)
    return {"message": f"Cluster '{cluster_name}' removed"}


# ── Cloud credentials ────────────────────────────────────────────────────────

@router.post("/cloud/credentials/azure", response_model=CredentialOut)
def save_azure_credential(
    body: AzureCredentialRequest,
    current_user: User = Depends(deps.get_current_user),
) -> CredentialOut:
    blob = {
        "subscription_id": body.subscription_id,
        "tenant_id": body.tenant_id,
        "client_id": body.client_id,
        "client_secret": body.client_secret,
    }
    cred = save_cloud_credential("aks", blob, added_by=current_user.username)
    return CredentialOut(**cred.model_dump())


@router.post("/cloud/credentials/aws", response_model=CredentialOut)
def save_aws_credential(
    body: AwsCredentialRequest,
    current_user: User = Depends(deps.get_current_user),
) -> CredentialOut:
    blob = {
        "access_key_id": body.access_key_id,
        "secret_access_key": body.secret_access_key,
        "region": body.region,
    }
    cred = save_cloud_credential("eks", blob, added_by=current_user.username)
    return CredentialOut(**cred.model_dump())


@router.get("/cloud/{credential_id}/discover")
async def discover_clusters(
    credential_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> List[Dict[str, Any]]:
    with Session(engine) as db:
        cred = db.get(CloudCredential, credential_id)
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    try:
        if cred.provider == "aks":
            return await discover_aks_clusters(credential_id)
        elif cred.provider == "eks":
            return await discover_eks_clusters(credential_id)
        else:
            raise HTTPException(
                status_code=400, detail=f"Discovery not supported for provider: {cred.provider}"
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/cloud/{credential_id}/import/aks", response_model=ClusterOut)
async def import_aks(
    credential_id: str,
    body: ImportAksRequest,
    current_user: User = Depends(deps.get_current_user),
) -> ClusterOut:
    try:
        conn = await import_aks_cluster(
            credential_id, body.cluster_name, body.resource_group, added_by=current_user.username
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ClusterOut(**conn.model_dump())


@router.post("/cloud/{credential_id}/import/eks", response_model=ClusterOut)
async def import_eks(
    credential_id: str,
    body: ImportEksRequest,
    current_user: User = Depends(deps.get_current_user),
) -> ClusterOut:
    try:
        conn = await import_eks_cluster(
            credential_id, body.cluster_name, added_by=current_user.username
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ClusterOut(**conn.model_dump())
