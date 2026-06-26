# MCP

MCP stands for **Model Context Protocol** — (in plain terms) a standard way to plug external "tool servers" into the AI so it can use their capabilities (e.g. a Jira tool server, a GitHub tool server). These endpoints manage those connections.

> **Shared note:** All endpoints require a token (any logged-in user).

---

## GET /api/v1/mcp/servers

**What this does:** Lists all connected (and saved) MCP servers.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/mcp/servers
```

**Example response (200):** array of `{ "id": "mcp_1", "name": "Jira", "transport": "http", "status": "connected", "tool_count": 8 }`.

---

## POST /api/v1/mcp/servers

**What this does:** Registers a new MCP server.

**Auth required?** Token.

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | yes | – | Friendly name. |
| `description` | string | no | – | What it provides. |
| `transport` | string | yes | – | How to reach it: `http`/`sse` (URL-based) or `stdio` (command-based). |
| `url` | string | no | – | The server URL (for `http`/`sse`). |
| `command` | string | no | – | The command to launch (for `stdio`). |
| `args` | string | no | – | Command arguments (for `stdio`). |
| `auth_type` | string | no | `none` | `none`, `bearer`, `header`, etc. |
| `auth_value` | string | no | – | The token/secret for `auth_type`. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/mcp/servers \
  -d '{"name":"Jira","transport":"http","url":"https://mcp.example.com","auth_type":"bearer","auth_value":"tok"}'
```

**Example response (200):** the created server object.

---

## PUT /api/v1/mcp/servers/{server_id}

**What this does:** Updates an MCP server's configuration.

**Auth required?** Token. **Path:** `server_id` (string, required).

**Request body** (JSON): same fields as Create above.

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/mcp/servers/mcp_1 \
  -d '{"name":"Jira Cloud","transport":"http","url":"https://mcp.example.com"}'
```

**Example response (200):** the updated server object.

---

## DELETE /api/v1/mcp/servers/{server_id}

**What this does:** Removes an MCP server connection.

**Auth required?** Token. **Path:** `server_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/mcp/servers/mcp_1
```

**Example response (200):** `{ "status": "deleted" }`

---

## POST /api/v1/mcp/servers/{server_id}/connect

**What this does:** Establishes (or re-establishes) the live connection to the MCP server.

**Auth required?** Token. **Path:** `server_id` (string, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/mcp/servers/mcp_1/connect
```

**Example response (200):** `{ "status": "connected", "tool_count": 8 }`

**Common errors:** `502`/`500` if the server can't be reached.

---

## POST /api/v1/mcp/servers/{server_id}/refresh

**What this does:** Re-fetches the list of tools the MCP server offers (in case they changed).

**Auth required?** Token. **Path:** `server_id` (string, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/mcp/servers/mcp_1/refresh
```

**Example response (200):** `{ "status": "refreshed", "tool_count": 9 }`

---

## GET /api/v1/mcp/servers/{server_id}/tools

**What this does:** Lists the tools a connected MCP server exposes.

**Auth required?** Token. **Path:** `server_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/mcp/servers/mcp_1/tools
```

**Example response (200):** array of `{ "name": "create_issue", "description": "...", "requires_confirmation": true }`.

---

## PUT /api/v1/mcp/servers/{server_id}/tools/{tool_name}/override

**What this does:** Overrides whether a specific MCP tool requires human confirmation before it runs.

**Auth required?** Token.

**Path parameters:** `server_id`, `tool_name` (string, required).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `confirmation_override` | boolean | no | `true` = always require confirmation; `false` = never; omit/null = use the tool's default. |

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/mcp/servers/mcp_1/tools/create_issue/override \
  -d '{"confirmation_override": true}'
```

**Example response (200):** the updated tool object.
