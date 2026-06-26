# Integrations (Observability)

These endpoints connect DokOps to **observability backends** — the systems that store your metrics, logs, and dashboards: Prometheus, Loki, Grafana, Elasticsearch, and Datadog. Once connected, the AI can query them.

> **Shared note:** All endpoints require a token (any logged-in user).

---

## GET /api/v1/integrations/obs/

**What this does:** Lists all connected observability integrations.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/integrations/obs/
```

**Example response (200):**

```json
[
  {
    "id": 1,
    "backend": "prometheus",
    "display_name": "Prod Prometheus",
    "base_url": "https://prom.example.com",
    "auth_type": "none",
    "is_active": true,
    "health_status": "ok",
    "connected_at": "2026-06-01T09:00:00Z"
  }
]
```

| Field | Meaning |
|-------|---------|
| `id` | Integration ID. |
| `backend` | Which system: `prometheus`, `loki`, `grafana`, `elasticsearch`, `datadog`. |
| `display_name` | Friendly name you gave it. |
| `base_url` | Its address. |
| `health_status` | Last health check result. |

---

## POST /api/v1/integrations/obs/connect

**What this does:** Connects a new observability backend.

**Auth required?** Token.

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `backend` | string (enum) | yes | – | One of `prometheus`, `loki`, `grafana`, `elasticsearch`, `datadog`. |
| `display_name` | string | yes | – | Friendly name. |
| `base_url` | string | yes | – | The backend's URL. |
| `auth_type` | string | no | `none` | How to authenticate (`none`, `basic`, `bearer`, etc.). |
| `credentials` | object | no | – | Auth details (username/password, token, API key). |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/integrations/obs/connect \
  -d '{"backend":"prometheus","display_name":"Prod Prometheus","base_url":"https://prom.example.com","auth_type":"none"}'
```

**Example response (200):** the created integration object (same shape as the list above).

**Common errors:** `422` invalid `backend` value or missing fields.

---

## POST /api/v1/integrations/obs/{integration_id}/test

**What this does:** Tests that a connected integration is reachable and working.

**Auth required?** Token. **Path:** `integration_id` (integer, required).

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/integrations/obs/1/test
```

**Example response (200):** `{ "success": true, "health_status": "ok" }`

**Common errors:** `404` integration not found.

---

## DELETE /api/v1/integrations/obs/{integration_id}

**What this does:** Disconnects and removes an observability integration.

**Auth required?** Token. **Path:** `integration_id` (integer, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/integrations/obs/1
```

**Example response (200):** `{ "status": "deleted" }`

---

## GET /api/v1/integrations/obs/debug/registry

**What this does:** Diagnostic endpoint — shows which tools the integration manager actually loaded. Useful when a tool seems "missing".

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/integrations/obs/debug/registry
```

**Example response (200):** an object listing loaded tools per backend.
