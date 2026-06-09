import asyncio
import os
import platform
import subprocess
import shlex
import json
# The following imports are used by the downloader methods added in install_predefined() below
import urllib.request
import zipfile
import tarfile
import shutil
import tempfile
import stat
from pathlib import Path
from typing import Any, Optional

PREDEFINED_TOOLS: dict = {
    "helm": {
        "description": "Kubernetes package manager — install, upgrade, and rollback releases",
        "version_cmd": "helm version --short",
        "install_type": "github_release",
        "repo": "helm/helm",
        "asset_patterns": {
            "windows_amd64": "windows-amd64.zip",
            "linux_amd64":   "linux-amd64.tar.gz",
            "linux_arm64":   "linux-arm64.tar.gz",
        },
        "binary_name":    "helm",
        "archive_subdir": True,
    },
    "kubectl": {
        "description": "Official Kubernetes CLI — raw cluster operations",
        "version_cmd": "kubectl version --client -o json",
        "install_type": "kubectl_special",
    },
    "kubectx": {
        "description": "Fast cluster and namespace context switcher",
        "version_cmd": "kubectx --version",
        "install_type": "github_release",
        "repo": "ahmetb/kubectx",
        "asset_patterns": {
            "windows_amd64": "windows_x86_64.zip",
            "linux_amd64":   "linux_x86_64.tar.gz",
            "linux_arm64":   "linux_arm64.tar.gz",
        },
        "binary_name":    "kubectx",
        "archive_subdir": False,
    },
    "kustomize": {
        "description": "Kubernetes native config management via overlays",
        "version_cmd": "kustomize version",
        "install_type": "github_release",
        "repo": "kubernetes-sigs/kustomize",
        "asset_patterns": {
            "windows_amd64": "kustomize_v",
            "linux_amd64":   "linux_amd64.tar.gz",
            "linux_arm64":   "linux_arm64.tar.gz",
        },
        "binary_name":    "kustomize",
        "archive_subdir": False,
    },
    "flux": {
        "description": "FluxCD GitOps CLI — manage continuous delivery pipelines",
        "version_cmd": "flux --version",
        "install_type": "github_release",
        "repo": "fluxcd/flux2",
        "asset_patterns": {
            "windows_amd64": "windows_amd64.zip",
            "linux_amd64":   "linux_amd64.tar.gz",
            "linux_arm64":   "linux_arm64.tar.gz",
        },
        "binary_name":    "flux",
        "archive_subdir": False,
    },
    "argocd": {
        "description": "Argo CD CLI — declarative GitOps for Kubernetes",
        "version_cmd": "argocd version --client",
        "install_type": "github_release",
        "repo": "argoproj/argo-cd",
        "asset_patterns": {
            "windows_amd64": "argocd-windows-amd64.exe",
            "linux_amd64":   "argocd-linux-amd64",
            "linux_arm64":   "argocd-linux-arm64",
        },
        "binary_name":    "argocd",
        "archive_subdir": False,
        "direct_binary":  True,
    },
    "helm-diff": {
        "description": "Helm plugin — preview what changes a helm upgrade would apply",
        "version_cmd": "helm plugin list",
        "install_type": "helm_plugin",
        "plugin_url":   "https://github.com/databus23/helm-diff",
    },
}

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = _BACKEND_ROOT / "bin"
_CUSTOM_TOOLS_FILE = Path(__file__).resolve().parent.parent / "toolsets" / "cli_custom_tools.json"


