# backend/app/api/v1/mcp.py
import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import deps
from app.core.db import AsyncSessionLocal
from app.models.mcp import MCPServer, MCPTool
from app.models.user import User
from app.services.azure_service import encrypt_secret
from app.services.mcp_client_service import mcp_client_service, requires_confirmation, _make_namespaced

router = APIRouter()


# --- Request / Response models ---

class MCPServerCreate(BaseModel):
    name: str
    description: str = ""
    transport: str           # "http" | "sse" | "stdio"
    url: Optional[str] = None
    command: Optional[str] = None
    args: Optional[str] = None    # space-separated for stdio
    auth_type: str = "none"
    auth_value: Optional[str] = None   # plaintext; encrypted before storage


class ToolOverrideRequest(BaseModel):
    confirmation_override: Optional[bool] = None   # None=auto, True=always, False=never


def _server_to_response(server: MCPServer) -> dict:
    """Never include auth_value in responses."""
    return {
        "id": server.id,
        "name": server.name,
        "description": server.description,
        "transport": server.transport,
        "url": server.url,
        "command": server.command,
        "args": server.args,
        "auth_type": server.auth_type,
        "is_connected": server.is_connected,
        "last_connected_at": server.last_connected_at,
        "created_at": server.created_at,
    }


def _tool_to_response(tool: MCPTool, server_name: str) -> dict:
    return {
        "id": tool.id,
        "server_id": tool.server_id,
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "confirmation_override": tool.confirmation_override,
        "last_synced_at": tool.last_synced_at,
        "namespaced_name": _make_namespaced(server_name, tool.name),
        "requires_confirmation": requires_confirmation(tool),
    }


# --- Endpoints ---

@router.get("/servers")
async def list_servers(current_user: User = Depends(deps.get_current_user)) -> List[dict]:
    async with AsyncSessionLocal() as session:
        servers = (await session.exec(select(MCPServer))).all()
        return [_server_to_response(s) for s in servers]


@router.post("/servers")
async def create_server(
    body: MCPServerCreate,
    current_user: User = Depends(deps.get_current_user),
) -> dict:
    args_json = None
    if body.args and body.transport == "stdio":
        args_json = json.dumps(body.args.split())

    encrypted_auth = encrypt_secret(body.auth_value) if body.auth_value else None

    server = MCPServer(
        name=body.name,
        description=body.description,
        transport=body.transport,
        url=body.url,
        command=body.command,
        args=args_json,
        auth_type=body.auth_type,
        auth_value=encrypted_auth,
    )
    async with AsyncSessionLocal() as session:
        session.add(server)
        await session.commit()
        await session.refresh(server)

    # Auto-connect after creation
    connect_result = await mcp_client_service.connect(server.id)
    async with AsyncSessionLocal() as session:
        updated = await session.get(MCPServer, server.id)
        if not updated:
            return {"connect_result": connect_result}
        response = _server_to_response(updated)
    response["connect_result"] = connect_result
    return response


@router.put("/servers/{server_id}")
async def update_server(
    server_id: str,
    body: MCPServerCreate,
    current_user: User = Depends(deps.get_current_user),
) -> dict:
    async with AsyncSessionLocal() as session:
        server = await session.get(MCPServer, server_id)
        if not server:
            raise HTTPException(status_code=404, detail="MCP server not found")

        if body.transport == "stdio":
            args_json = json.dumps(body.args.split()) if body.args else server.args
        else:
            args_json = None  # Non-stdio transports don't use args

        server.name = body.name
        server.description = body.description
        server.transport = body.transport
        server.url = body.url
        server.command = body.command
        server.args = args_json
        server.auth_type = body.auth_type
        if body.auth_value:
            server.auth_value = encrypt_secret(body.auth_value)

        session.add(server)
        await session.commit()
        await session.refresh(server)
        return _server_to_response(server)


@router.delete("/servers/{server_id}")
async def delete_server(
    server_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> dict:
    async with AsyncSessionLocal() as session:
        server = await session.get(MCPServer, server_id)
        if not server:
            raise HTTPException(status_code=404, detail="MCP server not found")

        tools = (await session.exec(select(MCPTool).where(MCPTool.server_id == server_id))).all()
        for t in tools:
            await session.delete(t)
        await session.delete(server)
        await session.commit()
    return {"deleted": True}


@router.post("/servers/{server_id}/connect")
async def connect_server(
    server_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> dict:
    async with AsyncSessionLocal() as session:
        if not await session.get(MCPServer, server_id):
            raise HTTPException(status_code=404, detail="MCP server not found")
    result = await mcp_client_service.connect(server_id)
    async with AsyncSessionLocal() as session:
        server = await session.get(MCPServer, server_id)
        response = _server_to_response(server) if server else {}
    response["connect_result"] = result
    return response


@router.post("/servers/{server_id}/refresh")
async def refresh_server(
    server_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> dict:
    async with AsyncSessionLocal() as session:
        if not await session.get(MCPServer, server_id):
            raise HTTPException(status_code=404, detail="MCP server not found")
    result = await mcp_client_service.refresh(server_id)
    async with AsyncSessionLocal() as session:
        server = await session.get(MCPServer, server_id)
        response = _server_to_response(server) if server else {}
    response["connect_result"] = result
    return response


@router.get("/servers/{server_id}/tools")
async def list_tools(
    server_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> List[dict]:
    async with AsyncSessionLocal() as session:
        server = await session.get(MCPServer, server_id)
        if not server:
            raise HTTPException(status_code=404, detail="MCP server not found")
        tools = (await session.exec(select(MCPTool).where(MCPTool.server_id == server_id))).all()
        server_name = server.name
        return [_tool_to_response(t, server_name) for t in tools]


@router.put("/servers/{server_id}/tools/{tool_name}/override")
async def set_tool_override(
    server_id: str,
    tool_name: str,
    body: ToolOverrideRequest,
    current_user: User = Depends(deps.get_current_user),
) -> dict:
    async with AsyncSessionLocal() as session:
        # Verify server exists first
        server = await session.get(MCPServer, server_id)
        if not server:
            raise HTTPException(status_code=404, detail="MCP server not found")

        tool = (await session.exec(
            select(MCPTool).where(
                MCPTool.server_id == server_id,
                MCPTool.name == tool_name,
            )
        )).first()
        if not tool:
            raise HTTPException(status_code=404, detail="Tool not found")

        tool.confirmation_override = body.confirmation_override
        session.add(tool)
        await session.commit()
        await session.refresh(tool)
        server_name = server.name
        return _tool_to_response(tool, server_name)
