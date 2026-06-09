# Configuration Reference

All DokOps settings are configured via environment variables. Many can also be set through the **Admin** → **Settings** UI after initial startup (stored encrypted in the database).

---

## Core Security

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_SECRET_KEY` | `changethis` | JWT signing secret. **Must change in production.** Use `python3 -c "import secrets; print(secrets.token_hex(32))"` to generate. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `11520` | JWT token expiry (11520 = 8 days). Reduce for production. |
| `ALGORITHM` | `HS256` | JWT signing algorithm. |
| `BACKEND_CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Comma-separated allowed CORS origins. |
| `FRONTEND_URL` | `http://localhost:3000` | Public URL of the frontend (used for SSO redirects). |
| `BACKEND_PUBLIC_URL` | `http://localhost:8000` | Public URL of the backend (used for SSO callback URLs). |

---

## Database

| Variable | Default | Description |
|----------|---------|-------------|
| `SQLITE_URL` | `sqlite:///./sql_app.db` | SQLite database path. Used when `DATABASE_URL` is not set. |
| `DATABASE_URL` | (empty) | PostgreSQL URL. If set, overrides SQLite. Format: `postgresql://user:pass@host:5432/dbname` |

---

## Kubernetes

| Variable | Default | Description |
|----------|---------|-------------|
| `K8S_IN_CLUSTER_CONFIG` | `false` | Set to `true` when running DokOps inside a Kubernetes pod (uses service account token). |
| `K8S_MOCK_MODE` | `false` | Use simulated K8s data. No real cluster needed. Good for demos. |
| `ALLOW_PRIVATE_CLUSTER_IPS` | `false` | Allow fetching URLs with private IP ranges (SSRF protection). |

---

## AI Providers

Configured via env vars at startup, or via **Admin** → **Settings** UI at runtime.

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_PROVIDER` | `GEMINI` | Active provider: `GEMINI`, `OPENAI`, or `AZURE` |
| `GEMINI_API_KEY` | (empty) | Google Gemini API key |
| `OPENAI_API_KEY` | (empty) | OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | (empty) | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_API_KEY` | (empty) | Azure OpenAI API key |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | (empty) | Azure deployment name (model) |
| `AZURE_OPENAI_API_VERSION` | (empty) | Azure OpenAI API version (e.g., `2024-02-01`) |

---

