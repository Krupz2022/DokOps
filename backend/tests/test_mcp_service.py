import pytest
from sqlmodel import SQLModel, create_engine, Session


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    import app.models.mcp  # noqa
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr("app.services.mcp_client_service.engine", test_engine)
    monkeypatch.setattr("app.core.db.engine", test_engine)
    yield test_engine


def test_mcp_server_model_creates_and_reads(isolated_db):
    from app.models.mcp import MCPServer
    server = MCPServer(
        id="test-id",
        name="Test Server",
        description="A test MCP server",
        transport="http",
        url="http://localhost:3000",
        auth_type="none",
        is_connected=False,
    )
    with Session(isolated_db) as session:
        session.add(server)
        session.commit()
        result = session.get(MCPServer, "test-id")
        assert result.name == "Test Server"
        assert result.transport == "http"


def test_mcp_tool_model_creates_and_reads(isolated_db):
    from app.models.mcp import MCPServer, MCPTool
    server = MCPServer(
        id="s1", name="S", description="d", transport="http",
        url="http://localhost:3000", auth_type="none", is_connected=True,
    )
    with Session(isolated_db) as session:
        session.add(server)
        session.commit()

    tool = MCPTool(
        id="t1", server_id="s1", name="create_issue",
        description="Create a GitHub issue",
        input_schema='{"type":"object","properties":{"title":{"type":"string"}}}',
        confirmation_override=None,
    )
    with Session(isolated_db) as session:
        session.add(tool)
        session.commit()
        result = session.get(MCPTool, "t1")
        assert result.name == "create_issue"
        assert result.confirmation_override is None


def test_requires_confirmation_by_keyword():
    from app.models.mcp import MCPTool
    from app.services.mcp_client_service import requires_confirmation
    tool = MCPTool(id="1", server_id="s", name="delete_branch",
                   description="Deletes a Git branch", input_schema="{}")
    assert requires_confirmation(tool) is True


def test_requires_confirmation_false_for_read():
    from app.models.mcp import MCPTool
    from app.services.mcp_client_service import requires_confirmation
    tool = MCPTool(id="2", server_id="s", name="get_issues",
                   description="List GitHub issues", input_schema="{}")
    assert requires_confirmation(tool) is False


def test_requires_confirmation_override_true_overrides_heuristic():
    from app.models.mcp import MCPTool
    from app.services.mcp_client_service import requires_confirmation
    tool = MCPTool(id="3", server_id="s", name="get_issues",
                   description="List GitHub issues", input_schema="{}",
                   confirmation_override=True)
    assert requires_confirmation(tool) is True


def test_requires_confirmation_override_false_overrides_heuristic():
    from app.models.mcp import MCPTool
    from app.services.mcp_client_service import requires_confirmation
    tool = MCPTool(id="4", server_id="s", name="delete_branch",
                   description="Deletes a Git branch", input_schema="{}",
                   confirmation_override=False)
    assert requires_confirmation(tool) is False


def test_get_all_tools_for_prompt_format(isolated_db):
    from app.models.mcp import MCPServer, MCPTool
    from app.services.mcp_client_service import MCPClientService

    server = MCPServer(
        id="gh", name="GitHub MCP", description="GitHub tools",
        transport="http", url="http://localhost:3100", auth_type="none",
        is_connected=True,
    )
    tool = MCPTool(
        id="t1", server_id="gh", name="create_issue",
        description="Create a GitHub issue",
        input_schema='{"type":"object","properties":{"title":{"type":"string"},"body":{"type":"string"}}}',
        confirmation_override=None,
    )
    with Session(isolated_db) as session:
        session.add(server)
        session.add(tool)
        session.commit()

    svc = MCPClientService()
    prompt = svc.get_all_tools_for_prompt()
    assert "mcp__github_mcp__create_issue" in prompt
    assert "REQUIRES CONFIRMATION" in prompt
    assert "MCP TOOLS" in prompt


def test_execute_tool_returns_pending_when_confirmation_required(isolated_db):
    from app.models.mcp import MCPServer, MCPTool
    from app.services.mcp_client_service import MCPClientService

    server = MCPServer(
        id="gh", name="GitHub MCP", description="GitHub tools",
        transport="http", url="http://localhost:3100", auth_type="none",
        is_connected=True,
    )
    tool = MCPTool(
        id="t1", server_id="gh", name="delete_branch",
        description="Delete a branch",
        input_schema='{"type":"object","properties":{"branch":{"type":"string"}}}',
    )
    with Session(isolated_db) as session:
        session.add(server)
        session.add(tool)
        session.commit()

    svc = MCPClientService()
    result = svc.execute_tool("mcp__github_mcp__delete_branch", {"branch": "main"}, confirmed=False)
    assert result.get("requires_confirmation") is True
    assert "pending_operation" in result


def test_connect_syncs_tools(isolated_db):
    from unittest.mock import patch
    from app.models.mcp import MCPServer, MCPTool
    from app.services.mcp_client_service import MCPClientService

    server = MCPServer(
        id="srv1", name="Test MCP", description="test",
        transport="http", url="http://localhost:9999", auth_type="none",
        is_connected=False,
    )
    # Pre-existing stale tool that should be removed on connect
    stale_tool = MCPTool(
        id="stale", server_id="srv1", name="old_tool",
        description="old", input_schema="{}",
    )
    with Session(isolated_db) as session:
        session.add(server)
        session.add(stale_tool)
        session.commit()

    fake_tools = [
        {"name": "new_tool_a", "description": "Tool A", "inputSchema": {"type": "object", "properties": {}}},
        {"name": "new_tool_b", "description": "Tool B", "inputSchema": {}},
    ]

    svc = MCPClientService()
    with patch.object(svc, "_list_tools_http", return_value=fake_tools):
        result = svc.connect("srv1")

    assert result["connected"] is True
    assert result["tool_count"] == 2

    with Session(isolated_db) as session:
        tools = session.exec(
            __import__("sqlmodel").select(MCPTool).where(MCPTool.server_id == "srv1")
        ).all()
        tool_names = {t.name for t in tools}
        assert "old_tool" not in tool_names
        assert "new_tool_a" in tool_names
        assert "new_tool_b" in tool_names

        updated_server = session.get(MCPServer, "srv1")
        assert updated_server.is_connected is True
        assert updated_server.last_connected_at is not None
