"""DokOps Minion Agent — runs on on-premise devices."""
import sys as _sys
from pathlib import Path as _Path
_lib = _Path(__file__).parent / "lib"
if _lib.exists():
    _sys.path.insert(0, str(_lib))

import asyncio
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

try:
    import blueprint as blueprint_engine
except ImportError:
    blueprint_engine = None  # type: ignore[assignment]

IS_WINDOWS = sys.platform == "win32"
CONFIG_FILE = Path(
    r"C:\ProgramData\DokOps\minion\config.env" if IS_WINDOWS
    else "/etc/dokops-minion/config.env"
)
LOG_FORMAT = "%(asctime)s [minion] %(levelname)s %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

def _ensure_deps():
    required = ["websockets", "psutil"]
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[minion] Installing missing dependencies: {missing}")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet"] + missing)
        except Exception as e:
            print(f"[minion] WARNING: could not auto-install {missing}: {e} — continuing without them")

_ensure_deps()
log = logging.getLogger(__name__)


def load_config() -> dict:
    cfg: dict = {}
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                cfg[k.strip()] = v.strip()
    # CLI args override config file
    for arg in sys.argv[1:]:
        if arg.startswith("--"):
            k, _, v = arg[2:].partition("=")
            cfg[k.upper().replace("-", "_")] = v
    return cfg


def _linux_os_id() -> str:
    """Read the distro ID from /etc/os-release (e.g. 'rocky', 'ubuntu', 'rhel')."""
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ID="):
                    return line.split("=", 1)[1].strip().strip('"').lower()
    except Exception:
        pass
    return platform.system().lower()


def collect_grains(org: str = "", env: str = "") -> dict:
    def _cmd(c: str) -> str:
        try:
            return subprocess.check_output(c, shell=True, stderr=subprocess.DEVNULL, text=True, timeout=5).strip().splitlines()[0]
        except Exception:
            return ""

    os_id = "windows" if IS_WINDOWS else _linux_os_id()

    grains: dict = {
        "hostname": platform.node(),
        "os": os_id,
        "arch": platform.machine(),
        "kernel": platform.release(),
        "python": platform.python_version(),
        "docker": _cmd("docker version --format '{{.Server.Version}}'") or None,
        "ansible": _cmd("ansible --version") or None,
        "systemctl": False if IS_WINDOWS else shutil.which("systemctl") is not None,
    }
    if IS_WINDOWS:
        grains["powershell"] = shutil.which("powershell") is not None
        grains["winget"] = shutil.which("winget") is not None
        grains["chocolatey"] = shutil.which("choco") is not None
    if org:
        grains["org"] = org
    if env:
        grains["env"] = env
    return grains


def _collect_patches_wua() -> dict:
    """Try Windows Update Agent COM API. Raises on failure (network blocked etc.)."""
    from datetime import datetime as _dt, timezone as _tz
    _SEV = {"critical": "critical", "important": "high", "moderate": "medium", "low": "low"}
    ps = (
        "$s=New-Object -ComObject Microsoft.Update.Session;"
        "$r=$s.CreateUpdateSearcher().Search('IsInstalled=0 and Type=\\'Software\\'');"
        "$out=@();"
        "foreach($u in $r.Updates){"
        "$sec=($u.Categories|?{$_.Name -match 'Security'}).Count -gt 0;"
        "$sev=if($u.MsrcSeverity){$u.MsrcSeverity.ToLower()}else{'none'};"
        "$out+=[pscustomobject]@{name=$u.Title;installed_version='';available_version=$u.Identity.UpdateID;"
        "advisory_type=if($sec){'security'}else{'enhancement'};severity=$sev;cve_ids=@()}};"
        "if($out.Count){$out|ConvertTo-Json -Compress}else{'[]'}"
    )
    raw = subprocess.check_output(
        ["powershell", "-NonInteractive", "-Command", ps],
        text=True, timeout=120, stderr=subprocess.PIPE
    ).strip()
    data = json.loads(raw or "[]")
    if isinstance(data, dict):
        data = [data]
    packages = []
    for item in data:
        sev_raw = (item.get("severity") or "").lower()
        packages.append({
            "name": item.get("name", ""),
            "installed_version": item.get("installed_version", ""),
            "available_version": item.get("available_version", ""),
            "advisory_type": item.get("advisory_type", "enhancement"),
            "severity": _SEV.get(sev_raw, "none"),
            "cve_ids": [],
        })
    return {
        "package_manager": "wua",
        "packages": packages,
        "scanned_at": _dt.now(_tz.utc).isoformat().replace("+00:00", "Z"),
    }


