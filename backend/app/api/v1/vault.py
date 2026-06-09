from __future__ import annotations
from typing import Any, List
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api import deps
from app.models.cluster import ClusterConnection
from app.models.service_diag import ServiceCredential
from app.models.user import User

router = APIRouter()

SUPPORTED_SERVICES = ["rabbitmq", "redis", "couchdb", "mongodb", "mysql", "postgres"]


def get_vault_coverage(db: Session) -> List[dict]:
    """Return credential coverage per cluster."""
    clusters = db.exec(select(ClusterConnection)).all()
    creds = db.exec(
        select(ServiceCredential).where(ServiceCredential.scope_type == "cluster")
    ).all()

    creds_by_cluster: dict[str, list[str]] = {}
    for cred in creds:
        creds_by_cluster.setdefault(cred.scope_id, []).append(cred.service_type)

    return [
        {
            "cluster_id": cluster.id,
            "cluster_name": cluster.name,
            "provider": cluster.provider,
            "configured": creds_by_cluster.get(cluster.id, []),
            "total_services": len(SUPPORTED_SERVICES),
        }
        for cluster in clusters
    ]


@router.get("/coverage")
def vault_coverage(
    db: Session = Depends(deps.get_db),
    _: User = Depends(deps.get_current_user),
) -> Any:
    return get_vault_coverage(db)
