from __future__ import annotations
from typing import Optional
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.core.encryption import encrypt, decrypt
from app.models.service_diag import ServiceCredential
from app.models.patch import MinionGroupMember


async def create_credential_async(
    db: AsyncSession,
    scope_type: str,
    service_type: str,
    username: str,
    password: str,
    scope_id: Optional[str] = None,
    port: Optional[int] = None,
    extra: str = "{}",
    host: Optional[str] = None,
    instance_name: str = "",
) -> ServiceCredential:
    cred = ServiceCredential(
        scope_type=scope_type,
        scope_id=scope_id,
        service_type=service_type,
        username=encrypt(username or ""),
        password=encrypt(password),
        port=port,
        extra=extra,
        host=host,
        instance_name=instance_name,
    )
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    return cred


def create_credential(
    db: Session,
    scope_type: str,
    service_type: str,
    username: str,
    password: str,
    scope_id: Optional[str] = None,
    port: Optional[int] = None,
    extra: str = "{}",
    host: Optional[str] = None,
    instance_name: str = "",
) -> ServiceCredential:
    cred = ServiceCredential(
        scope_type=scope_type,
        scope_id=scope_id,
        service_type=service_type,
        username=encrypt(username or ""),
        password=encrypt(password),
        port=port,
        extra=extra,
        host=host,
        instance_name=instance_name,
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return cred


def resolve_cluster_credential(
    cluster_id: str,
    service_type: str,
    db: Session,
) -> Optional[dict]:
    """Return decrypted credential dict for the given cluster + service, or None."""
    cred = db.exec(
        select(ServiceCredential).where(
            ServiceCredential.scope_type == "cluster",
            ServiceCredential.scope_id == cluster_id,
            ServiceCredential.service_type == service_type,
        )
    ).first()
    if not cred:
        return None
    return _to_dict(cred)


def resolve_credential(minion_id: str, service_type: str, db: Session) -> Optional[dict]:
    """Return decrypted cred dict or None. Precedence: minion > group > global."""
    cred = db.exec(
        select(ServiceCredential).where(
            ServiceCredential.scope_type == "minion",
            ServiceCredential.scope_id == minion_id,
            ServiceCredential.service_type == service_type,
        )
    ).first()
    if cred:
        return _to_dict(cred)

    memberships = db.exec(
        select(MinionGroupMember).where(MinionGroupMember.minion_id == minion_id)
    ).all()
    for m in memberships:
        cred = db.exec(
            select(ServiceCredential).where(
                ServiceCredential.scope_type == "group",
                ServiceCredential.scope_id == m.group_id,
                ServiceCredential.service_type == service_type,
            )
        ).first()
        if cred:
            return _to_dict(cred)

    cred = db.exec(
        select(ServiceCredential).where(
            ServiceCredential.scope_type == "global",
            ServiceCredential.service_type == service_type,
        )
    ).first()
    return _to_dict(cred) if cred else None


def _to_dict(cred: ServiceCredential) -> dict:
    return {
        "username": decrypt(cred.username) if cred.username else "",
        "password": decrypt(cred.password),
        "host": cred.host or "",
        "port": cred.port,
        "extra": cred.extra,
    }
