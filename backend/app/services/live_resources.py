"""Live (non-persisted) minion resource helpers: Portainer config + proxy, system services."""
from __future__ import annotations

import json
from typing import Optional

from sqlmodel import select

from app.models.setting import SystemSetting


def portainer_setting_key(minion_id: str) -> str:
    return f"portainer:{minion_id}"


async def get_portainer_config(minion_id: str, db) -> Optional[dict]:
    row = (await db.exec(
        select(SystemSetting).where(SystemSetting.key == portainer_setting_key(minion_id))
    )).first()
    if not row or not row.value:
        return None
    try:
        cfg = json.loads(row.value)
    except (ValueError, TypeError):
        return None
    return cfg


async def set_portainer_config(minion_id: str, cfg: dict, db) -> None:
    key = portainer_setting_key(minion_id)
    row = (await db.exec(select(SystemSetting).where(SystemSetting.key == key))).first()
    value = json.dumps({
        "base_url": cfg["base_url"].rstrip("/"),
        "api_key": cfg["api_key"],
        "endpoint_id": int(cfg["endpoint_id"]),
    })
    if row:
        row.value = value
    else:
        row = SystemSetting(key=key, value=value)
    db.add(row)
    await db.commit()
