# MCP Servers

DokOps can connect to external **Model Context Protocol (MCP)** servers. This lets the AI use tools from any MCP-compatible service — Jira, GitHub, database query tools, custom scripts — without code changes to DokOps.

---

## What is MCP?

The Model Context Protocol (MCP) is an open standard for exposing tools to AI systems. Any service that implements the MCP server spec can be discovered and used by the AI in DokOps's chat.

Popular MCP servers:
- **Jira MCP** — create/update/search issues
- **GitHub MCP** — list PRs, create issues, check CI status
- **Database MCP** — run read-only SQL queries
- **Slack MCP** — post messages, read channels
- **Custom scripts** — wrap any CLI command as an MCP tool

---

## Registering an MCP Server

1. Click **MCP Servers** in the sidebar.
2. Click **Add Server**.
3. Fill in:

```
Name:    jira-mcp
URL:     http://jira-mcp.internal:3000
Token:   (optional auth token for the MCP server)
```

4. Click **Connect** — DokOps calls the MCP server's `list_tools` endpoint and stores the tool schemas.
5. The registered tools appear in the **Tools** tab of the server card.

---

## Tool Discovery

After connecting, click **Refresh Tools** to re-discover tools from the server. This is useful when the MCP server adds new tools.

Tools are displayed with:
- **Name** — the tool identifier the AI will call
- **Description** — human-readable description (used for AI tool selection)
- **Input Schema** — the parameters the tool accepts

---

## Tool Overrides

You can customize how an MCP tool is presented to the AI:

1. Click the **Edit** icon next to a tool.
2. Modify:
   - **Override Description** — change how the AI decides when to use this tool
   - **Enabled** — toggle the tool on/off without disconnecting the server

This is useful when a generic tool description causes the AI to misuse it.

---

## Using MCP Tools in AI Chat

Once registered, MCP tools are automatically available in the AI chat alongside built-in K8s tools:

```
User: "Create a Jira ticket for the OOMKilled pod in payments"

AI: [Step] Calling jira_create_issue...
    {
      "project": "OPS",
      "issuetype": "Bug",
      "summary": "payments-api pod OOMKilled in production",
      "description": "Pod payments-api-6d9f7b was OOMKilled at 14:32 UTC.
                      Memory limit: 128Mi, actual usage exceeded limit.
                      Node: worker-2 (Memory: 78% utilized).
                      Recommended fix: increase limit to 256Mi.",
      "priority": "High",
      "labels": ["kubernetes", "production", "oom"]
    }

    Created ticket: OPS-4821 (https://jira.example.com/browse/OPS-4821)
```

---

## Example: GitHub MCP Integration

```bash
# Start the official GitHub MCP server
npx -y @github/mcp-server --port 3001

# Register it in DokOps
curl -X POST http://localhost:8000/api/v1/mcp/servers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "github-mcp",
    "url": "http://localhost:3001",
    "auth_token": "ghp_..."
  }'
```

Now in chat:

```
User: "Check if there are any failing CI checks on the main branch of my-app"

AI: [Step] Calling github_list_check_runs for repo 'my-app', branch 'main'...

    Check runs:
    ✅ lint         — passed
    ✅ unit-tests   — passed
    ❌ integration  — failed (exit 1)
    ✅ build        — passed

    The integration test run failed. Click here to view details: [link]
```

---

## MCP Server Health

From the MCP Servers page:
- **Connected** (green) — server is reachable and tools are loaded
- **Disconnected** (red) — server is not reachable (click Reconnect to retry)
- **Stale** (yellow) — tools haven't been refreshed in > 24 hours

---

## Via API

```bash
# List all registered MCP servers
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/mcp/servers

# Register a new server
curl -X POST http://localhost:8000/api/v1/mcp/servers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-mcp", "url": "http://my-mcp:3000", "auth_token": "secret"}'

# Refresh tools from a server
curl -X POST http://localhost:8000/api/v1/mcp/servers/{id}/refresh \
  -H "Authorization: Bearer $TOKEN"

# List tools from a server
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/mcp/servers/{id}/tools
```
