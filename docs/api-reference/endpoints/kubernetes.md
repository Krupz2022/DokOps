# Kubernetes

These endpoints let you **look at and control your Kubernetes cluster** — the system that runs your containerized apps. Read-only endpoints (listing pods, viewing logs) just need a token. Anything that changes or deletes things needs **God Mode**.

> **Shared notes for this group:**
> - All endpoints accept an optional `X-Cluster-Context` header to pick which cluster to talk to. Omit it for the active/default cluster.
> - **Plain-terms glossary:**
>   - *Namespace* = a folder that separates groups of apps in a cluster.
>   - *Pod* = the smallest running unit; usually one running container (your app).
>   - *Deployment* = a manager that keeps a set of identical pods running.
>   - *Service* = a stable network address that points at a set of pods.
>   - *ConfigMap* = a bag of plain-text settings for an app.
>   - *Secret* = like a ConfigMap but for sensitive values (passwords, keys).

---

## GET /api/v1/k8s/namespaces

**What this does:** Lists all namespaces (folders) in the cluster.

**Auth required?** Token. **Headers:** `X-Cluster-Context` (optional).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/k8s/namespaces
```

**Example response (200):** `["default", "kube-system", "production", "staging"]`

---

## GET /api/v1/k8s/cluster/health

**What this does:** Returns a health report for the whole cluster (nodes ready, problem pods, etc.).

**Auth required?** Token. **Headers:** `X-Cluster-Context` (optional).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/k8s/cluster/health
```

**Example response (200):**

```json
{ "healthy": true, "nodes_ready": 5, "nodes_total": 5, "problem_pods": [] }
```

---

## GET /api/v1/k8s/namespaces/{namespace}/pods

**What this does:** Lists all pods (running app instances) in one namespace.

**Auth required?** Token.

**Path parameters:** `namespace` (string, required) — the folder name.

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/k8s/namespaces/production/pods
```

**Example response (200):** an array of pod objects:

```json
[
  { "name": "payments-api-abc", "status": "Running", "restarts": 0, "node": "node-1" },
  { "name": "payments-api-xyz", "status": "CrashLoopBackOff", "restarts": 12, "node": "node-2" }
]
```

| Field | Meaning |
|-------|---------|
| `name` | The pod's name. |
| `status` | `Running`, `Pending`, `CrashLoopBackOff` (keeps crashing), etc. |
| `restarts` | How many times it has restarted (high = trouble). |
| `node` | Which machine it runs on. |

**Common errors:** `404` namespace not found.

---

## GET /api/v1/k8s/namespaces/{namespace}/pods/{pod_name}/logs

**What this does:** Fetches the recent log output (the text an app prints) from a pod — the first place to look when something is broken.

**Auth required?** Token.

**Path parameters:** `namespace`, `pod_name` (both string, required).

**Query parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `tail_lines` | integer | no | `100` | How many of the most recent log lines to return. |

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/k8s/namespaces/production/pods/payments-api-xyz/logs?tail_lines=50"
```

**Example response (200):** `{ "logs": "2026-06-26 10:00:01 ERROR Could not connect to database...\n..." }`

---

## DELETE /api/v1/k8s/namespaces/{namespace}/pods/{pod_name}

**What this does:** Deletes a pod. Kubernetes usually recreates it automatically, so this is a common way to "restart" a stuck app.

**Auth required?** **God Mode required.**

**Path parameters:** `namespace`, `pod_name` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/k8s/namespaces/production/pods/payments-api-xyz
```

**Example response (200):** `{ "status": "deleted", "pod": "payments-api-xyz" }`

**Common errors:** `403` God Mode not active; `404` pod not found.

---

## GET /api/v1/k8s/namespaces/{namespace}/deployments

**What this does:** Lists deployments (pod managers) in a namespace.

**Auth required?** Token. **Path:** `namespace` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/k8s/namespaces/production/deployments
```

**Example response (200):** array of `{ "name": "payments-api", "replicas": 3, "ready": 3, "image": "..." }`.

---

## POST /api/v1/k8s/namespaces/{namespace}/deployments

**What this does:** Creates a new deployment from a Kubernetes manifest you provide.

**Auth required?** **God Mode required.**

**Path parameters:** `namespace` (string, required).

**Request body** (JSON): a free-form object — the deployment manifest/spec (the standard Kubernetes deployment definition).

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/k8s/namespaces/production/deployments \
  -d '{ "metadata": {"name": "hello"}, "spec": { "replicas": 1, "...": "..." } }'
