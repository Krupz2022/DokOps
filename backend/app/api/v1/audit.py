from typing import Any, List, Optional
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select, desc
from app.api import deps
from app.models.audit import AuditLog
from app.models.user import User

router = APIRouter()

@router.get("/", response_model=List[AuditLog])
def read_audit_logs(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    source: Optional[str] = Query(default=None, description="Filter by source: SYSTEM, K8S, AZURE"),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    query = select(AuditLog).order_by(desc(AuditLog.timestamp)).offset(skip).limit(limit)
    if source:
        query = select(AuditLog).where(AuditLog.source == source).order_by(desc(AuditLog.timestamp)).offset(skip).limit(limit)
    return db.exec(query).all()
