# Integrations (Azure)

These endpoints connect DokOps to **Microsoft Azure** so it can pull in cost data, resource inventory, monitoring metrics, anomalies, and cost-saving recommendations.

> **Shared note:** All endpoints require a token (any logged-in user).

---

## POST /api/v1/integrations/azure/connect

**What this does:** Saves your Azure credentials and connects the integration.

**Auth required?** Token.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `tenant_id` | string | yes | Azure tenant (directory) ID. |
| `subscription_id` | string | yes | Azure subscription ID. |
| `client_id` | string | yes | App registration client ID. |
| `client_secret` | string | yes | App registration secret. |
| `resource_group` | string | no | Limit to one resource group. |
| `aks_cluster_name` | string | no | A specific AKS cluster to associate. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/integrations/azure/connect \
  -d '{"tenant_id":"...","subscription_id":"...","client_id":"...","client_secret":"..."}'
```

**Example response (200):** `{ "status": "connected" }`

---

## POST /api/v1/integrations/azure/test

**What this does:** Verifies the saved Azure credentials actually work.

**Auth required?** Token. No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/integrations/azure/test
```

**Example response (200):** `{ "success": true }`

---

## DELETE /api/v1/integrations/azure/disconnect

**What this does:** Disconnects Azure and removes saved credentials.

**Auth required?** Token.

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/integrations/azure/disconnect
```

**Example response (200):** `{ "status": "disconnected" }`

---

## GET /api/v1/integrations/azure/status

**What this does:** Shows whether Azure is connected and which features are enabled.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/integrations/azure/status
```

**Example response (200):** `{ "connected": true, "features": { "cost": true, "monitor": true } }`

---

## PATCH /api/v1/integrations/azure/features/{feature_key}

**What this does:** Turns one Azure feature on or off (e.g. cost analysis, monitoring).

**Auth required?** Token.

**Path parameters:** `feature_key` (string, required) — e.g. `cost`, `monitor`, `anomalies`.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `enabled` | boolean | yes | `true` to enable, `false` to disable. |

```bash
curl -X PATCH -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/integrations/azure/features/cost \
  -d '{"enabled": true}'
```

**Example response (200):** `{ "feature": "cost", "enabled": true }`

---

## GET /api/v1/integrations/azure/cost

**What this does:** Returns Azure cost/spending data.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/integrations/azure/cost
```

**Example response (200):** an object of cost breakdowns (by service, by day, totals).

---

## GET /api/v1/integrations/azure/resources

**What this does:** Lists your Azure resources (VMs, storage, etc.).

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/integrations/azure/resources
```

**Example response (200):** an object/array of Azure resources.

---

## GET /api/v1/integrations/azure/monitor

**What this does:** Returns Azure Monitor metrics (performance/health data).

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/integrations/azure/monitor
```

**Example response (200):** a metrics object.

---

## GET /api/v1/integrations/azure/anomalies

**What this does:** Returns detected anomalies (unusual spikes in cost or usage).

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/integrations/azure/anomalies
```

**Example response (200):** an object listing anomalies.

---

## GET /api/v1/integrations/azure/recommendations

**What this does:** Returns cost-saving / best-practice recommendations from Azure Advisor.

**Auth required?** Token.

**Query parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `triggered_by` | string | no | `ui` | Where the request came from (used for analytics). |

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/integrations/azure/recommendations?triggered_by=ui"
```

**Example response (200):** an object of recommendations.

---

## POST /api/v1/integrations/azure/analyze-resources

**What this does:** Runs an AI analysis over your Azure resources to surface insights.

**Auth required?** Token. No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/integrations/azure/analyze-resources
```

**Example response (200):** an AI-generated analysis object.

**Common errors (this group):** `401` not authenticated; `400`/`502` if Azure isn't connected or credentials are wrong.