def collect_patches_windows() -> dict:
    """Try WUA COM first; fall back to winget if WUA is unreachable."""
    try:
        return _collect_patches_wua()
    except Exception:
        pass  # WUA blocked (corporate firewall) — fall through to winget

    from datetime import datetime as _dt, timezone as _tz
    packages = []
    pkg_mgr = "none"

    if shutil.which("winget"):
        pkg_mgr = "winget"
        try:
            raw = subprocess.check_output(
                ["winget", "upgrade", "--include-unknown", "--accept-source-agreements", "--disable-interactivity"],
                stderr=subprocess.DEVNULL, text=True, timeout=120, encoding="utf-8", errors="replace"
            )
            lines = raw.splitlines()
            col_starts: dict = {}
            header_idx = None
            for i, line in enumerate(lines):
                if "Name" in line and "Available" in line and "Version" in line:
                    header_idx = i
                    col_starts["name"] = line.index("Name")
                    col_starts["id"] = line.index("Id") if "Id" in line else len(line)
                    col_starts["version"] = line.index("Version")
                    col_starts["available"] = line.index("Available")
                    break
            if header_idx is not None:
                for line in lines[header_idx + 2:]:
                    if not line.strip() or line.startswith("-") or "upgrades available" in line:
                        continue
                    if len(line) <= col_starts.get("available", 9999):
                        continue
                    try:
                        name = line[col_starts["name"]:col_starts["id"]].strip()
                        version = line[col_starts["version"]:col_starts["available"]].strip()
                        available = line[col_starts["available"]:].split()[0].strip()
                        if name and available and version and available != version:
                            packages.append({
                                "name": name,
                                "installed_version": version,
                                "available_version": available,
                                "advisory_type": "enhancement",
                                "severity": "none",
                                "cve_ids": [],
                            })
                    except Exception:
                        continue
        except Exception:
            pass

    return {
        "package_manager": pkg_mgr,
        "packages": packages,
        "scanned_at": _dt.now(_tz.utc).isoformat().replace("+00:00", "Z"),
    }


def collect_patches() -> dict:
    """Return structured patch data using the local package manager."""
    if IS_WINDOWS:
        return collect_patches_windows()

    import shutil, subprocess, json as _json

    packages = []

    if shutil.which("apt-get"):
        try:
            raw = subprocess.check_output(
                ["apt", "list", "--upgradable"],
                stderr=subprocess.DEVNULL, text=True, timeout=30
            )
        except Exception:
            raw = ""
        for line in raw.splitlines():
            # Format: nginx/focal-security 1.24.0-1 amd64 [upgradable from: 1.18.0-0]
            if "/" not in line or "[upgradable" not in line:
                continue
            try:
                pkg_part, rest = line.split("/", 1)
                pocket = rest.split(" ")[0]  # e.g. focal-security
                avail = rest.split(" ")[1]
                installed = line.split("from: ")[1].rstrip("]")
                advisory_type = "security" if "security" in pocket or "esm" in pocket.lower() else "enhancement"
                packages.append({
                    "name": pkg_part.strip(),
                    "installed_version": installed.strip(),
                    "available_version": avail.strip(),
                    "advisory_type": advisory_type,
                    "severity": "high" if advisory_type == "security" else "none",
                    "cve_ids": [],
                })
            except Exception:
                continue

    elif shutil.which("dnf") or shutil.which("yum"):
        mgr = "dnf" if shutil.which("dnf") else "yum"
        try:
            raw = subprocess.check_output(
                [mgr, "updateinfo", "list", "updates", "--quiet"],
                stderr=subprocess.DEVNULL, text=True, timeout=60
            )
        except Exception:
            raw = ""
        raw_entries: list[dict] = []
        for line in raw.splitlines():
            # Format: RLSA-2026:1234 Important perl-Errno-1.36-497.el9.x86_64
            parts = line.split()
            if len(parts) < 3:
                continue
            advisory_id = parts[0]
            severity_raw = parts[1].lower()
            pkg_full = parts[2]
            pkg_name = pkg_full.rsplit("-", 2)[0] if pkg_full.count("-") >= 2 else pkg_full
            severity = "critical" if "critical" in severity_raw else \
                       "high" if "important" in severity_raw else \
                       "medium" if "moderate" in severity_raw else \
                       "low" if "low" in severity_raw else "none"
            # 3rd character of prefix encodes type: S=Security B=Bugfix E=Enhancement
            # Covers RLSA/RLBA/RLEA (Rocky), RHSA/RHBA/RHEA (RHEL),
            # ALSA/ALBA/ALEA (AlmaLinux), ELSA (Oracle), etc.
            third = advisory_id[2:3].upper() if len(advisory_id) >= 3 else ""
            advisory_type = "security" if third == "S" else \
                            "enhancement" if third == "E" else "bugfix"
            raw_entries.append({
                "name": pkg_name,
                "installed_version": "",
                "available_version": pkg_full,
                "advisory_id": advisory_id,
                "advisory_type": advisory_type,
                "severity": severity,
                "cve_ids": [],
            })

        # Deduplicate by package name: one advisory per package.
        # Keep highest severity; break ties by latest advisory ID (lexicographic).
        _sev_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1, "none": 0}
        best: dict[str, dict] = {}
        for entry in raw_entries:
            name = entry["name"]
            if name not in best:
                best[name] = entry
            else:
                cur = best[name]
                if (_sev_rank.get(entry["severity"], 0), entry["advisory_id"]) > \
                   (_sev_rank.get(cur["severity"], 0), cur["advisory_id"]):
                    best[name] = entry
        packages.extend(best.values())

    from datetime import datetime as _dt, timezone as _tz
    return {
        "package_manager": "apt" if shutil.which("apt-get") else "dnf",
        "packages": packages,
        "scanned_at": _dt.now(_tz.utc).isoformat().replace("+00:00", "Z"),
    }


