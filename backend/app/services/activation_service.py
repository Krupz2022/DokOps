import uuid
from datetime import datetime

import httpx
from sqlmodel import Session, select

from app.core.license_constants import ACTIVATION_ENABLED, LICENSE_SERVER_URL
from app.core.db import engine
from app.models.activation import Activation


async def activate_key(license_key: str, db: Session) -> dict:
    if not ACTIVATION_ENABLED:
        return {"success": True, "message": "Activation not required"}

    existing = db.exec(select(Activation)).first()
    instance_id = existing.instance_id if existing else str(uuid.uuid4())

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{LICENSE_SERVER_URL}/validate",
                json={"key": license_key, "instance_id": instance_id},
            )
            data = resp.json()
    except Exception:
        return {"success": False, "message": "Could not reach license server"}

    if not data.get("valid"):
        return {"success": False, "message": data.get("message", "Invalid license key")}

    now = datetime.utcnow()
    if existing:
        existing.license_key = license_key
        existing.instance_id = instance_id
        existing.is_active = True
        existing.last_heartbeat_at = now
        db.add(existing)
    else:
        db.add(Activation(
            license_key=license_key,
            instance_id=instance_id,
            activated_at=now,
            last_heartbeat_at=now,
            is_active=True,
        ))
    db.commit()
    return {"success": True, "message": "Activated successfully"}


def get_status(db: Session) -> dict:
    if not ACTIVATION_ENABLED:
        return {"activation_required": False, "activated": True}

    row = db.exec(select(Activation)).first()
    if not row:
        return {"activation_required": True, "activated": False, "last_heartbeat": None}
    return {
        "activation_required": True,
        "activated": row.is_active,
        "activated_at": row.activated_at.isoformat() if row.activated_at else None,
        "last_heartbeat": row.last_heartbeat_at.isoformat() if row.last_heartbeat_at else None,
    }


async def run_heartbeat() -> None:
    if not ACTIVATION_ENABLED:
        return

    with Session(engine) as db:
        row = db.exec(select(Activation)).first()
        if not row or not row.is_active:
            return

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{LICENSE_SERVER_URL}/heartbeat",
                    json={"key": row.license_key, "instance_id": row.instance_id},
                )
                data = resp.json()
            row.is_active = data.get("valid", False)
        except Exception:
            pass  # network blip — keep current state, retry next cycle

        row.last_heartbeat_at = datetime.utcnow()
        db.add(row)
        db.commit()


async def heartbeat_loop() -> None:
    import asyncio
    while True:
        await asyncio.sleep(12 * 3600)  # 12 hours
        await run_heartbeat()
