# Production Checklist

Use this guide before going to production with DokOps.

---

## Security

### 1. Rotate `AUTH_SECRET_KEY`

The default is `changethis`. Generate a proper random key:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
# Example: a1b2c3d4e5f6...
```

Set it as an environment variable or Kubernetes secret. **Do not change this after initial setup** without re-entering all encrypted credentials.

### 2. Use HTTPS

All traffic must be over TLS:
- Use a reverse proxy (Nginx, Traefik, AWS ALB) for TLS termination.
- Or use cert-manager in Kubernetes for automatic Let's Encrypt certificates.

Update CORS settings:

```env
BACKEND_CORS_ORIGINS=https://dokops.example.com
FRONTEND_URL=https://dokops.example.com
BACKEND_PUBLIC_URL=https://dokops.example.com
```

### 3. Shorten Token Expiry

```env
ACCESS_TOKEN_EXPIRE_MINUTES=480   # 8 hours (or less)
```

### 4. Disable Self-Registration

```env
DOKOPS_SIGNUP_ENABLED=false
```

Use [SSO](../security/authentication.md) or create accounts manually.

### 5. Least-Privilege K8s RBAC

The DokOps service account should only have permissions it actually needs. Review the ClusterRole and remove any verbs or resources not in use.

---

## Database

### Use PostgreSQL (Not SQLite)

SQLite is not suitable for production (no concurrent writes, single-file backup complexity):

```env
DATABASE_URL=postgresql://dokops:strongpassword@postgres-host:5432/dokops
```

### Back Up the Database

Set up automated daily backups:

```bash
# PostgreSQL backup
pg_dump -h postgres-host -U dokops -d dokops > backup-$(date +%Y%m%d).sql

# Or in Kubernetes via CronJob
```

---

## Kubernetes Deployment

### Run Multiple Backend Replicas

```yaml
# values.yaml
backend:
  replicaCount: 2
```

The backend is stateless (DB handles state), so multiple replicas work without additional config.

### Resource Limits

```yaml
backend:
  resources:
    requests:
      cpu: "200m"
      memory: "512Mi"
    limits:
      cpu: "1"
      memory: "1Gi"

frontend:
  resources:
    requests:
      cpu: "50m"
      memory: "128Mi"
    limits:
      cpu: "200m"
      memory: "256Mi"
```

### Liveness and Readiness Probes

The chart includes:

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30

readinessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
```

### Pod Disruption Budget

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: dokops-backend-pdb
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: dokops-backend
```

---

## Observability

### Enable Structured Logging

The FastAPI backend logs in JSON format (to stdout). Forward to your log aggregator:

```yaml
# If using Fluentd/Fluent Bit DaemonSet, logs are auto-collected from stdout
```

### Expose Metrics

DokOps exposes `/metrics` in Prometheus format for basic FastAPI metrics (request count, latency). Connect Prometheus to scrape:

```yaml
# Prometheus ServiceMonitor
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: dokops-backend
spec:
  selector:
    matchLabels:
      app: dokops-backend
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

---

## ChromaDB for Production

Use an external ChromaDB instance (not embedded):

```env
LOG_RAG_USE_LOCAL_CHROMA=false
DOKOPS_RAG_CHROMA_HOST=chroma.dokops.svc.cluster.local
DOKOPS_RAG_CHROMA_PORT=8000
```

The Helm 4-service chart deploys ChromaDB automatically. For large-scale deployments, consider using a managed vector DB (Pinecone, Weaviate).

---

## AI Provider

### Azure OpenAI (Enterprise Recommended)

Azure OpenAI provides:
- Data residency (choose region)
- Private endpoints (no public internet for API calls)
- Content filtering
- Usage monitoring in Azure

```env
AI_PROVIDER=AZURE
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
AZURE_OPENAI_API_VERSION=2024-02-01
```

### Rate Limiting

If using OpenAI/Gemini, be aware of:
- Tokens per minute (TPM) limits
- Requests per minute (RPM) limits

DokOps does not implement rate limiting internally — this is handled at the provider level.

---

## God Mode in Production

For production environments with multiple admins:
- Require out-of-band approval for destructive operations (e.g., "message #ops-approvals in Slack before deleting a namespace")
- Review audit logs weekly
- Consider a policy of "no God Mode on Fridays" (classic SRE practice)

---

## Network Policies

Restrict pod-to-pod communication:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: dokops-backend
  namespace: dokops
spec:
  podSelector:
    matchLabels:
      app: dokops-backend
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: dokops-frontend
      ports:
        - port: 8000
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
      ports:
        - port: 8000
  egress:
    - {}   # Allow all egress (needed for K8s API server calls)
```

---

## Production Readiness Checklist

- [ ] `AUTH_SECRET_KEY` is a random 32-byte hex string
- [ ] HTTPS is configured
- [ ] `ACCESS_TOKEN_EXPIRE_MINUTES` ≤ 480
- [ ] `DOKOPS_SIGNUP_ENABLED=false`
- [ ] PostgreSQL in use (not SQLite)
- [ ] Database backups configured
- [ ] `K8S_IN_CLUSTER_CONFIG=true` (running in cluster)
- [ ] Resource requests/limits set on all pods
- [ ] Liveness/readiness probes configured
- [ ] Logs forwarded to aggregator
- [ ] Audit log export schedule configured
- [ ] AI provider is Azure OpenAI (for enterprise)
- [ ] SSO configured (if enterprise users)
- [ ] RBAC reviewed — least privilege service account
- [ ] Network policies applied
- [ ] TLS certificates auto-renewed (cert-manager)
- [ ] Backup/restore procedure documented and tested
