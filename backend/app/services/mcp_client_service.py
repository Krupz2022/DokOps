# backend/app/services/mcp_client_service.py
import asyncio
import concurrent.futures as _cf
import json
import re
import subprocess
import uuid
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional


from sqlmodel import Session, select


def _run_async(coro):
    """Run an async coroutine from a synchronous context safely.

    asyncio.run() raises RuntimeError if an event loop is already running (e.g. FastAPI).
    This helper submits the coroutine to a fresh thread that has no running loop.
    """
    with _cf.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()

from app.core.db import engine
from app.models.mcp import MCPServer, MCPTool
# encrypt_secret / decrypt_secret used in Tasks 3–5 transport implementations
# to decrypt server.auth_value before building auth headers
from app.services.azure_service import encrypt_secret, decrypt_secret  # noqa: F401

CONFIRMATION_KEYWORDS = {
    "delete", "destroy", "remove", "create", "write",
    "apply", "update", "patch", "scale", "restart", "exec", "run",
}


def requires_confirmation(tool: MCPTool) -> bool:
    if tool.confirmation_override is not None:
        return tool.confirmation_override
    text = (tool.name + " " + tool.description).lower()
    return any(kw in text for kw in CONFIRMATION_KEYWORDS)


def _slugify(name: str) -> str:
    """Convert display name to safe identifier: 'GitHub MCP' → 'github_mcp'"""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _make_namespaced(server_name: str, tool_name: str) -> str:
    return f"mcp__{_slugify(server_name)}__{tool_name}"


def _parse_namespaced(namespaced: str):
    """'mcp__github_mcp__create_issue' → ('github_mcp', 'create_issue')"""
    if not namespaced.startswith("mcp__"):
        return None, None
    parts = namespaced[len("mcp__"):].split("__", 1)
    if len(parts) != 2:
        return None, None
    return parts[0], parts[1]


def _schema_to_params(schema_json: str) -> str:
    try:
        schema = json.loads(schema_json)
        props = schema.get("properties", {})
        return ", ".join(props.keys())
    except Exception:
        return ""


