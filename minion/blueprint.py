"""DokOps minion state handlers — stdlib only, runs on Windows + Linux."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"

import contextvars

_emit_var: "contextvars.ContextVar" = contextvars.ContextVar("bp_emit", default=None)
_rid_var: "contextvars.ContextVar" = contextvars.ContextVar("bp_rid", default=None)


def _run(cmd, shell: bool = False) -> tuple[int, str]:
    emit = _emit_var.get()
    if emit is None:
        try:
            p = subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=300)
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except Exception as e:  # noqa: BLE001 — surface failure as nonzero rc
            return 1, str(e)
    # streaming path: read line-by-line and emit log events as they arrive
    rid = _rid_var.get()
    lines: list[str] = []
    try:
        p = subprocess.Popen(
            cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
    except Exception as e:  # noqa: BLE001
        emit({"kind": "log", "id": rid, "line": str(e)})
        return 1, str(e)
    assert p.stdout is not None
    for raw in p.stdout:
        line = raw.rstrip("\n")
        lines.append(line)
        emit({"kind": "log", "id": rid, "line": line})
    p.wait()
    return (p.returncode or 0), "\n".join(lines)


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
        return {"result": True, "changes": {"executed": name}, "comment": "command ran", "output": out}
    return {"result": False, "changes": {}, "comment": f"exit {rc}", "output": out}


# ── package helpers (split out so tests can monkeypatch) ──────────────────────
def _pkg_manager() -> str:
    if IS_WINDOWS:
        return "winget" if shutil.which("winget") else ("choco" if shutil.which("choco") else "none")
    if shutil.which("apt-get"):
        return "dpkg"
    if shutil.which("dnf") or shutil.which("yum"):
        return "rpm"
    return "none"


def _pkg_installed(name: str) -> bool:
    mgr = _pkg_manager()
    if mgr == "dpkg":
        rc, _ = _run(["dpkg", "-s", name])
    elif mgr == "rpm":
        rc, _ = _run(["rpm", "-q", name])
    elif mgr == "winget":
        rc, out = _run(["winget", "list", "--id", name, "--exact"])
        return rc == 0 and name.lower() in out.lower()
    elif mgr == "choco":
        rc, out = _run(["choco", "list", "--local-only", name])
        return rc == 0 and name.lower() in out.lower()
    else:
        return False
    return rc == 0


def _pkg_install(name: str) -> tuple[int, str]:
    mgr = _pkg_manager()
    cmds = {
        "dpkg": ["apt-get", "install", "-y", name],
        "rpm": [("dnf" if shutil.which("dnf") else "yum"), "install", "-y", name],
        "winget": ["winget", "install", "--id", name, "--exact", "--silent",
                   "--accept-package-agreements", "--accept-source-agreements"],
        "choco": ["choco", "install", name, "-y"],
    }
    return _run(cmds.get(mgr, ["false"]))


def _pkg_remove(name: str) -> tuple[int, str]:
    mgr = _pkg_manager()
    cmds = {
        "dpkg": ["apt-get", "remove", "-y", name],
        "rpm": [("dnf" if shutil.which("dnf") else "yum"), "remove", "-y", name],
        "winget": ["winget", "uninstall", "--id", name, "--exact", "--silent"],
        "choco": ["choco", "uninstall", name, "-y"],
    }
    return _run(cmds.get(mgr, ["false"]))


def handle_pkg(state: dict, sources: dict, test: bool) -> dict:
    name = state["name"]
    ensure = state.get("ensure", "present")
    installed = _pkg_installed(name)

    if ensure in ("present", "latest"):
        if installed and ensure == "present":
            return {"result": True, "changes": {}, "comment": "already installed"}
        if test:
            return {"result": None, "changes": {"old": "absent" if not installed else "old", "new": "installed"},
                    "comment": "would install"}
        rc, out = _pkg_install(name)
        if rc == 0:
            return {"result": True, "changes": {"old": "absent", "new": "installed"}, "comment": "installed", "output": out}
        return {"result": False, "changes": {}, "comment": "install failed", "output": out}

    if ensure == "absent":
        if not installed:
            return {"result": True, "changes": {}, "comment": "already absent"}
        if test:
            return {"result": None, "changes": {"old": "installed", "new": "absent"}, "comment": "would remove"}
        rc, out = _pkg_remove(name)
        if rc == 0:
            return {"result": True, "changes": {"old": "installed", "new": "absent"}, "comment": "removed", "output": out}
        return {"result": False, "changes": {}, "comment": "remove failed", "output": out}

    return {"result": False, "changes": {}, "comment": f"unknown ensure '{ensure}'"}


# ── service helpers ───────────────────────────────────────────────────────────
def _svc_is_active(name: str) -> bool:
    if IS_WINDOWS:
        rc, out = _run(["powershell", "-NonInteractive", "-Command",
                        f"(Get-Service -Name '{name}').Status"])
        return rc == 0 and "running" in out.lower()
    rc, out = _run(["systemctl", "is-active", name])
    return out.strip() == "active"


def _svc_is_enabled(name: str) -> bool:
    if IS_WINDOWS:
        rc, out = _run(["powershell", "-NonInteractive", "-Command",
                        f"(Get-Service -Name '{name}').StartType"])
        return rc == 0 and "automatic" in out.lower()
    rc, out = _run(["systemctl", "is-enabled", name])
    return out.strip() == "enabled"


def _svc_start(name: str) -> tuple[int, str]:
    return _run(["powershell", "-NonInteractive", "-Command", f"Start-Service '{name}'"]) if IS_WINDOWS \
        else _run(["systemctl", "start", name])


def _svc_stop(name: str) -> tuple[int, str]:
    return _run(["powershell", "-NonInteractive", "-Command", f"Stop-Service '{name}'"]) if IS_WINDOWS \
        else _run(["systemctl", "stop", name])


def _svc_set_enabled(name: str, enabled: bool) -> tuple[int, str]:
    if IS_WINDOWS:
        kind = "Automatic" if enabled else "Manual"
        return _run(["powershell", "-NonInteractive", "-Command",
                     f"Set-Service -Name '{name}' -StartupType {kind}"])
    return _run(["systemctl", "enable" if enabled else "disable", name])


def _svc_restart(name: str) -> tuple[int, str]:
    return _run(["powershell", "-NonInteractive", "-Command", f"Restart-Service '{name}'"]) if IS_WINDOWS \
        else _run(["systemctl", "restart", name])


def handle_service(state: dict, sources: dict, test: bool) -> dict:
    name = state["name"]
    ensure = state.get("ensure", "running")
    want_active = ensure == "running"
    changes: dict = {}

    logs: list[str] = []
    is_active = _svc_is_active(name)
    if is_active != want_active:
        if test:
            changes["active"] = {"old": is_active, "new": want_active}
        else:
            rc, out = (_svc_start(name) if want_active else _svc_stop(name))
            logs.append(out)
            if rc != 0:
                return {"result": False, "changes": {}, "comment": "service change failed", "output": "\n".join(logs)}
            changes["active"] = {"old": is_active, "new": want_active}

    if "enabled" in state:
        want_enabled = bool(state["enabled"])
        is_enabled = _svc_is_enabled(name)
        if is_enabled != want_enabled:
            if test:
                changes["enabled"] = {"old": is_enabled, "new": want_enabled}
            else:
                rc, out = _svc_set_enabled(name, want_enabled)
                logs.append(out)
                if rc != 0:
                    return {"result": False, "changes": {}, "comment": "enable change failed", "output": "\n".join(logs)}
                changes["enabled"] = {"old": is_enabled, "new": want_enabled}

    if not changes:
        return {"result": True, "changes": {}, "comment": "service in desired state"}
    return {"result": None if test else True, "changes": changes,
            "comment": "would change service" if test else "service reconciled", "output": "\n".join(logs)}


def _service_react(state: dict, test: bool) -> dict:
    """watch reaction: restart the service."""
    name = state["name"]
    if test:
        return {"result": None, "changes": {"restart": "would restart (watch)"}, "comment": "would restart"}
    rc, out = _svc_restart(name)
    if rc == 0:
        return {"result": True, "changes": {"restart": "restarted (watch)"}, "comment": "restarted", "output": out}
    return {"result": False, "changes": {}, "comment": "restart failed", "output": out}


HANDLERS = {
    "pkg": lambda s, src, t: handle_pkg(s, src, t),
    "service": lambda s, src, t: handle_service(s, src, t),
    "file": lambda s, src, t: handle_file(s, src, t),
    "cmd": lambda s, src, t: handle_cmd(s, src, t),
}


def _deps(state: dict) -> list[str]:
    return list(state.get("require") or []) + list(state.get("watch") or [])


def order_resources(states: list[dict]) -> list[dict]:
    """Topologically order by require+watch. Raises ValueError on cycle/unknown id."""
    by_id = {s["id"]: s for s in states}
    visited: dict[str, int] = {}  # 1 = done (visiting tracked via the stack set)
    out: list[dict] = []

    def visit(sid: str, stack: set[str]) -> None:
        if visited.get(sid) == 1:
            return
        if sid in stack:
            raise ValueError(f"requisite cycle at '{sid}'")
        if sid not in by_id:
            raise ValueError(f"unknown requisite id '{sid}'")
        stack.add(sid)
        for dep in _deps(by_id[sid]):
            visit(dep, stack)
        stack.discard(sid)
        visited[sid] = 1
        out.append(by_id[sid])

    for s in states:
        visit(s["id"], set())
    return out


def run_blueprint(states: list[dict], sources: dict, test: bool, emit=None) -> list[dict]:
    _emit_token = _emit_var.set(emit) if emit is not None else None
    try:
        ordered = order_resources(states)
        results: dict[str, dict] = {}
        failed: set[str] = set()
        changed: set[str] = set()

        for st in ordered:
            sid = st["id"]
            if emit is not None:
                _rid_var.set(sid)
                emit({"kind": "resource_start", "id": sid})
            reqs = list(st.get("require") or [])
            if any(r in failed for r in reqs):
                res = {"id": sid, "result": False, "changes": {}, "comment": "requisite failed — skipped"}
            else:
                handler = HANDLERS.get(st["type"])
                if not handler:
                    res = {"id": sid, "result": False, "changes": {}, "comment": f"unknown type '{st['type']}'"}
                else:
                    res = dict(handler(st, sources, test))
                    res["id"] = sid
                    watched = list(st.get("watch") or [])
                    if st["type"] == "service" and any(w in changed for w in watched):
                        react = _service_react(st, test)
                        res["changes"] = {**res.get("changes", {}), **react.get("changes", {})}
                        if react.get("output"):
                            res["output"] = (res.get("output", "") + "\n" + react["output"]).strip()
                        if res["result"] is True and react["result"] is None:
                            res["result"] = None
                        if react["result"] is False:
                            res["result"] = False
                        res["comment"] = (res.get("comment", "") + "; " + react.get("comment", "")).strip("; ")

            res["output"] = str(res.get("output", ""))[:4000]
            results[sid] = res
            if res["result"] is False:
                failed.add(sid)
            if res.get("changes"):
                changed.add(sid)
            if emit is not None:
                emit({"kind": "resource_result", **res})

        return [results[s["id"]] for s in ordered]
    finally:
        if _emit_token is not None:
            _emit_var.reset(_emit_token)
