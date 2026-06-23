import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_async_db, get_current_user, get_current_active_superuser
from app.models.activation_key import ActivationKey, KeyBlueprint
from app.models.user import User
from app.services.minion_service import hash_token

router = APIRouter()


class KeyIn(BaseModel):
    name: str
    org_id: Optional[str] = None
    group_id: Optional[str] = None
    run_on_attach: bool = False
    enabled: bool = True
    blueprint_ids: list[str] = []


async def _blueprint_ids(key_id: str, db: AsyncSession) -> list[str]:
    rows = (await db.exec(
        select(KeyBlueprint).where(KeyBlueprint.key_id == key_id).order_by(KeyBlueprint.position)
    )).all()
    return [r.blueprint_id for r in rows]


def _public(key: ActivationKey, blueprint_ids: list[str]) -> dict:
    return {
        "id": key.id, "name": key.name, "org_id": key.org_id, "group_id": key.group_id,
        "run_on_attach": key.run_on_attach, "enabled": key.enabled,
        "created_at": key.created_at, "blueprint_ids": blueprint_ids,
    }


async def _set_blueprints(key_id: str, blueprint_ids: list[str], db: AsyncSession) -> None:
    for old in (await db.exec(select(KeyBlueprint).where(KeyBlueprint.key_id == key_id))).all():
        await db.delete(old)
    for i, bid in enumerate(blueprint_ids):
        db.add(KeyBlueprint(key_id=key_id, blueprint_id=bid, position=i))


@router.get("/")
async def list_keys(db: AsyncSession = Depends(get_async_db), _: User = Depends(get_current_user)):
    keys = (await db.exec(select(ActivationKey))).all()
    return [_public(k, await _blueprint_ids(k.id, db)) for k in keys]


@router.post("/")
async def create_key(body: KeyIn, db: AsyncSession = Depends(get_async_db),
                     user: User = Depends(get_current_active_superuser)):
    if (await db.exec(select(ActivationKey).where(ActivationKey.name == body.name))).first():
        raise HTTPException(status_code=409, detail="Key name already exists")
    value = secrets.token_urlsafe(24)
    key = ActivationKey(
        name=body.name, value_hash=hash_token(value), org_id=body.org_id, group_id=body.group_id,
        run_on_attach=body.run_on_attach, enabled=body.enabled, created_by=user.username,
    )
    db.add(key)
    await db.flush()
    await _set_blueprints(key.id, body.blueprint_ids, db)
    await db.commit()
    await db.refresh(key)
    return {"key": _public(key, body.blueprint_ids), "value": value}


@router.get("/{key_id}")
async def get_key(key_id: str, db: AsyncSession = Depends(get_async_db), _: User = Depends(get_current_user)):
    key = await db.get(ActivationKey, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    return _public(key, await _blueprint_ids(key_id, db))


@router.put("/{key_id}")
async def update_key(key_id: str, body: KeyIn, db: AsyncSession = Depends(get_async_db),
                     _: User = Depends(get_current_active_superuser)):
    key = await db.get(ActivationKey, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    key.name = body.name
    key.org_id = body.org_id
    key.group_id = body.group_id
    key.run_on_attach = body.run_on_attach
    key.enabled = body.enabled
    db.add(key)
    await _set_blueprints(key_id, body.blueprint_ids, db)
    await db.commit()
    return _public(key, body.blueprint_ids)


@router.delete("/{key_id}")
async def delete_key(key_id: str, db: AsyncSession = Depends(get_async_db),
                     _: User = Depends(get_current_active_superuser)):
    key = await db.get(ActivationKey, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    for kb in (await db.exec(select(KeyBlueprint).where(KeyBlueprint.key_id == key_id))).all():
        await db.delete(kb)
    await db.delete(key)
    await db.commit()
    return {"deleted": True}
