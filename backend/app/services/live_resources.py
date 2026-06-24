"""Live (non-persisted) minion resource helpers: Portainer config + proxy, system services."""
from __future__ import annotations

import json
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.setting import SystemSetting


def portainer_setting_key(minion_id: str) -> str:
    return f"portainer:{minion_id}"


async def get_portainer_config(minion_id: str, db: AsyncSession) -> Optional[dict]:
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


async def set_portainer_config(minion_id: str, cfg: dict, db: AsyncSession) -> None:
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


_WINDOWS_SERVICES_CMD = (
    "Get-Service | Where-Object {$_.Status -eq 'Running'} | "
    "Select-Object Name,DisplayName,@{N='Status';E={$_.Status.ToString()}} | "
    "ConvertTo-Json -Compress"
)
_LINUX_SERVICES_CMD = (
    "systemctl list-units --type=service --state=running --no-pager --no-legend"
)


def services_command(os_id: str) -> str:
    return _WINDOWS_SERVICES_CMD if (os_id or "").lower() == "windows" else _LINUX_SERVICES_CMD


def parse_services(os_id: str, stdout: str) -> list[dict]:
    if (os_id or "").lower() == "windows":
        try:
            data = json.loads(stdout or "[]")
        except (ValueError, TypeError):
            return []
        if isinstance(data, dict):  # single service → not a list
            data = [data]
        out = []
        for item in data:
            out.append({
                "name": item.get("Name", ""),
                "display_name": item.get("DisplayName", ""),
                "status": str(item.get("Status", "")),
            })
        return out

    # Linux systemctl: "ssh.service loaded active running <description...>"
    out = []
    for line in (stdout or "").splitlines():
        parts = line.split(maxsplit=4)
        if len(parts) < 4 or not parts[0].endswith(".service"):
            continue
        out.append({
            "name": parts[0][: -len(".service")],
            "display_name": parts[4] if len(parts) == 5 else "",
            "status": parts[3],
        })
    return out