async def run_job(ws, job_id: str, cmd: str, timeout: int) -> None:
    log.info("Running job %s: %s", job_id, cmd)
    exit_code = 1
    proc = None
    try:
        if IS_WINDOWS:
            proc = await asyncio.create_subprocess_exec(
                "powershell", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                limit=1024 * 1024,
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                limit=1024 * 1024,
            )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                proc.kill()
                exit_code = 124
                break
            try:
                chunk = await asyncio.wait_for(proc.stdout.read(65536), timeout=remaining)
            except asyncio.TimeoutError:
                proc.kill()
                exit_code = 124
                break
            if not chunk:
                break
            await ws.send(json.dumps({"type": "chunk", "job_id": job_id, "data": chunk.decode(errors="replace")}))
        if exit_code != 124:
            await proc.wait()
            exit_code = proc.returncode if proc.returncode is not None else 0
    except Exception as e:
        await ws.send(json.dumps({"type": "chunk", "job_id": job_id, "data": f"ERROR: {e}\n"}))

    await ws.send(json.dumps({"type": "done", "job_id": job_id, "exit_code": exit_code}))

    if proc is not None:
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except asyncio.TimeoutError:
            proc.kill()
    log.info("Job %s cleaned up (exit_code=%s)", job_id, exit_code)


