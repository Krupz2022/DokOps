"""Live (non-persisted) minion resource helpers: Portainer config + proxy, system services."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Optional

import httpx

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


async def fetch_docker_resources(base_url: str, api_key: str, endpoint_id: int) -> dict:
    base = f"{base_url.rstrip('/')}/api/endpoints/{endpoint_id}/docker"
    headers = {"X-API-Key": api_key}
    paths = {
        "containers": "/containers/json?all=1",
        "images": "/images/json",
        "volumes": "/volumes",
        "networks": "/networks",
    }
    # verify=False: Portainer commonly uses a self-signed cert on :9443.
    # ponytail: trust on first use is acceptable for an operator-entered host; add a
    # verify toggle to the config if a customer needs strict TLS.
    async with httpx.AsyncClient(verify=False, timeout=15) as cx:
        async def _get(path: str) -> list | dict:
            resp = await cx.get(base + path, headers=headers)
            resp.raise_for_status()
            return resp.json()
        containers, images, volumes, networks = await asyncio.gather(
            _get(paths["containers"]), _get(paths["images"]),
            _get(paths["volumes"]), _get(paths["networks"]),
        )
    return {"containers": containers, "images": images, "volumes": volumes, "networks": networks}


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


def parse_services(os_id: str, stdout: str) -> list[dict[str, str]]:
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


# Service names are interpolated into a shell/PowerShell command, so they MUST match this
# strict charset (no shell metacharacters) before being passed to service_logs_command().
# Covers Linux unit names (incl. template units like "getty@tty1") and Windows service names.
_SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_.@:-]{1,128}$")


def valid_service_name(name: str) -> bool:
    return bool(_SERVICE_NAME_RE.match(name or ""))


# Combined Docker CLI query (works in bash and PowerShell). Each docker sub-command emits
# one JSON object per line; the @@MARKERS@@ split the four resource types apart.
_DOCKER_CLI_CMD = (
    "docker ps -a --format '{{json .}}'; echo '@@IMAGES@@'; "
    "docker images --format '{{json .}}'; echo '@@VOLUMES@@'; "
    "docker volume ls --format '{{json .}}'; echo '@@NETWORKS@@'; "
    "docker network ls --format '{{json .}}'"
)


def docker_cli_command() -> str:
    return _DOCKER_CLI_CMD


def _json_lines(block: str) -> list[dict]:
    out: list[dict] = []
    for line in (block or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def parse_docker_cli(stdout: str) -> dict:
    """Map `docker ... --format '{{json .}}'` CLI output into the same shape the Portainer
    proxy returns, so the frontend renders both identically."""
    c, _, after = (stdout or "").partition("@@IMAGES@@")
    i, _, after2 = after.partition("@@VOLUMES@@")
    v, _, n = after2.partition("@@NETWORKS@@")
    containers = [
        {
            "Id": d.get("ID", ""),
            "Names": ["/" + d.get("Names", "")] if d.get("Names") else [],
            "Image": d.get("Image", ""),
            "State": d.get("State", ""),
            "Status": d.get("Status", ""),
        }
        for d in _json_lines(c)
    ]
    images = [
        {
            "Id": d.get("ID", ""),
            "RepoTags": [f"{d.get('Repository', '')}:{d.get('Tag', '')}"] if d.get("Repository") and d.get("Repository") != "<none>" else [],
        }
        for d in _json_lines(i)
    ]
    volumes = {"Volumes": [{"Name": d.get("Name", ""), "Driver": d.get("Driver", "")} for d in _json_lines(v)]}
    networks = [
        {"Id": d.get("ID", ""), "Name": d.get("Name", ""), "Driver": d.get("Driver", "")}
        for d in _json_lines(n)
    ]
    return {"containers": containers, "images": images, "volumes": volumes, "networks": networks}


def container_logs_command(name: str) -> str:
    """`docker logs` for one container (id or name). Caller MUST validate `name` with
    valid_service_name() first — it is interpolated. Cross-platform (docker CLI)."""
    return f"docker logs --tail 200 --timestamps {name} 2>&1"


def service_logs_command(os_id: str, name: str) -> str:
    """Build a per-OS status+logs command for a single service.
    Caller MUST validate `name` with valid_service_name() first — it is interpolated."""
    if (os_id or "").lower() == "windows":
        return (
            f"Get-Service -Name '{name}' | Format-List Name,DisplayName,Status,StartType; "
            "Write-Output '===== recent Service Control Manager events ====='; "
            "Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Service Control Manager'} "
            f"-MaxEvents 50 -ErrorAction SilentlyContinue | Where-Object {{$_.Message -like '*{name}*'}} "
            "| Format-List TimeCreated,Id,LevelDisplayName,Message"
        )
    return (
        f"systemctl status {name} --no-pager; "
        "echo; echo '===== recent logs ====='; "
        f"journalctl -u {name} --no-pager -n 200 2>&1"
    )
