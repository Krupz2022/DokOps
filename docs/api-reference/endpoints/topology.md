# Topology

The **topology** is a live, visual map of how things in your cluster connect — nodes, pods, and services. There's a streaming endpoint that feeds the live graph and one to drill into a single node.

---

## GET /api/v1/topology/stream  *(streaming)*

**What this does:** Continuously streams a fresh snapshot of the cluster's dependency graph, refreshed every 10 seconds — this is what draws the live topology view.

**Auth required?** Token, but passed as a **query parameter** (not a header), because browser streaming connections can't send headers.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `token` | string | yes | Your JWT token (the same one you'd put in the `Authorization` header). |
| `cluster_context` | string | no | Which cluster to graph. Omit for the default. |

```bash
curl -N "http://localhost:8000/api/v1/topology/stream?token=$TOKEN&cluster_context=prod-cluster"
```

**Example stream:** Server-Sent Events, each `data:` line being a JSON `TopologySnapshot`:

```
data: {"nodes":[{"id":"pod/prod/api","kind":"pod","status":"Running"}],"edges":[{"from":"svc/prod/api","to":"pod/prod/api"}]}
data: {"nodes":[...],"edges":[...]}
```

| Field | Meaning |
|-------|---------|
| `nodes` | The boxes on the graph (pods, nodes, services). |
| `edges` | The lines connecting them (who talks to whom). |

**Common errors:** `401`/`422` if `token` is missing or invalid.

---

## GET /api/v1/topology/node/{kind}/{name}

**What this does:** Returns the full details for a single item on the graph (one pod, node, or service) — what you see when you click a box.

**Auth required?** Token (header or cookie).

**Path parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `kind` | string | yes | `pod`, `node`, or `service`. |
| `name` | string | yes | The item's name. |

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `namespace` | string | no | Namespace of the item (for pods/services). |
| `cluster_context` | string | no | Which cluster. |

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/topology/node/pod/payments-api-xyz?namespace=production"
```

**Example response (200):** a detailed object describing the item (status, labels, related resources, recent events).

**Common errors:** `404` if the item doesn't exist; `422` for a bad `kind`.