## Knowledge Base (RAG)

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_RAG_ENABLED` | `false` | Enable automatic pod log ingestion into ChromaDB |
| `LOG_RAG_USE_LOCAL_CHROMA` | `true` | Use embedded ChromaDB (false = external server) |
| `LOG_CHROMA_LOCAL_PATH` | `./chroma_logs` | Path for embedded ChromaDB data |
| `LOG_RETENTION_DAYS` | `7` | Days to keep ingested logs |
| `LOG_INGEST_INTERVAL_SECONDS` | `300` | How often to re-ingest logs (seconds) |
| `LOG_INGEST_TAIL_LINES` | `100` | Log lines to fetch per pod per cycle |

For external ChromaDB:

| Variable | Default | Description |
|----------|---------|-------------|
| `DOKOPS_RAG_CHROMA_HOST` | (empty) | External ChromaDB host |
| `DOKOPS_RAG_CHROMA_PORT` | `8000` | External ChromaDB port |

---

## Bootstrap / Seeding

These variables seed the database on first startup. On subsequent starts, they are ignored (unless `DOKOPS_FORCE_SEED=true`).

| Variable | Description |
|----------|-------------|
| `DOKOPS_ADMIN_USERNAME` | Initial admin username |
| `DOKOPS_ADMIN_PASSWORD` | Initial admin password |
| `DOKOPS_AI_PROVIDER` | AI provider to configure on first start |
| `DOKOPS_AI_API_KEY` | AI API key to configure on first start |
| `DOKOPS_AI_MODEL` | AI model name to configure on first start |
| `DOKOPS_RAG_ENABLED` | Enable RAG on first start (`true`/`false`) |
| `DOKOPS_RAG_CHROMA_HOST` | ChromaDB host for RAG on first start |
| `DOKOPS_RAG_CHROMA_PORT` | ChromaDB port for RAG on first start |
| `DOKOPS_LOG_RAG_ENABLED` | Enable log ingestion on first start |
| `DOKOPS_LOG_RETENTION_DAYS` | Log retention days on first start |
| `DOKOPS_LOG_INGEST_INTERVAL_SECONDS` | Log ingest interval on first start |
| `DOKOPS_SIGNUP_ENABLED` | Enable self-registration on first start |
| `DOKOPS_SIGNUP_DEFAULT_ROLE` | Default role for self-registered users (`admin`/`viewer`) |
| `DOKOPS_FORCE_SEED` | `true` to overwrite existing settings on every start (⚠️ use carefully) |

---

## SSO / OAuth2

| Variable | Default | Description |
|----------|---------|-------------|
| `SSO_ENABLED` | `false` | Show SSO login buttons |
| `SSO_AUTO_PROVISION` | `true` | Auto-create accounts for new SSO users |
| `SSO_ALLOWED_DOMAINS` | (empty) | Comma-separated allowed email domains. Empty = all. |

### Entra ID

| Variable | Description |
|----------|-------------|
| `ENTRA_CLIENT_ID` | Azure AD application (client) ID |
| `ENTRA_CLIENT_SECRET` | Azure AD client secret |
| `ENTRA_TENANT_ID` | Azure AD tenant ID |
| `ENTRA_ROLES_CLAIM` | JWT claim name for roles (default: `roles`) |
| `ENTRA_ADMIN_ROLE` | Role value that maps to DokOps admin |

### Google Workspace

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLIENT_ID` | Google OAuth2 client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth2 client secret |
| `GOOGLE_ALLOWED_DOMAIN` | Restrict to this domain (e.g., `example.com`) |
| `GOOGLE_ADMIN_GROUP` | Google Group that maps to DokOps admin |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Path to service account JSON for group lookup |

### Authentik

| Variable | Description |
|----------|-------------|
| `AUTHENTIK_CLIENT_ID` | Authentik client ID |
| `AUTHENTIK_CLIENT_SECRET` | Authentik client secret |
| `AUTHENTIK_BASE_URL` | Authentik server URL |
| `AUTHENTIK_ROLES_CLAIM` | JWT claim for roles |
| `AUTHENTIK_ADMIN_ROLE` | Role value for admin |

### AWS Cognito

| Variable | Description |
|----------|-------------|
| `COGNITO_CLIENT_ID` | Cognito app client ID |
| `COGNITO_CLIENT_SECRET` | Cognito app client secret |
| `COGNITO_USER_POOL_ID` | Cognito User Pool ID |
| `COGNITO_REGION` | AWS region (e.g., `us-east-1`) |
| `COGNITO_ROLES_CLAIM` | JWT claim for roles |
| `COGNITO_ADMIN_ROLE` | Role value for admin |

---

## Complete Minimal Production Example

```env
# Security
AUTH_SECRET_KEY=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2
ACCESS_TOKEN_EXPIRE_MINUTES=480
BACKEND_CORS_ORIGINS=https://dokops.example.com
FRONTEND_URL=https://dokops.example.com
BACKEND_PUBLIC_URL=https://dokops.example.com

# Database (PostgreSQL)
DATABASE_URL=postgresql://dokops:strongpassword@postgres:5432/dokops

# Kubernetes (running inside cluster)
K8S_IN_CLUSTER_CONFIG=true

# AI
AI_PROVIDER=OPENAI
OPENAI_API_KEY=sk-...

# Bootstrap
DOKOPS_ADMIN_USERNAME=admin
DOKOPS_ADMIN_PASSWORD=securepassword123!
DOKOPS_SIGNUP_ENABLED=false
DOKOPS_SIGNUP_DEFAULT_ROLE=viewer

# RAG / Log Ingestion
LOG_RAG_ENABLED=true
LOG_RAG_USE_LOCAL_CHROMA=false
DOKOPS_RAG_CHROMA_HOST=chroma
DOKOPS_RAG_CHROMA_PORT=8000
LOG_RETENTION_DAYS=14
LOG_INGEST_INTERVAL_SECONDS=300
```
