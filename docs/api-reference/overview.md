# API Reference Overview

DokOps exposes a REST API at `http://localhost:8000/api/v1/`. Interactive Swagger documentation is available at `http://localhost:8000/docs`.

---

## Authentication

All endpoints (except `/api/v1/auth/login/access-token` and `/api/v1/auth/register`) require a JWT bearer token:

```
Authorization: Bearer <your-token>
```

### Get a Token

```bash
curl -X POST http://localhost:8000/api/v1/auth/login/access-token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=yourpassword"

# Response
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

Store the token:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login/access-token \
  -d "username=admin&password=yourpassword" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

---

## Base URL

| Environment | Base URL |
|-------------|----------|
| Local dev | `http://localhost:8000/api/v1` |
| Docker Compose | `http://localhost:8000/api/v1` |
| Kubernetes (in-cluster) | `http://dokops-backend.dokops.svc.cluster.local/api/v1` |
| External (via Ingress) | `https://dokops.example.com/api/v1` |

---

## Response Format

All responses return JSON. Successful responses use HTTP 2xx:

```json
{
  "id": 1,
  "name": "my-cluster",
  "status": "verified"
}
```

Error responses:

```json
{
  "detail": "Cluster not found"
}
```

Or with validation errors:

```json
{
  "detail": [
    {
      "loc": ["body", "username"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## HTTP Status Codes

| Code | Meaning |
|------|---------|
| `200` | Success |
| `201` | Created |
| `204` | No content (delete success) |
| `400` | Bad request (validation error) |
| `401` | Unauthorized (missing or invalid token) |
| `403` | Forbidden (insufficient role or God Mode not enabled) |
| `404` | Not found |
| `422` | Unprocessable entity (request body validation failed) |
| `500` | Internal server error |

---

## Pagination

List endpoints support pagination via query parameters:

```
GET /api/v1/audit?limit=50&offset=100
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `limit` | `100` | Max items to return |
| `offset` | `0` | Items to skip |

---

## Endpoint Groups

| Group | Prefix | Description |
|-------|--------|-------------|
| Auth | `/auth` | Login, register, SSO |
| System | `/system` | Status, settings, setup, God Mode |
| Dashboard | `/dashboard` | Cluster stats and metrics |
| Kubernetes | `/k8s` | All K8s resource operations |
| AI | `/ai` | AI config, diagnostics, runbooks |
| Chat | `/chat` | Conversation CRUD, streaming messages |
| Clusters | `/clusters` | Multi-cluster management |
| Tools | `/tools` | Toolsets and env vars |
| Operations | `/operations` | Pending operation queue |
| Topology | `/topology` | Dependency graph |
| Integrations | `/integrations` | Azure and observability |
| RAG | `/rag` | Knowledge base documents |
| Workflows | `/workflows` | Workflow CRUD and execution |
| MCP | `/mcp` | MCP server management |
| Minions | `/minions` | Remote agent fleet |
| Organisations | `/organisations` | Org and group management |
| Patching | `/patches` | Patch compliance and pipelines |
| Audit | `/audit` | Mutation audit log |
| Users | `/users` | User profile |
| SSO | `/auth/sso` | OAuth2 flows |
| Activation | `/activation` | License management |
| CLI Tools | `/system/cli-tools` | CLI tool management |

---

## Swagger UI

The full interactive API documentation is at:

```
http://localhost:8000/docs
```

You can authenticate in Swagger by clicking **Authorize** and entering your Bearer token. All endpoints can be tested directly from the browser.

---

## Health Check

```bash
curl http://localhost:8000/health
# {"status": "ok", "db": "connected", "k8s": "connected"}
```

---

## Streaming Endpoints (SSE)

Some endpoints use Server-Sent Events for streaming responses:

| Endpoint | Description |
|----------|-------------|
| `POST /ai/diagnose/stream` | Stream AI diagnostic response |
| `POST /ai/global/stream` | Stream AI chat response |
| `GET /topology/stream` | Stream topology graph build |
| `POST /minions/{id}/jobs` | Stream job output from a minion |

SSE events are newline-delimited JSON:

```bash
curl -N -H "Authorization: Bearer $TOKEN" \
  -X POST http://localhost:8000/api/v1/ai/global/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "What pods are failing?", "conversation_id": "123"}'

# Stream output:
data: {"type": "step", "content": "Listing pods in all namespaces..."}
data: {"type": "step", "content": "Found 2 pods in Error state..."}
data: {"type": "text", "content": "The following pods are failing:..."}
data: {"type": "done"}
```

---

## Example: Full Workflow via API

```bash
# 1. Authenticate
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login/access-token \
  -d "username=admin&password=password" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. Check cluster health
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/k8s/cluster/health | python3 -m json.tool

# 3. List failing pods
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/k8s/namespaces/production/pods" | \
  python3 -c "import sys,json; pods=json.load(sys.stdin); [print(p['name'], p['status']) for p in pods if p['status'] != 'Running']"

# 4. Get logs from a failing pod
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/k8s/namespaces/production/pods/payments-api-xyz/logs?tail=50"

# 5. Stream AI diagnosis
curl -N -H "Authorization: Bearer $TOKEN" \
  -X POST http://localhost:8000/api/v1/ai/diagnose/stream \
  -H "Content-Type: application/json" \
  -d '{"namespace": "production", "pod_name": "payments-api-xyz"}'
```
