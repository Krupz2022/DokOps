# Clusters

These endpoints let you **connect Kubernetes clusters** to DokOps — by uploading a kubeconfig, pasting a token, or importing from a cloud provider (AWS EKS / Azure AKS).

> **Shared note:** All endpoints require a token (any logged-in user). Deleting a cluster requires **God Mode**.
> *Cluster* (in plain terms) = one complete Kubernetes installation that runs your apps.

---

## GET /api/v1/clusters/

**What this does:** Lists all clusters that have been connected to DokOps.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/clusters/
```

**Example response (200):**

```json
[
  {
    "id": "cl_123",
    "name": "prod-cluster",
    "provider": "aks",
    "api_server": "https://prod.example.com:443",
    "namespace": "default",
    "added_by": "admin",
    "created_at": "2026-06-01T09:00:00Z",
    "last_verified": "2026-06-26T08:00:00Z"
  }
]
```

| Field | Meaning |
|-------|---------|
| `id` | Internal cluster ID (use it in other calls). |
| `name` | Friendly name. |
| `provider` | `aks`, `eks`, `generic`, etc. |
| `api_server` | The cluster's address. |
| `last_verified` | When DokOps last confirmed it could reach the cluster. |

---

## GET /api/v1/clusters/manifest

**What this does:** Returns a ready-to-apply Kubernetes manifest (used to deploy DokOps' in-cluster agent / RBAC).

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/clusters/manifest
```

**Example response (200):** YAML/text or a wrapped object containing the manifest.

---

## POST /api/v1/clusters/upload/kubeconfig

**What this does:** Connects a cluster by uploading its `kubeconfig` file (the standard credentials file `kubectl` uses).

**Auth required?** Token.

**Request body** (`multipart/form-data`):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `file` | file | yes | Your kubeconfig file. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -F "file=@/home/me/.kube/config" \
  http://localhost:8000/api/v1/clusters/upload/kubeconfig
```

**Example response (200):** the created cluster object (same shape as in the list above).

**Common errors:** `422` if the file is missing or not a valid kubeconfig.

---

## POST /api/v1/clusters/connect/token

**What this does:** Connects a cluster using its API server address and a service-account token (instead of a full kubeconfig).

**Auth required?** Token.

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | yes | – | Friendly name for the cluster. |
| `api_server` | string | yes | – | The cluster's API URL. |
| `token` | string | yes | – | A service-account bearer token for the cluster. |
| `provider` | string | no | `generic` | `aks`, `eks`, or `generic`. |
| `ca_cert` | string | no | – | The cluster's CA certificate (for TLS verification). |
| `namespace` | string | no | `default` | Default namespace to use. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/clusters/connect/token \
  -d '{"name":"prod","api_server":"https://prod:443","token":"eyJ...","provider":"generic"}'
```

**Example response (200):** the created cluster object.

---

## GET /api/v1/clusters/{cluster_id}/verify

**What this does:** Tests that DokOps can still reach a connected cluster, and updates its "last verified" time.

**Auth required?** Token. **Path:** `cluster_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/clusters/cl_123/verify
```

**Example response (200):** the cluster object with a fresh `last_verified`.

**Common errors:** `404` cluster not found; `502`/`500` if the cluster is unreachable.

---

## DELETE /api/v1/clusters/{cluster_id}

**What this does:** Removes a cluster from DokOps (does not delete the actual cluster, just disconnects it).

**Auth required?** **God Mode required.** **Path:** `cluster_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/clusters/cl_123
```

**Example response (200):** `{ "status": "deleted" }`

**Common errors:** `403` God Mode not active; `404` not found.

---

## POST /api/v1/clusters/cloud/credentials/azure

**What this does:** Saves Azure credentials so DokOps can later discover and import your AKS clusters.

**Auth required?** Token.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `subscription_id` | string | yes | Azure subscription ID. |
| `tenant_id` | string | yes | Azure tenant (directory) ID. |
| `client_id` | string | yes | App registration client ID. |
| `client_secret` | string | yes | App registration secret. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/clusters/cloud/credentials/azure \
  -d '{"subscription_id":"...","tenant_id":"...","client_id":"...","client_secret":"..."}'
```

**Example response (200):** `{ "id": "cred_az1", "provider": "azure", "added_by": "admin", "created_at": "..." }`

---

## POST /api/v1/clusters/cloud/credentials/aws

**What this does:** Saves AWS credentials so DokOps can later discover and import your EKS clusters.

**Auth required?** Token.

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `access_key_id` | string | yes | – | AWS access key ID. |
| `secret_access_key` | string | yes | – | AWS secret access key. |
| `region` | string | no | `us-east-1` | Default AWS region. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/clusters/cloud/credentials/aws \
  -d '{"access_key_id":"AKIA...","secret_access_key":"...","region":"us-west-2"}'
```

**Example response (200):** `{ "id": "cred_aws1", "provider": "aws", "added_by": "admin", "created_at": "..." }`

---

## GET /api/v1/clusters/cloud/{credential_id}/discover

**What this does:** Uses saved cloud credentials to list the clusters available in that cloud account (so you can pick which to import).

**Auth required?** Token. **Path:** `credential_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/clusters/cloud/cred_az1/discover
```

**Example response (200):** array of `{ "name": "prod-aks", "resource_group": "rg-prod", "region": "eastus" }` (Azure) or EKS equivalents.

---

## POST /api/v1/clusters/cloud/{credential_id}/import/aks

**What this does:** Imports a specific Azure AKS cluster into DokOps.

**Auth required?** Token. **Path:** `credential_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `cluster_name` | string | yes | The AKS cluster name. |
| `resource_group` | string | yes | The Azure resource group it lives in. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/clusters/cloud/cred_az1/import/aks \
  -d '{"cluster_name":"prod-aks","resource_group":"rg-prod"}'
```

**Example response (200):** the newly imported cluster object.

---

## POST /api/v1/clusters/cloud/{credential_id}/import/eks

**What this does:** Imports a specific AWS EKS cluster into DokOps.

**Auth required?** Token. **Path:** `credential_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `cluster_name` | string | yes | The EKS cluster name. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/clusters/cloud/cred_aws1/import/eks \
  -d '{"cluster_name":"prod-eks"}'
```

**Example response (200):** the newly imported cluster object.
