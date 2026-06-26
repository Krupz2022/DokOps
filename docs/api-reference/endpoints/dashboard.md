# Dashboard

The numbers and charts you see on the DokOps home screen come from these two endpoints.

> **Shared note:** Both endpoints accept an optional `X-Cluster-Context` header to choose *which* cluster the numbers are for. Leave it out to use the active/default cluster. (in plain terms: which Kubernetes cluster you're looking at.)

---

## GET /api/v1/dashboard/stats

**What this does:** Returns the headline cluster statistics — counts of pods, deployments, nodes, namespaces, how many are healthy vs. failing, and so on.

**Auth required?** Token (any logged-in user).

**Headers:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `X-Cluster-Context` | string | no | Which cluster to report on. Omit for the default. |

**curl example:**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  -H "X-Cluster-Context: prod-cluster" \
  http://localhost:8000/api/v1/dashboard/stats
```

**Example response (200):** an object of counts/summaries, for example:

```json
{
  "namespaces": 12,
  "pods": { "total": 84, "running": 80, "failing": 4 },
  "deployments": 30,
  "nodes": 5
}
```

(Exact fields depend on your cluster; the values describe overall cluster health.)

**Common errors:** `401` not authenticated; `422` bad header value.

---

## GET /api/v1/dashboard/metrics

**What this does:** Returns per-node resource metrics — how much CPU and memory each machine in the cluster is using.

**Auth required?** Token (any logged-in user).

**Headers:** `X-Cluster-Context` (optional, same as above).

**curl example:**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/dashboard/metrics
```

**Example response (200):**

```json
{
  "nodes": [
    { "name": "node-1", "cpu_percent": 42, "memory_percent": 67 },
    { "name": "node-2", "cpu_percent": 18, "memory_percent": 51 }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `nodes[].name` | The machine's name. |
| `nodes[].cpu_percent` | How busy its processor is (0–100). |
| `nodes[].memory_percent` | How full its memory is (0–100). |

**Note:** Metrics depend on the cluster's metrics-server being installed; if it isn't, values may be empty.
