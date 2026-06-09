# Helm Deployment

DokOps ships two Helm charts for Kubernetes deployment:

| Chart | Path | Use Case |
|-------|------|----------|
| `dokops` | `deployment/helm/dokops/` | Production: 4 separate pods (backend, frontend, ChromaDB, PostgreSQL) |
| `dokops-aio` | `deployment/helm/dokops-aio/` | All-in-one single pod (staging/demo) |

---

## 4-Service Chart (Production)

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Kubernetes Namespace: dokops          │
│                                                         │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────┐ │
│  │ frontend │   │ backend  │   │chromadb  │   │  pg  │ │
│  │ (nginx)  │──▶│ (fastapi)│──▶│(vector)  │   │ (db) │ │
│  │  :3000   │   │  :8000   │──▶│  :8000   │   │:5432 │ │
│  └──────────┘   └──────────┘   └──────────┘   └──────┘ │
│        │               │                                 │
│      Ingress       ServiceAccount                        │
│   (external TLS)   (ClusterRole)                         │
└─────────────────────────────────────────────────────────┘
```

### Prerequisites

```bash
# Create namespace
kubectl create namespace dokops

# Create secrets (recommended over --set for sensitive values)
kubectl create secret generic dokops-secrets \
  --namespace dokops \
  --from-literal=auth-secret-key="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
  --from-literal=admin-password="yourpassword" \
  --from-literal=ai-api-key="sk-..." \
  --from-literal=db-password="dbpassword"
```

### Install

```bash
helm install dokops ./deployment/helm/dokops \
  --namespace dokops \
  --values my-values.yaml
```

### values.yaml Example

```yaml
# my-values.yaml

backend:
  replicaCount: 2
  image:
    repository: ghcr.io/your-org/dokops-backend
    tag: "latest"
  env:
    AI_PROVIDER: "OPENAI"
    K8S_IN_CLUSTER_CONFIG: "true"
    LOG_RAG_ENABLED: "true"
    LOG_RAG_USE_LOCAL_CHROMA: "false"
    DOKOPS_SIGNUP_ENABLED: "false"
    DOKOPS_SIGNUP_DEFAULT_ROLE: "viewer"
    # Secrets from Kubernetes Secret
    AUTH_SECRET_KEY:
      valueFrom:
        secretKeyRef:
          name: dokops-secrets
          key: auth-secret-key
    DOKOPS_ADMIN_PASSWORD:
      valueFrom:
        secretKeyRef:
          name: dokops-secrets
          key: admin-password
    OPENAI_API_KEY:
      valueFrom:
        secretKeyRef:
          name: dokops-secrets
          key: ai-api-key

frontend:
  replicaCount: 1
  image:
    repository: ghcr.io/your-org/dokops-frontend
    tag: "latest"

postgres:
  enabled: true
  auth:
    database: dokops
    username: dokops
    existingSecret: dokops-secrets
    secretKeys:
      userPasswordKey: db-password
  primary:
    persistence:
      size: 10Gi

chromadb:
  enabled: true
  persistence:
    size: 20Gi

ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: dokops.example.com
      paths:
        - path: /
          pathType: Prefix
          service: frontend
        - path: /api
          pathType: Prefix
          service: backend
  tls:
    - secretName: dokops-tls
      hosts:
        - dokops.example.com

rbac:
  create: true      # Creates ClusterRole and ClusterRoleBinding for K8s access

serviceAccount:
  create: true
  name: dokops
```

### Upgrade

```bash
helm upgrade dokops ./deployment/helm/dokops \
  --namespace dokops \
  --values my-values.yaml
```

### Rollback

```bash
helm history dokops -n dokops
helm rollback dokops 2 -n dokops  # roll back to revision 2
```

---

## All-in-One Chart (Staging/Demo)

```bash
helm install dokops-demo ./deployment/helm/dokops-aio \
  --namespace dokops-demo \
  --create-namespace \
  --set backend.env.AUTH_SECRET_KEY="your-secret" \
  --set backend.env.DOKOPS_ADMIN_USERNAME="admin" \
  --set backend.env.DOKOPS_ADMIN_PASSWORD="demo-password" \
  --set backend.env.AI_PROVIDER="GEMINI" \
  --set backend.env.GEMINI_API_KEY="your-key" \
  --set backend.env.K8S_IN_CLUSTER_CONFIG="true"
```

---

## RBAC for Cluster Access

The chart creates a `ServiceAccount`, `ClusterRole`, and `ClusterRoleBinding` for DokOps to access your cluster:

```yaml
# Created by the chart when rbac.create=true
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: dokops
rules:
  # Read-only (Normal Mode)
  - apiGroups: ["", "apps", "batch", "networking.k8s.io", "storage.k8s.io"]
    resources: ["*"]
    verbs: ["get", "list", "watch"]
  # Write (God Mode)
  - apiGroups: ["", "apps"]
    resources: ["pods", "deployments", "deployments/scale", "namespaces"]
    verbs: ["create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["pods/exec", "pods/log"]
    verbs: ["create", "get"]
```

If `rbac.create=false`, create the ServiceAccount and bindings manually before installing.

---

## Persistent Storage

The chart creates PersistentVolumeClaims for:

| Component | PVC | Default Size |
|-----------|-----|-------------|
| PostgreSQL | `postgres-data` | 10Gi |
| ChromaDB | `chroma-data` | 20Gi |

Ensure your cluster has a StorageClass that supports `ReadWriteOnce`.

```bash
kubectl get storageclass
# NAME                 PROVISIONER               RECLAIMPOLICY
# standard (default)   kubernetes.io/gce-pd      Delete
```

Specify in values.yaml:

```yaml
postgres:
  primary:
    persistence:
      storageClass: standard
      size: 10Gi

chromadb:
  persistence:
    storageClass: standard
    size: 20Gi
```

---

## Health Checks

After installation:

```bash
# Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app=dokops-backend -n dokops --timeout=120s

# Check health endpoint
kubectl port-forward svc/dokops-backend 8000:8000 -n dokops &
curl http://localhost:8000/health
```

---

## Uninstall

```bash
helm uninstall dokops -n dokops

# Remove PVCs (caution: deletes persistent data)
kubectl delete pvc -l app=dokops -n dokops
kubectl delete namespace dokops
```