async def handle_messages(ws) -> None:
    """Process inbound messages until the socket closes (extracted for testability)."""
    async for raw in ws:
        msg = json.loads(raw)
        t = msg.get("type")
        if t == "blueprint":
            results = []
            if blueprint_engine is not None:
                try:
                    results = blueprint_engine.run_blueprint(
                        msg.get("resources", []), msg.get("sources", {}), bool(msg.get("test", True))
                    )
                except Exception as e:  # noqa: BLE001 — report compile/order failures upstream
                    results = [{"id": "_compile", "result": False, "changes": {}, "comment": str(e)}]
            await ws.send(json.dumps({"type": "blueprint_result", "run_id": msg.get("run_id"), "results": results}))
        elif t == "welcome":
            log.info("Status: %s", msg.get("status"))
        elif t == "approved":
            log.info("Approved by master — ready for jobs")
        elif t == "job":
            asyncio.ensure_future(run_job(ws, msg["job_id"], msg["cmd"], msg.get("timeout", 60)))
        elif t == "ping":
            await ws.send(json.dumps({"type": "pong"}))
        elif t == "scan_patches":
            async def _rescan():
                pd = collect_patches()
                await ws.send(json.dumps({"type": "patches", "data": pd}))
                del pd
            asyncio.ensure_future(_rescan())

        elif t == "discover_services":
            async def _discover():
                def _run(cmd: str) -> str:
                    try:
                        return subprocess.check_output(
                            cmd, shell=True, stderr=subprocess.DEVNULL,
                            text=True, timeout=15
                        )
                    except Exception:
                        return ""
                if IS_WINDOWS:
                    netstat_out = _run("netstat -ano")
                    services_out = _run(
                        'powershell -Command "Get-Service | Where-Object {$_.Status -eq \'Running\'}'
                        ' | Select-Object -Property Name,DisplayName | ConvertTo-Json -Compress"'
                    )
                    docker_out = _run("docker ps --format '{{json .}}'")
                    await ws.send(json.dumps({
                        "type": "discover_services_result",
                        "platform": "windows",
                        "netstat": netstat_out,
                        "services": services_out,
                        "docker": docker_out,
                    }))
                else:
                    ss_out = _run("ss -tlnp")
                    systemctl_out = _run("systemctl list-units --type=service --state=running --no-pager")
                    docker_out = _run("docker ps --format '{{json .}}'")
                    await ws.send(json.dumps({
                        "type": "discover_services_result",
                        "platform": "linux",
                        "ss": ss_out,
                        "systemctl": systemctl_out,
                        "docker": docker_out,
                    }))
            asyncio.ensure_future(_discover())


async def connect_and_run(url: str, token: Optional[str], org: str = "", env: str = "") -> None:
    import websockets

    ws_url = url
    if token:
        ws_url = f"{url}?token={token}"

    log.info("Connecting to %s", url)
    async with websockets.connect(ws_url, ping_interval=30, ping_timeout=90) as ws:
        log.info("Connected")

        # Send grains on connect
        await ws.send(json.dumps({"type": "grains", "data": collect_grains(org=org, env=env)}))

        # Send initial patch scan
        patch_data = collect_patches()
        await ws.send(json.dumps({"type": "patches", "data": patch_data}))
        del patch_data  # free memory immediately

        # Heartbeat loop
        async def heartbeat():
            while True:
                await asyncio.sleep(30)
                try:
                    import psutil
                    cpu = psutil.cpu_percent(interval=1)
                    mem = psutil.virtual_memory().percent
                    disk = psutil.disk_usage("C:\\" if IS_WINDOWS else "/").percent
                except ImportError:
                    cpu = mem = disk = 0.0
                try:
                    await ws.send(json.dumps({
                        "type": "heartbeat",
                        "cpu_pct": cpu,
                        "mem_pct": mem,
                        "disk_pct": disk,
                        "uptime_s": int(asyncio.get_running_loop().time()),
                    }))
                except Exception:
                    break

        asyncio.ensure_future(heartbeat())

        # Periodic patch scanner (every 6 hours)
        async def patch_scanner():
            while True:
                await asyncio.sleep(6 * 3600)  # 6 hours
                try:
                    pd = collect_patches()
                    await ws.send(json.dumps({"type": "patches", "data": pd}))
                    del pd
                except Exception:
                    break

        asyncio.ensure_future(patch_scanner())

        # Message loop
        await handle_messages(ws)


async def main() -> None:
    cfg = load_config()
    base_url = cfg.get("DOKOPS_URL", "http://localhost:8000").rstrip("/")
    minion_id = cfg.get("MINION_ID")
    token = cfg.get("MINION_TOKEN")
    org = cfg.get("ORG", "")
    env = cfg.get("ENV", "")

    if not minion_id:
        import uuid
        minion_id = str(uuid.uuid4())
        log.info("Generated new MINION_ID: %s", minion_id)
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with CONFIG_FILE.open("a") as f:
            f.write(f"\nMINION_ID={minion_id}\n")

    ws_scheme = "wss" if base_url.startswith("https") else "ws"
    host = base_url.split("://", 1)[1]
    ws_url = f"{ws_scheme}://{host}/api/v1/minions/ws/{minion_id}"

    backoff = 1
    while True:
        try:
            await connect_and_run(ws_url, token, org=org, env=env)
            backoff = 1
        except Exception as e:
            log.warning("Connection lost: %s — retrying in %ss", e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
