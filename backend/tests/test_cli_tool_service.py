import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock
from app.services.cli_tool_service import CLIToolService, PREDEFINED_TOOLS

service = CLIToolService()

def test_predefined_tools_have_required_keys():
    for name, tool in PREDEFINED_TOOLS.items():
        assert "description" in tool, f"{name} missing description"
        assert "version_cmd" in tool, f"{name} missing version_cmd"
        assert "install_type" in tool, f"{name} missing install_type"

@pytest.mark.asyncio
async def test_check_tool_installed():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="v3.14.0", stderr="")
        result = await service._check_tool("helm")
    assert result["installed"] is True
    assert result["version"] == "v3.14.0"

@pytest.mark.asyncio
async def test_check_tool_not_installed():
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError("helm not found")
        result = await service._check_tool("helm")
    assert result["installed"] is False
    assert result["version"] is None

@pytest.mark.asyncio
async def test_detect_all_returns_all_tools():
    async def _fake_check(name):
        return {"installed": False, "version": None}
    with patch.object(service, "_check_tool", side_effect=_fake_check):
        results = await service.detect_all()
    assert len(results) == len(PREDEFINED_TOOLS)
    for r in results:
        assert "name" in r
        assert "installed" in r
    # Verify results are sorted by name
    names = [r["name"] for r in results]
    assert names == sorted(names)

def test_detect_platform_windows():
    with patch("platform.system", return_value="Windows"), \
         patch("platform.machine", return_value="AMD64"):
        result = service._detect_platform()
    assert result == "windows_amd64"

def test_detect_platform_linux():
    with patch("platform.system", return_value="Linux"), \
         patch("platform.machine", return_value="x86_64"):
        result = service._detect_platform()
    assert result == "linux_amd64"

def test_find_asset_by_pattern():
    assets = [
        {"name": "helm-v3.14.0-linux-amd64.tar.gz", "browser_download_url": "http://example.com/helm-linux.tar.gz"},
        {"name": "helm-v3.14.0-windows-amd64.zip",  "browser_download_url": "http://example.com/helm-win.zip"},
    ]
    result = service._find_asset(assets, "linux-amd64.tar.gz")
    assert result["name"] == "helm-v3.14.0-linux-amd64.tar.gz"

def test_find_asset_returns_none_when_no_match():
    assets = [{"name": "helm-v3.14.0-darwin-amd64.tar.gz", "browser_download_url": "http://x.com/a"}]
    result = service._find_asset(assets, "linux-amd64.tar.gz")
    assert result is None

@pytest.mark.asyncio
async def test_install_predefined_unknown_tool():
    result = await service.install_predefined("nonexistent_tool")
    assert result["success"] is False
    assert "Unknown tool" in result["output"]

def test_custom_tools_roundtrip(tmp_path, monkeypatch):
    import app.services.cli_tool_service as svc_module
    monkeypatch.setattr(svc_module, "_CUSTOM_TOOLS_FILE", tmp_path / "cli_custom_tools.json")
    service.save_custom_tool({"name": "mytool", "platform": "linux", "command": "curl -o /tmp/mytool http://example.com/mytool"})
    tools = service.list_custom_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "mytool"

def test_delete_custom_tool(tmp_path, monkeypatch):
    import app.services.cli_tool_service as svc_module
    monkeypatch.setattr(svc_module, "_CUSTOM_TOOLS_FILE", tmp_path / "cli_custom_tools.json")
    service.save_custom_tool({"name": "mytool", "platform": "linux", "command": "echo hi"})
    service.delete_custom_tool("mytool")
    assert service.list_custom_tools() == []

@pytest.mark.asyncio
async def test_install_custom_tool_runs_command():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="done\n", stderr="")
        result = await service.install_custom_tool({"name": "t", "platform": "both", "command": "echo hi"})
    assert result["success"] is True
    assert "done" in result["output"]

@pytest.mark.asyncio
async def test_install_custom_tool_platform_mismatch():
    with patch.object(service, "_detect_platform", return_value="linux_amd64"):
        result = await service.install_custom_tool({"name": "t", "platform": "windows", "command": "echo hi"})
    assert result["success"] is False
    assert "Windows" in result["output"]