class CLIToolService:

    async def _check_tool(self, name: str) -> dict[str, Any]:
        tool = PREDEFINED_TOOLS[name]
        cmd = tool["version_cmd"]
        try:
            # shell=True is intentional: version_cmd values may use pipes (e.g. helm plugin list | grep diff).
            # Commands come from the hardcoded PREDEFINED_TOOLS dict, never from user input.
            result = await asyncio.to_thread(
                subprocess.run,
                cmd, shell=True, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                version = (result.stdout or result.stderr or "").strip().splitlines()[0]
                return {"installed": True, "version": version}
            return {"installed": False, "version": None}
        except Exception:
            # Broad catch intentional: tool may not exist, timeout, permission denied, etc.
            return {"installed": False, "version": None}

    async def detect_all(self) -> list[dict]:
        names = list(PREDEFINED_TOOLS.keys())
        statuses = await asyncio.gather(*[self._check_tool(name) for name in names])
        results = [
            {
                "name": name,
                "description": PREDEFINED_TOOLS[name]["description"],
                "installed": status["installed"],
                "version": status["version"],
            }
            for name, status in zip(names, statuses)
        ]
        return sorted(results, key=lambda x: x["name"])


    # -----------------------------------------------------------------------
    # Platform
    # -----------------------------------------------------------------------

    def _detect_platform(self) -> str:
        """Return 'windows_amd64', 'linux_amd64', or 'linux_arm64'."""
        system = platform.system().lower()
        machine = platform.machine().lower()
        arch = "arm64" if "arm" in machine or "aarch" in machine else "amd64"
        if system == "windows":
            return f"windows_{arch}"
        return f"linux_{arch}"   # Docker is always Linux

    def _find_asset(self, assets: list[dict[str, Any]], pattern: str) -> Optional[dict[str, Any]]:
        """Find a GitHub release asset whose name contains pattern."""
        for asset in assets:
            if pattern in asset["name"]:
                return asset
        return None

    def _fetch_latest_release(self, repo: str) -> dict[str, Any]:
        """Fetch the latest GitHub release metadata for a repo."""
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "dokops/1.0", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        if "message" in data and "assets" not in data:
            raise RuntimeError(f"GitHub API error for {repo}: {data['message']}")
        return data

    def _ensure_bin_dir(self) -> Path:
        """Create and return the backend bin/ directory."""
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        return BIN_DIR

    def _extract_and_place(self, archive_path: Path, binary_name: str, is_windows: bool) -> Path:
        """Extract archive and move the target binary to BIN_DIR."""
        bin_dir = self._ensure_bin_dir()
        ext = ".exe" if is_windows else ""
        target = bin_dir / f"{binary_name}{ext}"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            if archive_path.suffix == ".zip":
                with zipfile.ZipFile(archive_path, "r") as zf:
                    zf.extractall(tmp_path)
            else:
                with tarfile.open(archive_path, "r:gz") as tf:
                    tf.extractall(tmp_path, filter="data")

            # Find the binary anywhere in the extracted tree
            matches = list(tmp_path.rglob(f"{binary_name}{ext}"))
            if not matches:
                raise FileNotFoundError(f"{binary_name}{ext} not found in archive")
            shutil.copy2(matches[0], target)

        if not is_windows:
            target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return target

    def _download_file(self, url: str, dest: Path) -> None:
        """Download a file from url to dest path, following redirects."""
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "dokops/1.0", "Accept": "application/octet-stream"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            status = resp.status
            if status != 200:
                body = resp.read(512)
                raise RuntimeError(
                    f"Download failed: HTTP {status} from {url} — {body!r}"
                )
            content_type = resp.headers.get("Content-Type", "")
            if any(t in content_type for t in ("text/", "application/json", "text/html")):
                body = resp.read(512)
                raise RuntimeError(
                    f"Expected binary but got Content-Type {content_type!r} from {url} — "
                    f"response starts with: {body!r}"
                )
            with open(dest, "wb") as f:
                shutil.copyfileobj(resp, f)
        # Sanity-check: gzip magic bytes are 0x1f 0x8b
        if dest.suffix in (".gz", ".tgz"):
            magic = dest.read_bytes()[:2]
            if magic != b"\x1f\x8b":
                first = dest.read_bytes()[:256]
                dest.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Downloaded file from {url} is not a valid gzip archive. "
                    f"First bytes: {first!r}"
                )

    async def install_predefined(self, tool_name: str) -> dict[str, Any]:
        """Install a pre-defined tool. Returns {success, output, version}."""
        if tool_name not in PREDEFINED_TOOLS:
            return {"success": False, "output": f"Unknown tool: {tool_name}", "version": None}

        tool = PREDEFINED_TOOLS[tool_name]
        install_type = tool["install_type"]

        try:
            if install_type == "github_release":
                return await self._install_github_release(tool_name, tool)
            elif install_type == "kubectl_special":
                return await self._install_kubectl()
            elif install_type == "helm_plugin":
                return await self._install_helm_plugin(tool)
            else:
                return {"success": False, "output": f"Unknown install type: {install_type}", "version": None}
        except Exception:  # Broad catch intentional: network, IO, permission errors
            import traceback
            return {"success": False, "output": traceback.format_exc(), "version": None}

    async def _install_github_release(self, tool_name: str, tool: dict[str, Any]) -> dict[str, Any]:
        """Download and install a tool from its GitHub release."""
        plat = self._detect_platform()
        is_windows = plat.startswith("windows")
        patterns = tool["asset_patterns"]

        pattern = patterns.get(plat) or patterns.get("linux_amd64")
        release = self._fetch_latest_release(tool["repo"])
        assets = release.get("assets", [])

        is_direct_binary = tool.get("direct_binary", False)
        bin_dir = self._ensure_bin_dir()
        ext = ".exe" if is_windows else ""
        binary_name = tool["binary_name"]

        if is_direct_binary:
            asset = self._find_asset(assets, pattern)
            if not asset:
                return {"success": False, "output": f"No asset matching '{pattern}' found in release", "version": None}
            dest = bin_dir / f"{binary_name}{ext}"
            self._download_file(asset["browser_download_url"], dest)
            if not is_windows:
                dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        else:
            asset = self._find_asset(assets, pattern)
            if not asset:
                return {"success": False, "output": f"No asset matching '{pattern}' found in release", "version": None}
            with tempfile.NamedTemporaryFile(suffix=Path(asset["name"]).suffix, delete=False) as tf:
                tmp_path = Path(tf.name)
            try:
                self._download_file(asset["browser_download_url"], tmp_path)
                self._extract_and_place(tmp_path, binary_name, is_windows)
            finally:
                tmp_path.unlink(missing_ok=True)

        status = await self._check_tool(tool_name)
        return {"success": True, "output": f"Installed {binary_name} to {bin_dir}", "version": status.get("version")}

    async def _install_kubectl(self) -> dict[str, Any]:
        """Install kubectl from dl.k8s.io (not GitHub releases)."""
        plat = self._detect_platform()
        is_windows = plat.startswith("windows")
        bin_dir = self._ensure_bin_dir()
        ext = ".exe" if is_windows else ""

        with urllib.request.urlopen("https://dl.k8s.io/release/stable.txt", timeout=15) as resp:
            version = resp.read().decode().strip()

        os_str = "windows" if is_windows else "linux"
        arch = "arm64" if "arm64" in plat else "amd64"
        url = f"https://dl.k8s.io/release/{version}/bin/{os_str}/{arch}/kubectl{ext}"

        dest = bin_dir / f"kubectl{ext}"
        self._download_file(url, dest)
        if not is_windows:
            dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        status = await self._check_tool("kubectl")
        return {"success": True, "output": f"Installed kubectl {version} to {bin_dir}", "version": status.get("version")}

    async def _install_helm_plugin(self, tool: dict[str, Any]) -> dict[str, Any]:
        """Install a helm plugin (requires helm to already be installed)."""
        result = await asyncio.to_thread(
            subprocess.run,
            ["helm", "plugin", "install", tool["plugin_url"]],
            shell=False, capture_output=True, text=True, timeout=120,
        )
        success = result.returncode == 0
        output = (result.stdout + result.stderr).strip()
        return {"success": success, "output": output, "version": None}


    # -----------------------------------------------------------------------
    # Custom tools
    # -----------------------------------------------------------------------

    def _load_custom_tools(self) -> list[dict[str, Any]]:
        """Load custom tools from JSON file."""
        if not _CUSTOM_TOOLS_FILE.exists():
            return []
        try:
            return json.loads(_CUSTOM_TOOLS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _save_custom_tools(self, tools: list[dict[str, Any]]) -> None:
        """Persist custom tools to JSON file."""
        _CUSTOM_TOOLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CUSTOM_TOOLS_FILE.write_text(json.dumps(tools, indent=2), encoding="utf-8")

    def list_custom_tools(self) -> list[dict[str, Any]]:
        """Return all saved custom tool definitions."""
        return self._load_custom_tools()

    def save_custom_tool(self, tool: dict[str, Any]) -> None:
        """Save or replace a custom tool definition."""
        tools = self._load_custom_tools()
        tools = [t for t in tools if t["name"] != tool["name"]]  # replace if exists
        tools.append(tool)
        self._save_custom_tools(tools)

    def delete_custom_tool(self, name: str) -> None:
        """Remove a custom tool definition by name."""
        tools = [t for t in self._load_custom_tools() if t["name"] != name]
        self._save_custom_tools(tools)

    async def install_custom_tool(self, tool: dict[str, Any]) -> dict[str, Any]:
        """Run the custom install command, respecting platform constraints."""
        plat = self._detect_platform()
        tool_platform = tool.get("platform", "both")

        if tool_platform == "windows" and not plat.startswith("windows"):
            return {"success": False, "output": "This tool is configured for Windows only but server is Linux.", "version": None}
        if tool_platform == "linux" and plat.startswith("windows"):
            return {"success": False, "output": "This tool is configured for Linux only but server is Windows.", "version": None}

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                shlex.split(tool["command"]),
                shell=False, capture_output=True,
                text=True, timeout=120,
            )
            output = (result.stdout + result.stderr)[:50000]
            return {"success": result.returncode == 0, "output": output.strip(), "version": None}
        except Exception as e:
            # Broad catch intentional: subprocess.TimeoutExpired, OSError, etc.
            return {"success": False, "output": str(e), "version": None}


cli_tool_service: CLIToolService = CLIToolService()
