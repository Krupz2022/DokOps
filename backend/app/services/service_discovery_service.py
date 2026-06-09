from __future__ import annotations
import json
import re
from datetime import datetime
from typing import List
from sqlmodel import Session, select
from app.models.service_diag import DiscoveredService
from app.services.probe_registry import (
    PORT_SERVICE_MAP, UNIT_SERVICE_MAP, IMAGE_SERVICE_MAP, DEFAULT_PORTS,
)



DISCOVERY_COMMANDS = {
    "ss": "ss -tlnp",
    "systemctl": "systemctl list-units --type=service --state=running --no-pager",
    "docker": "docker ps --format '{{json .}}'",
}


def parse_discovery_output(
    minion_id: str, ss_output: str, systemctl_output: str, docker_output: str
) -> List[DiscoveredService]:
    """Parse raw command stdout into DiscoveredService objects. Docker wins over native for same service."""
    found: dict[str, DiscoveredService] = {}

    # --- Port scan ---
    for line in ss_output.splitlines():
        m = re.search(r":(\d+)\s", line)
        if m:
            port = int(m.group(1))
            svc = PORT_SERVICE_MAP.get(port)
            if svc and svc not in found:
                found[svc] = DiscoveredService(
                    minion_id=minion_id,
                    service_type=svc,
                    install_type="native",
                    port=port,
                )

    # --- Systemd units ---
    for line in systemctl_output.splitlines():
        for unit_name, svc in UNIT_SERVICE_MAP.items():
            if unit_name in line and svc not in found:
                found[svc] = DiscoveredService(
                    minion_id=minion_id,
                    service_type=svc,
                    install_type="native",
                    port=DEFAULT_PORTS[svc],
                )

    # --- Docker containers (overrides native if same service_type) ---
    for line in docker_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            container = json.loads(line)
        except json.JSONDecodeError:
            continue
        raw_image = container.get("Image", "").lower()
        image = raw_image.split(":")[0].split("/")[-1]
        for img_prefix, svc in IMAGE_SERVICE_MAP.items():
            if image.startswith(img_prefix):
                port = DEFAULT_PORTS[svc]
                pm = re.search(r":(\d+)->", container.get("Ports", ""))
                if pm:
                    port = int(pm.group(1))
                found[svc] = DiscoveredService(
                    minion_id=minion_id,
                    service_type=svc,
                    install_type="docker",
                    container_name=container.get("Names", "").lstrip("/"),
                    port=port,
                )
                break

    return list(found.values())


def parse_discovery_output_windows(
    minion_id: str, netstat_output: str, services_output: str, docker_output: str
) -> List[DiscoveredService]:
    """Parse Windows netstat -ano and Get-Service JSON output into DiscoveredService objects."""
    found: dict[str, DiscoveredService] = {}

    # --- netstat -ano LISTENING ports ---
    for line in netstat_output.splitlines():
        parts = line.split()
        # Format: TCP    0.0.0.0:5672    0.0.0.0:0    LISTENING    1234
        if len(parts) >= 4 and "LISTENING" in parts:
            addr = parts[1]
            try:
                port = int(addr.rsplit(":", 1)[-1])
                svc = PORT_SERVICE_MAP.get(port)
                if svc and svc not in found:
                    found[svc] = DiscoveredService(
                        minion_id=minion_id,
                        service_type=svc,
                        install_type="native",
                        port=port,
                    )
            except (ValueError, IndexError):
                continue

    # --- Get-Service JSON ---
    try:
        raw = services_output.strip()
        if raw:
            svc_list = json.loads(raw)
            if isinstance(svc_list, dict):
                svc_list = [svc_list]
            for entry in svc_list:
                name = (entry.get("Name") or "").lower()
                for unit_name, svc_type in UNIT_SERVICE_MAP.items():
                    if unit_name in name and svc_type not in found:
                        found[svc_type] = DiscoveredService(
                            minion_id=minion_id,
                            service_type=svc_type,
                            install_type="native",
                            port=DEFAULT_PORTS[svc_type],
                        )
    except (json.JSONDecodeError, Exception):
        pass

    # --- Docker containers (same as Linux) ---
    for line in docker_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            container = json.loads(line)
        except json.JSONDecodeError:
            continue
        raw_image = container.get("Image", "").lower()
        image = raw_image.split(":")[0].split("/")[-1]
        for img_prefix, svc in IMAGE_SERVICE_MAP.items():
            if image.startswith(img_prefix):
                port = DEFAULT_PORTS[svc]
                pm = re.search(r":(\d+)->", container.get("Ports", ""))
                if pm:
                    port = int(pm.group(1))
                found[svc] = DiscoveredService(
                    minion_id=minion_id,
                    service_type=svc,
                    install_type="docker",
                    container_name=container.get("Names", "").lstrip("/"),
                    port=port,
                )
                break

    return list(found.values())


def persist_discovery(minion_id: str, services: List[DiscoveredService], db: Session) -> None:
    """Replace auto-detected rows for this minion. Rows with overridden=True are untouched."""
    existing = db.exec(
        select(DiscoveredService).where(
            DiscoveredService.minion_id == minion_id,
            DiscoveredService.overridden == False,  # noqa: E712
        )
    ).all()
    for row in existing:
        db.delete(row)

    now = datetime.utcnow()
    for svc in services:
        svc.detected_at = now
        db.add(svc)

    db.commit()
