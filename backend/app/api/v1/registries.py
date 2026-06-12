# backend/app/api/v1/registries.py
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import deps
from app.core import db as _db
from app.core.encryption import decrypt, encrypt
from app.core.settings_cache import invalidate as _invalidate_settings_cache
from app.models.registry import RegistryConnection
from app.models.setting import SystemSetting
from app.services.registry_service import registry_service

router = APIRouter()


class RegistryIn(BaseModel):
    name: str
    url: str
    username: Optional[str] = None
    password: Optional[str] = None


class RegistryOut(BaseModel):
    id: str
    name: str
    url: str
    username: Optional[str] = None
    added_by: Optional[str] = None
    created_at: datetime


class RegistrySettings(BaseModel):
    enabled: bool


def _to_out(r: RegistryConnection) -> RegistryOut:
    return RegistryOut(
        id=r.id,
        name=r.name,
        url=r.url,
        username=r.username,
        added_by=r.added_by,
        created_at=r.created_at,
    )


@router.get("/", response_model=List[RegistryOut])
async def list_registries(_user=Depends(deps.get_current_user)):
    async with _db.AsyncSessionLocal() as db:
        rows = (await db.exec(select(RegistryConnection))).all()
    return [_to_out(r) for r in rows]


@router.post("/", response_model=RegistryOut)
async def add_registry(req: RegistryIn, user=Depends(deps.get_current_user)):
    encrypted_pw = encrypt(req.password) if req.password else None
    row = RegistryConnection(
        name=req.name,
        url=req.url.rstrip("/"),
        username=req.username or None,
        password=encrypted_pw,
        added_by=user.username,
    )
    async with _db.AsyncSessionLocal() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return _to_out(row)


# Settings routes must be defined BEFORE /{registry_id} to avoid FastAPI
# matching the literal string "settings" as a registry_id path parameter.
@router.get("/settings", response_model=RegistrySettings)
async def get_settings(_user=Depends(deps.get_current_user)):
    async with _db.AsyncSessionLocal() as db:
        row = await db.get(SystemSetting, "registry_lookup_enabled")
    enabled = row is not None and row.value.lower() == "true"
    return RegistrySettings(enabled=enabled)


@router.post("/settings", response_model=RegistrySettings)
async def update_settings(body: RegistrySettings, _user=Depends(deps.get_current_user)):
    value = "true" if body.enabled else "false"
    async with _db.AsyncSessionLocal() as db:
        row = await db.get(SystemSetting, "registry_lookup_enabled")
        if row:
            row.value = value
            db.add(row)
        else:
            db.add(SystemSetting(key="registry_lookup_enabled", value=value))
        await db.commit()
        _invalidate_settings_cache()
    return RegistrySettings(enabled=body.enabled)


@router.get("/{registry_id}/catalog")
async def list_catalog(registry_id: str, _user=Depends(deps.get_current_user)):
    """List all repositories in a connected registry."""
    repos, message = await registry_service.list_catalog(registry_id)
    return {"repositories": repos, "count": len(repos), "message": message}


class CheckImageRequest(BaseModel):
    image: str  # e.g. "myapp:v1.2.3" or "myapp"


@router.post("/{registry_id}/check-image")
async def check_image(
    registry_id: str, body: CheckImageRequest, _user=Depends(deps.get_current_user)
):
    """Check whether a specific image (and tag) exists in the registry."""
    result = await registry_service.check_image(registry_id, body.image)
    return result


@router.delete("/{registry_id}")
async def delete_registry(registry_id: str, _user=Depends(deps.get_current_user)):
    async with _db.AsyncSessionLocal() as db:
        row = await db.get(RegistryConnection, registry_id)
        if not row:
            raise HTTPException(status_code=404, detail="Registry not found")
        await db.delete(row)
        await db.commit()
    return {"deleted": True}


@router.post("/{registry_id}/test")
async def test_registry(registry_id: str, _user=Depends(deps.get_current_user)):
    async with _db.AsyncSessionLocal() as db:
        row = await db.get(RegistryConnection, registry_id)
        if not row:
            raise HTTPException(status_code=404, detail="Registry not found")
        url = row.url
        username = row.username
        pw_plain: Optional[str] = None
        if row.password:
            try:
                pw_plain = decrypt(row.password)
            except Exception:
                raise HTTPException(status_code=500, detail="Failed to decrypt stored credentials")

    auth = (username, pw_plain) if username and pw_plain else None
    test_url = f"https://{url}/v2/"
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(test_url, auth=auth)
        # 200 = anonymous access OK; 401 = auth required but registry is reachable
        ok = resp.status_code in (200, 401)
        msg = "Reachable" if ok else f"Unexpected HTTP {resp.status_code}"
        return {"ok": ok, "status_code": resp.status_code, "message": msg}
    except Exception as e:
        return {"ok": False, "status_code": None, "message": str(e)}
