import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

from app.core.datetimes import utc_field, utc_optional_field


class MCPServer(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str
    description: str = ""
    transport: str                       # "http" | "sse" | "stdio"
    url: Optional[str] = None            # for http / sse
    command: Optional[str] = None        # for stdio
    args: Optional[str] = None           # for stdio — JSON array string
    auth_type: str = "none"              # "none" | "bearer" | "api_key" | "basic"
    auth_value: Optional[str] = None     # Fernet-encrypted
    is_connected: bool = False
    last_connected_at: Optional[datetime] = utc_optional_field()
    created_at: datetime = utc_field()


class MCPTool(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    server_id: str = Field(foreign_key="mcpserver.id", index=True)
    name: str
    description: str = ""
    input_schema: str                    # JSON string of MCP inputSchema
    confirmation_override: Optional[bool] = None   # None=heuristic, True=always, False=never
    last_synced_at: Optional[datetime] = utc_optional_field()
