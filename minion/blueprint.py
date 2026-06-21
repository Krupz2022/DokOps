"""DokOps minion state handlers — stdlib only, runs on Windows + Linux."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"


def _run(cmd, shell: bool = False) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=300)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:  # noqa: BLE001 — surface failure as nonzero rc
        return 1, str(e)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]


def handle_file(state: dict, sources: dict, test: bool) -> dict:
    path = state["path"]
    name = state.get("source")
    desired = sources.get(name, "")
    if name and name not in sources:
        return {"result": False, "changes": {}, "comment": f"source '{name}' not in bundle"}

    current = None
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                current = f.read()
        except OSError as e:
            return {"result": False, "changes": {}, "comment": f"read failed: {e}"}

    if current == desired:
        return {"result": True, "changes": {}, "comment": "file in desired state"}

    changes = {"old": _sha(current) if current is not None else "absent", "new": _sha(desired)}
    if test:
        return {"result": None, "changes": changes, "comment": "would update file"}

    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(desired)
        if not IS_WINDOWS and state.get("mode"):
            os.chmod(path, int(str(state["mode"]), 8))
    except OSError as e:
        return {"result": False, "changes": {}, "comment": f"write failed: {e}"}
    return {"result": True, "changes": changes, "comment": "file updated"}


def handle_cmd(state: dict, sources: dict, test: bool) -> dict:
    name = state["name"]
    unless = state.get("unless")
    onlyif = state.get("onlyif")

    if unless:
        rc, _ = _run(unless, shell=True)
        if rc == 0:
            return {"result": True, "changes": {}, "comment": "unless satisfied — skipped"}
    if onlyif:
        rc, _ = _run(onlyif, shell=True)
        if rc != 0:
            return {"result": True, "changes": {}, "comment": "onlyif not met — skipped"}

    if test:
        return {"result": None, "changes": {"executed": name}, "comment": "would run command"}

    rc, out = _run(name, shell=True)
    if rc == 0:
        return {"result": True, "changes": {"executed": name}, "comment": out[:500]}
    return {"result": False, "changes": {}, "comment": f"exit {rc}: {out[:500]}"}