class MCPClientService:
    def __init__(self) -> None:
        self._stdio_procs: Dict[str, Any] = {}

    def build_openai_tools_schema(self) -> list:
        """Return connected MCP tools as OpenAI function-calling tool entries."""
        with Session(engine) as session:
            servers = session.exec(
                select(MCPServer).where(MCPServer.is_connected == True)  # noqa: E712
            ).all()
            tools = []
            for server in servers:
                mcp_tools = session.exec(
                    select(MCPTool).where(MCPTool.server_id == server.id)
                ).all()
                for t in mcp_tools:
                    ns_name = _make_namespaced(server.name, t.name)
                    try:
                        schema = json.loads(t.input_schema or "{}")
                    except Exception:
                        schema = {}
                    properties = schema.get("properties", {})
                    required = schema.get("required", [])
                    tools.append({
                        "type": "function",
                        "function": {
                            "name": ns_name,
                            "description": f"[{server.name}] {t.description}",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    k: {"type": v.get("type", "string"), "description": v.get("description", k)}
                                    for k, v in properties.items()
                                },
                                "required": required,
                            },
                        },
                    })
            return tools

    def build_gemini_tools_schema(self) -> list:
        """Return connected MCP tools as Gemini function_declarations entries."""
        with Session(engine) as session:
            servers = session.exec(
                select(MCPServer).where(MCPServer.is_connected == True)  # noqa: E712
            ).all()
            declarations = []
            for server in servers:
                mcp_tools = session.exec(
                    select(MCPTool).where(MCPTool.server_id == server.id)
                ).all()
                for t in mcp_tools:
                    ns_name = _make_namespaced(server.name, t.name)
                    try:
                        schema = json.loads(t.input_schema or "{}")
                    except Exception:
                        schema = {}
                    properties = schema.get("properties", {})
                    declarations.append({
                        "name": ns_name,
                        "description": f"[{server.name}] {t.description}",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                k: {"type": "STRING", "description": v.get("description", k)}
                                for k, v in properties.items()
                            },
                        },
                    })
            return declarations

    def get_all_tools_for_prompt(self) -> str:
        with Session(engine) as session:
            servers = session.exec(
                select(MCPServer).where(MCPServer.is_connected == True)  # noqa: E712
            ).all()
            if not servers:
                return ""

            lines = ["MCP TOOLS (from connected external MCP servers):"]
            for server in servers:
                tools = session.exec(
                    select(MCPTool).where(MCPTool.server_id == server.id)
                ).all()
                for tool in tools:
                    ns_name = _make_namespaced(server.name, tool.name)
                    params = _schema_to_params(tool.input_schema)
                    flag = "REQUIRES CONFIRMATION" if requires_confirmation(tool) else "EXECUTES IMMEDIATELY"
                    lines.append(
                        f"- {ns_name}({params}): {tool.description} [{flag}]"
                    )
            return "\n".join(lines)

    def execute_tool(self, tool_name: str, inputs: dict, confirmed: bool = False) -> dict:
        server_slug, raw_tool_name = _parse_namespaced(tool_name)
        if not server_slug or not raw_tool_name:
            return {"success": False, "data": None, "error": f"Invalid MCP tool name: {tool_name}", "source": "mcp"}

        with Session(engine) as session:
            servers = session.exec(
                select(MCPServer).where(MCPServer.is_connected == True)  # noqa: E712
            ).all()
            server = next((s for s in servers if _slugify(s.name) == server_slug), None)
            if not server:
                return {"success": False, "data": None, "error": f"No connected MCP server with slug '{server_slug}'", "source": "mcp"}

            tool = session.exec(
                select(MCPTool).where(
                    MCPTool.server_id == server.id,
                    MCPTool.name == raw_tool_name,
                )
            ).first()
            if not tool:
                return {"success": False, "data": None, "error": f"Tool '{raw_tool_name}' not found on server '{server.name}'", "source": "mcp"}

            if requires_confirmation(tool) and not confirmed:
                op_id = str(uuid.uuid4())
                return {
                    "requires_confirmation": True,
                    "pending_operation": {
                        "id": op_id,
                        "tool_name": tool_name,
                        "tool_inputs": inputs,
                        "confirmation_message": f"MCP tool **{tool_name}** requires confirmation.\n\n{tool.description}\n\nParameters: `{json.dumps(inputs)}`",
                        "risk_level": "medium",
                        "created_at": time.time(),
                        "status": "pending",
                    },
                }

            server_id = server.id

        return self.call_tool(server_id, raw_tool_name, inputs)

    def call_tool(self, server_id: str, tool_name: str, inputs: dict) -> dict:
        with Session(engine) as session:
            server = session.get(MCPServer, server_id)
            if not server:
                return {"success": False, "data": None, "error": "Server not found", "source": "mcp"}

            if server.transport == "http":
                return self._call_http(server, tool_name, inputs)
            elif server.transport == "sse":
                return self._call_sse(server, tool_name, inputs)
            elif server.transport == "stdio":
                return self._call_stdio(server, tool_name, inputs)
            else:
                return {"success": False, "data": None, "error": f"Unknown transport: {server.transport}", "source": "mcp"}

    def connect(self, server_id: str) -> dict:
        with Session(engine) as session:
            server = session.get(MCPServer, server_id)
            if not server:
                return {"connected": False, "error": "Server not found", "tool_count": 0}

            try:
                if server.transport == "http":
                    tools = self._list_tools_http(server)
                elif server.transport == "sse":
                    tools = self._list_tools_sse(server)
                elif server.transport == "stdio":
                    tools = self._list_tools_stdio(server)
                else:
                    return {"connected": False, "error": f"Unknown transport: {server.transport}", "tool_count": 0}

                # Delete old tools for this server
                old_tools = session.exec(select(MCPTool).where(MCPTool.server_id == server_id)).all()
                for t in old_tools:
                    session.delete(t)

                # Insert new tools
                for t in tools:
                    mcp_tool = MCPTool(
                        server_id=server_id,
                        name=t["name"],
                        description=t.get("description", ""),
                        input_schema=json.dumps(t.get("inputSchema", {})),
                        last_synced_at=datetime.now(timezone.utc),
                    )
                    session.add(mcp_tool)

                server.is_connected = True
                server.last_connected_at = datetime.now(timezone.utc)
                session.add(server)
                session.commit()

                return {"connected": True, "tool_count": len(tools)}

            except Exception as e:
                session.rollback()
                # server is expired/detached after rollback — reload from DB
                fresh_server = session.get(MCPServer, server_id)
                if fresh_server:
                    fresh_server.is_connected = False
                    session.add(fresh_server)
                    session.commit()
                return {"connected": False, "error": str(e), "tool_count": 0}

    def refresh(self, server_id: str) -> dict:
        return self.connect(server_id)

    # --- Transport implementations ---

    # ── Task 3: HTTP transport ──────────────────────────────────────────────

    def _build_http_headers(self, server: MCPServer) -> dict:
        import base64
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if server.auth_type == "none" or not server.auth_value:
            return headers
        auth_val = decrypt_secret(server.auth_value)
        if server.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {auth_val}"
        elif server.auth_type == "api_key":
            headers["X-API-Key"] = auth_val
        elif server.auth_type == "basic":
            user, pwd = (auth_val.split(":", 1) + [""])[:2]
            encoded = base64.b64encode(f"{user}:{pwd}".encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        return headers

    @staticmethod
    def _parse_mcp_response(resp) -> dict:
        """Parse an MCP HTTP response that may be JSON or SSE-wrapped JSON."""
        ct = resp.headers.get("content-type", "")
        text = resp.text.strip()
        if not text:
            return {}
        if "text/event-stream" in ct:
            # Extract JSON from SSE: find the first `data: {...}` line
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    payload = line[len("data:"):].strip()
                    if payload and payload != "[DONE]":
                        try:
                            return json.loads(payload)
                        except json.JSONDecodeError:
                            continue
            return {}
        return json.loads(text)

    def _http_initialize(self, client, server: MCPServer, headers: dict) -> dict:
        """Perform MCP initialize handshake. Returns headers with session ID if provided."""
        init_payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "dokops", "version": "1.0.0"},
            },
        }
        resp = client.post(server.url, json=init_payload, headers=headers)
        resp.raise_for_status()

        session_headers = dict(headers)
        session_id = resp.headers.get("mcp-session-id")
        if session_id:
            session_headers["Mcp-Session-Id"] = session_id

        # Send initialized notification (fire-and-forget, ignore response)
        notif_payload = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        try:
            client.post(server.url, json=notif_payload, headers=session_headers)
        except Exception:
            pass

        return session_headers

    def _list_tools_http(self, server: MCPServer) -> list:
        import httpx
        headers = self._build_http_headers(server)
        with httpx.Client(timeout=15.0) as client:
            session_headers = self._http_initialize(client, server, headers)
            payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "tools/list", "params": {}}
            resp = client.post(server.url, json=payload, headers=session_headers)
            resp.raise_for_status()
            data = self._parse_mcp_response(resp)
            return data.get("result", {}).get("tools", [])

    def _call_http(self, server: MCPServer, tool_name: str, inputs: dict) -> dict:
        import httpx
        headers = self._build_http_headers(server)
        try:
            with httpx.Client(timeout=30.0) as client:
                session_headers = self._http_initialize(client, server, headers)
                payload = {
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": inputs},
                }
                resp = client.post(server.url, json=payload, headers=session_headers)
                resp.raise_for_status()
                data = self._parse_mcp_response(resp)
                result = data.get("result", {})
                is_error = result.get("isError", False)
                content = result.get("content", [])
                text = "\n".join(
                    c.get("text", str(c)) if isinstance(c, dict) else str(c)
                    for c in content
                )
                return {"success": not is_error, "data": text, "error": None if not is_error else text, "source": "mcp"}
        except Exception as e:
            return {"success": False, "data": None, "error": str(e), "source": "mcp"}

    # ── Task 4: SSE transport ───────────────────────────────────────────────

    def _list_tools_sse(self, server: MCPServer) -> list:
        from mcp.client.sse import sse_client
        from mcp import ClientSession

        auth_val = decrypt_secret(server.auth_value) if server.auth_value else None
        headers = {}
        if server.auth_type == "bearer" and auth_val:
            headers["Authorization"] = f"Bearer {auth_val}"
        elif server.auth_type == "api_key" and auth_val:
            headers["X-API-Key"] = auth_val

        async def _inner():
            async with sse_client(server.url, headers=headers) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return [
                        {
                            "name": t.name,
                            "description": t.description or "",
                            "inputSchema": t.inputSchema if hasattr(t, "inputSchema") else {},
                        }
                        for t in result.tools
                    ]

        async def _run():
            return await asyncio.wait_for(_inner(), timeout=30.0)

        return _run_async(_run())

    def _call_sse(self, server: MCPServer, tool_name: str, inputs: dict) -> dict:
        from mcp.client.sse import sse_client
        from mcp import ClientSession

        auth_val = decrypt_secret(server.auth_value) if server.auth_value else None
        headers = {}
        if server.auth_type == "bearer" and auth_val:
            headers["Authorization"] = f"Bearer {auth_val}"
        elif server.auth_type == "api_key" and auth_val:
            headers["X-API-Key"] = auth_val

        async def _inner():
            async with sse_client(server.url, headers=headers) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, inputs)
                    content = "\n".join(
                        c.text if hasattr(c, "text") else str(c)
                        for c in result.content
                    )
                    return {
                        "success": not result.isError,
                        "data": content,
                        "error": content if result.isError else None,
                        "source": "mcp",
                    }

        async def _run():
            return await asyncio.wait_for(_inner(), timeout=30.0)

        try:
            return _run_async(_run())
        except Exception as e:
            return {"success": False, "data": None, "error": str(e), "source": "mcp"}

    # ── Task 5: stdio transport ─────────────────────────────────────────────

    def _list_tools_stdio(self, server: MCPServer) -> list:
        from mcp.client.stdio import stdio_client, StdioServerParameters
        from mcp import ClientSession

        args_list = json.loads(server.args or "[]")
        params = StdioServerParameters(command=server.command, args=args_list)

        async def _inner():
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return [
                        {
                            "name": t.name,
                            "description": t.description or "",
                            "inputSchema": t.inputSchema if hasattr(t, "inputSchema") else {},
                        }
                        for t in result.tools
                    ]

        async def _run():
            return await asyncio.wait_for(_inner(), timeout=30.0)

        return _run_async(_run())

    def _call_stdio(self, server: MCPServer, tool_name: str, inputs: dict) -> dict:
        """Call a tool on a stdio MCP server, reusing a persistent subprocess."""
        try:
            proc = self._stdio_procs.get(server.id)
            if proc is None or proc.poll() is not None:
                # Spawn a new process — NOT shell=True to prevent command injection
                args_list = json.loads(server.args or "[]")
                cmd = [server.command] + args_list
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                self._stdio_procs[server.id] = proc

            request = json.dumps({
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": inputs},
            }) + "\n"
            proc.stdin.write(request.encode())
            proc.stdin.flush()
            response_line = proc.stdout.readline()
            data = json.loads(response_line)
            result = data.get("result", {})
            is_error = result.get("isError", False)
            content = result.get("content", [])
            text = "\n".join(
                c.get("text", str(c)) if isinstance(c, dict) else str(c)
                for c in content
            )
            return {"success": not is_error, "data": text, "error": text if is_error else None, "source": "mcp"}
        except Exception as e:
            # Remove dead/broken process so next call spawns a fresh one
            self._stdio_procs.pop(server.id, None)
            return {"success": False, "data": None, "error": str(e), "source": "mcp"}


mcp_client_service = MCPClientService()