```

**Example response (200):** `{ "status": "created", "deployment": "hello" }`

**Common errors:** `403` God Mode not active; `422` invalid manifest.

---

## POST /api/v1/k8s/namespaces/{namespace}/deployments/{deployment_name}/scale

**What this does:** Changes how many copies (replicas) of an app run — scale up for more capacity, down to save resources.

**Auth required?** **God Mode required.**

**Path parameters:** `namespace`, `deployment_name` (string, required).

**Request body** (JSON): an object with the desired replica count, e.g. `{"replicas": 5}`.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/k8s/namespaces/production/deployments/payments-api/scale \
  -d '{"replicas": 5}'
```

**Example response (200):** `{ "status": "scaled", "replicas": 5 }`

---

## POST /api/v1/k8s/namespaces/{namespace}/deployments/{deployment_name}/restart

**What this does:** Performs a rolling restart of a deployment (replaces its pods gracefully, no downtime if configured).

**Auth required?** **God Mode required.**

**Path parameters:** `namespace`, `deployment_name` (string, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/k8s/namespaces/production/deployments/payments-api/restart
```

**Example response (200):** `{ "status": "restarted" }`

---

## DELETE /api/v1/k8s/namespaces/{namespace}/deployments/{deployment_name}

**What this does:** Deletes a deployment (and the pods it manages stop).

**Auth required?** **God Mode required.**

**Path parameters:** `namespace`, `deployment_name` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/k8s/namespaces/production/deployments/payments-api
```

**Example response (200):** `{ "status": "deleted" }`

---

## GET /api/v1/k8s/namespaces/{namespace}/services

**What this does:** Lists services (stable network addresses) in a namespace.

**Auth required?** Token. **Path:** `namespace` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/k8s/namespaces/production/services
```

**Example response (200):** array of `{ "name": "payments-api", "type": "ClusterIP", "cluster_ip": "10.0.0.5", "ports": [80] }`.

---

## GET /api/v1/k8s/namespaces/{namespace}/configmaps

**What this does:** Lists configmaps (plain-text settings bundles) in a namespace.

**Auth required?** Token. **Path:** `namespace` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/k8s/namespaces/production/configmaps
```

**Example response (200):** array of configmap summaries.

---

## GET /api/v1/k8s/namespaces/{namespace}/configmaps/{name}

**What this does:** Shows the full contents of one configmap.

**Auth required?** Token. **Path:** `namespace`, `name` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/k8s/namespaces/production/configmaps/app-config
```

**Example response (200):** `{ "name": "app-config", "data": { "LOG_LEVEL": "info", "TIMEOUT": "30" } }`

---

## PATCH /api/v1/k8s/namespaces/{namespace}/configmaps/{name}

**What this does:** Changes one or more settings inside a configmap.

**Auth required?** **God Mode required.**

**Path parameters:** `namespace`, `name` (string, required).

**Request body** (JSON): an object with the keys/values to set, e.g. `{"data": {"LOG_LEVEL": "debug"}}`.

```bash
curl -X PATCH -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/k8s/namespaces/production/configmaps/app-config \
  -d '{"data": {"LOG_LEVEL": "debug"}}'
```

**Example response (200):** the updated configmap.

---

## GET /api/v1/k8s/namespaces/{namespace}/secrets

**What this does:** Lists secrets (sensitive settings) in a namespace. Values are not exposed in plain text by the UI.

**Auth required?** Token. **Path:** `namespace` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/k8s/namespaces/production/secrets
```

**Example response (200):** array of secret summaries (names/types, not raw values).

---

## DELETE /api/v1/k8s/namespaces/{name}

**What this does:** Deletes an entire namespace — and **everything inside it**. Very destructive.

**Auth required?** **God Mode required.**

**Path parameters:** `name` (string, required) — the namespace to delete.

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/k8s/namespaces/staging
```

**Example response (200):** `{ "status": "deleting", "namespace": "staging" }`

**Common errors:** `403` God Mode not active; `404` namespace not found.

---

## GET /api/v1/k8s/pods/search

**What this does:** Searches for pods by name across all namespaces at once.

**Auth required?** Token.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query` | string | yes | Text to search pod names for. |

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/k8s/pods/search?query=payments"
```

**Example response (200):** array of matching pods with their namespace, e.g. `[{ "namespace": "production", "name": "payments-api-xyz", "status": "Running" }]`.

**Common errors:** `422` if `query` is missing.
