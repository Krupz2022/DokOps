# Installation

DokOps can be run three ways: **Docker Compose** (simplest), **Helm** (production), or **local development**.

---

## Option 1 — Docker Compose (Recommended for Quick Start)

The all-in-one image runs the backend and frontend in a single container.

### Prerequisites
- Docker 24+
- A cluster to connect to — you can upload a kubeconfig, use cloud auto-discovery (AKS/EKS), or connect via bearer token after startup. See [First Run](first-run.md). Alternatively, set `K8S_MOCK_MODE=true` for a demo without a real cluster.

### Run

```bash
# Pull and start
docker run -d \
  --name dokops \
  -p 3000:3000 \
  -p 8000:8000 \
  -v ~/.kube:/root/.kube:ro \
  -v dokops-data:/app/data \
  ghcr.io/your-org/dokops:latest
```

Or with Docker Compose (`deployment/docker-compose.yml`):

```bash
cd deployment
docker compose up -d
```

Open `http://localhost:3000` — the first-run setup wizard will appear.

### Environment Variables for Docker Compose

Create a `.env` file next to `docker-compose.yml`:

```env
# Admin bootstrap (insert-once on first start)
DOKOPS_ADMIN_USERNAME=admin
DOKOPS_ADMIN_PASSWORD=changeme123!

# AI Provider — pick one
DOKOPS_AI_PROVIDER=GEMINI
DOKOPS_AI_API_KEY=your-gemini-api-key

# Or Azure OpenAI
# DOKOPS_AI_PROVIDER=AZURE
# DOKOPS_AI_API_KEY=your-azure-api-key
# AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
# AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o

# Security — change this!
AUTH_SECRET_KEY=a-very-long-random-secret-string
```

---

## Option 2 — Helm (Production)

Two charts are available:

| Chart | When to use |
|-------|-------------|
| `deployment/helm/dokops` | Production: backend, frontend, ChromaDB, PostgreSQL as separate pods |
| `deployment/helm/dokops-aio` | Single-pod all-in-one (staging/demo) |

### Install (4-service chart)

```bash
# Add credentials to a values override file
cat > my-values.yaml << 'EOF'
backend:
  env:
    AUTH_SECRET_KEY: "your-secret-key-here"
    DOKOPS_ADMIN_USERNAME: "admin"
    DOKOPS_ADMIN_PASSWORD: "yourpassword"
    DOKOPS_AI_PROVIDER: "OPENAI"
    DOKOPS_AI_API_KEY: "sk-..."

postgres:
  auth:
    password: "dbpassword"
EOF

# Install
helm install dokops ./deployment/helm/dokops \
  --namespace dokops \
  --create-namespace \
  -f my-values.yaml
```

### Install (all-in-one chart)

```bash
helm install dokops ./deployment/helm/dokops-aio \
  --namespace dokops \
  --create-namespace \
  --set backend.env.AUTH_SECRET_KEY="your-secret-key" \
  --set backend.env.DOKOPS_ADMIN_PASSWORD="yourpassword"
```

### Expose the UI

The chart creates a `ClusterIP` service by default. To expose externally:

```bash
# Port-forward (dev/test)
kubectl port-forward svc/dokops-frontend 3000:3000 -n dokops

# Or update values.yaml to use LoadBalancer / Ingress
```

---

## Option 3 — Local Development

### Prerequisites
- Python 3.10+
- Node.js 20+
- (Optional) A `~/.kube/config` or set `K8S_MOCK_MODE=true`

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Configure (create .env or export vars)
export AUTH_SECRET_KEY="dev-secret-key"
export AI_PROVIDER="GEMINI"
export GEMINI_API_KEY="your-key"

uvicorn app.main:app --reload --port 8000
```

The API is available at `http://localhost:8000`. Swagger docs at `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The UI is available at `http://localhost:5173`.

---

## Mock Mode (No Real Cluster)

Set `K8S_MOCK_MODE=true` to run with simulated Kubernetes data. Useful for demos or testing the AI chat without a real cluster.

```bash
export K8S_MOCK_MODE=true
uvicorn app.main:app --reload --port 8000
```

---

## Health Check

```bash
curl http://localhost:8000/health
# {"status": "ok", "db": "connected", "k8s": "connected"}
```

---

## Next Steps

- [First Run & Setup](first-run.md) — create the admin account and configure AI
- [Quickstart](quickstart.md) — get your first AI diagnosis running
