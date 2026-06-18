from __future__ import annotations
from datetime import datetime
from typing import Optional

from app.core.datetimes import utcnow
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_user, get_async_db, require_god_mode
from app.core.encryption import decrypt, encrypt
from app.models.service_diag import ServiceCredential
from app.models.user import User
from app.services.service_credential_service import create_credential_async

router = APIRouter()

VALID_SCOPES = ("global", "group", "minion", "cluster")


class CredentialCreate(BaseModel):
    scope_type: str
    scope_id: Optional[str] = None
    service_type: str
    instance_name: Optional[str] = ""
    username: Optional[str] = ""
    password: str
    port: Optional[int] = None
    host: Optional[str] = None
    extra: Optional[str] = "{}"


class CredentialRead(BaseModel):
    id: str
    scope_type: str
    scope_id: Optional[str]
    service_type: str
    instance_name: str
    username: str
    host: Optional[str]
    port: Optional[int]
    extra: str
    created_at: datetime
    updated_at: datetime


def _to_read(cred: ServiceCredential) -> CredentialRead:
    raw_username = decrypt(cred.username) if cred.username else ""
    masked_username = (raw_username[:1] + "***") if raw_username else ""
    return CredentialRead(
        id=cred.id,
        scope_type=cred.scope_type,
        scope_id=cred.scope_id,
        service_type=cred.service_type,
        instance_name=cred.instance_name or "",
        username=masked_username,
        host=cred.host,
        port=cred.port,
        extra="",  # never expose extra in list responses
        created_at=cred.created_at,
        updated_at=cred.updated_at,
    )


@router.get("/", response_model=list[CredentialRead])
async def list_credentials(
    scope_type: Optional[str] = None,
    scope_id: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    query = select(ServiceCredential)
    if scope_type:
        query = query.where(ServiceCredential.scope_type == scope_type)
    if scope_id:
        query = query.where(ServiceCredential.scope_id == scope_id)
    return [_to_read(c) for c in (await db.exec(query)).all()]


@router.post("/", response_model=CredentialRead, status_code=201)
async def add_credential(
    body: CredentialCreate,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(require_god_mode),
):
    if body.scope_type not in VALID_SCOPES:
        raise HTTPException(status_code=422, detail=f"scope_type must be one of {VALID_SCOPES}")
    if body.scope_type != "global" and not body.scope_id:
        raise HTTPException(status_code=422, detail="scope_id is required for non-global scopes")
    cred = await create_credential_async(
        db,
        scope_type=body.scope_type,
        service_type=body.service_type,
        username=body.username,
        password=body.password,
        scope_id=body.scope_id,
        port=body.port,
        host=body.host,
        extra=body.extra or "{}",
        instance_name=body.instance_name or "",
    )
    return _to_read(cred)


# IMPORTANT: /resolve/{minion_id}/{service_type} MUST be defined BEFORE /{cred_id}
# to prevent FastAPI from treating "resolve" as a cred_id path parameter.

@router.get("/resolve/{minion_id}/{service_type}")
async def resolve_preview(
    minion_id: str,
    service_type: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    """Returns which scope level would be used. Never returns the password."""
    from app.models.patch import MinionGroupMember

    if (await db.exec(
        select(ServiceCredential).where(
            ServiceCredential.scope_type == "minion",
            ServiceCredential.scope_id == minion_id,
            ServiceCredential.service_type == service_type,
        )
    )).first():
        return {"resolved": True, "scope_type": "minion"}

    memberships = (await db.exec(
        select(MinionGroupMember).where(MinionGroupMember.minion_id == minion_id)
    )).all()
    for m in memberships:
        if (await db.exec(
            select(ServiceCredential).where(
                ServiceCredential.scope_type == "group",
                ServiceCredential.scope_id == m.group_id,
                ServiceCredential.service_type == service_type,
            )
        )).first():
            return {"resolved": True, "scope_type": "group"}

    if (await db.exec(
        select(ServiceCredential).where(
            ServiceCredential.scope_type == "global",
            ServiceCredential.service_type == service_type,
        )
    )).first():
        return {"resolved": True, "scope_type": "global"}

    return {"resolved": False, "scope_type": None}


@router.put("/{cred_id}", response_model=CredentialRead)
async def update_credential(
    cred_id: str,
    body: CredentialCreate,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(require_god_mode),
):
    cred = await db.get(ServiceCredential, cred_id)
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    if body.scope_type not in VALID_SCOPES:
        raise HTTPException(status_code=422, detail=f"scope_type must be one of {VALID_SCOPES}")
    if body.scope_type != "global" and not body.scope_id:
        raise HTTPException(status_code=422, detail="scope_id is required for non-global scopes")
    cred.scope_type = body.scope_type
    cred.scope_id = body.scope_id
    cred.service_type = body.service_type
    cred.instance_name = body.instance_name or ""
    cred.username = encrypt(body.username or "")
    cred.password = encrypt(body.password)
    cred.port = body.port
    cred.host = body.host
    cred.extra = body.extra or "{}"
    cred.updated_at = utcnow()
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    return _to_read(cred)


@router.delete("/{cred_id}")
async def delete_credential(
    cred_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(require_god_mode),
):
    cred = await db.get(ServiceCredential, cred_id)
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    await db.delete(cred)
    await db.commit()
    return {"deleted": True}
