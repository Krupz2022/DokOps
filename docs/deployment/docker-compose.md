# Docker Compose Deployment

The `deployment/` folder contains a production-ready stack powered by **Traefik** (reverse proxy + automatic SSL), **PostgreSQL**, **ChromaDB**, and the DokOps all-in-one image. All services communicate on a private bridge network — only ports 80 and 443 are exposed.

---

## Prerequisites

- Docker Engine 24+ with the Compose plugin (`docker compose`)
- A domain name with an A record pointing to your server (required for Let's Encrypt)
- Ports 80 and 443 open in your firewall

---

## Quick Start

### 1. Create your `.env` file

```bash
cd deployment
cp .env.example .env
$EDITOR .env
```

Minimum required values:

```env
# ── Domain & SSL ──────────────────────────────────────────────────────────────
DOMAIN=dokops.yourdomain.com
ACME_EMAIL=you@yourdomain.com

# ── Security ──────────────────────────────────────────────────────────────────
AUTH_SECRET_KEY=<generate-with-python3-c-import-secrets-print-secrets.token_hex32>
ENCRYPTION_KEY=<generate-with-python3-c-import-secrets-print-secrets.token_hex32>

# ── PostgreSQL ────────────────────────────────────────────────────────────────
POSTGRES_DB=dokops
POSTGRES_USER=dokops
POSTGRES_PASSWORD=<strong-random-password>

# ── AI Provider (set at least one) ───────────────────────────────────────────
OPENAI_API_KEY=
GOOGLE_API_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_DEPLOYMENT=
```

Generate secure keys:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Start the stack

```bash
docker compose up -d
```

On first boot, navigate to `https://<DOMAIN>/setup` to create the initial admin account. Let's Encrypt certificates are fetched automatically on the first request.

---

## Services

| Container | Image | Port (internal) | Role |
|-----------|-------|-----------------|------|
| `traefik` | `traefik:v3.6.6` | 80, 443 (public) | Reverse proxy, SSL, HTTP→HTTPS redirect |
| `dokops-postgres` | `postgres:16-alpine` | 5432 | Primary relational database |
| `dokops-chromadb` | `chromadb/chroma:latest` | 8000 | Vector store for RAG knowledge base |
| `dokops-aio` | `krupz/dokops-aio:latest` | 3000 | DokOps backend + frontend bundled |

---

## SSL Options

The `docker-compose.yml` ships with comments for both modes. Read the header block in the file to switch.

### Option A — Let's Encrypt (default)

No extra steps. Traefik uses the HTTP-01 ACME challenge on port 80 to obtain and auto-renew a certificate for `$DOMAIN`. Requires port 80 to be reachable from the public internet.

Set `ACME_EMAIL` in `.env` so Let's Encrypt can contact you about expiry notices.

### Option B — Bring Your Own Certificate

1. Place your `cert.pem` and `key.pem` in `deployment/certs/`.
2. In `docker-compose.yml`, comment out the four `--certificatesresolvers.le.*` lines under the `traefik` service `command` block.
3. Under the `dokops` labels, comment out `tls.certresolver=le` and uncomment `tls=true`.

The `traefik-dynamic.yml` file is already pre-wired to load `/etc/traefik/certs/cert.pem` and `key.pem` — no further changes needed.

> `deployment/certs/` is gitignored. Never commit certificate files.

---

## Environment Variables Reference

See the full reference in [Configuration](../administration/configuration.md). The variables used directly by `docker-compose.yml`:

| Variable | Required | Description |
|----------|----------|-------------|
| `DOMAIN` | Yes | Public hostname (e.g. `dokops.example.com`) |
| `ACME_EMAIL` | Option A | Email for Let's Encrypt notifications |
| `AUTH_SECRET_KEY` | Yes | JWT signing secret (min 32 chars, random) |
| `ENCRYPTION_KEY` | Yes | Fernet key for stored credentials (min 32 chars, random) |
| `POSTGRES_DB` | Yes | PostgreSQL database name |
| `POSTGRES_USER` | Yes | PostgreSQL username |
| `POSTGRES_PASSWORD` | Yes | PostgreSQL password |
| `OPENAI_API_KEY` | One required | OpenAI API key |
| `GOOGLE_API_KEY` | One required | Google Gemini API key |
| `AZURE_OPENAI_*` | One required | Azure OpenAI credentials |
| `ENTRA_CLIENT_ID/SECRET/TENANT_ID` | No | Microsoft Entra SSO (optional) |

---

## Headless Bootstrap (Skip the `/setup` UI)

Add these to `.env` to seed the admin account and AI config on first start:

```env
DOKOPS_ADMIN_USERNAME=admin
DOKOPS_ADMIN_PASSWORD=your-secure-password
DOKOPS_AI_PROVIDER=openai
DOKOPS_AI_API_KEY=sk-...
DOKOPS_AI_MODEL=gpt-4o
```

Set `DOKOPS_FORCE_SEED=true` to overwrite existing DB values on every restart (useful for infrastructure-as-code deployments).

---

## Kubernetes Access

By default, the `dokops` service mounts `~/.kube/config` from the host:

```yaml
volumes:
  - ~/.kube/config:/root/.kube/config:ro
```

For in-cluster deployments (running DokOps inside Kubernetes), set `K8S_IN_CLUSTER_CONFIG=true` in the environment and remove the kubeconfig mount. Grant the pod a `ServiceAccount` with appropriate RBAC permissions.

---

## Persistent Data

| Volume | Contents |
|--------|----------|
| `postgres-data` | All DokOps state: users, clusters, conversations, audit log, patch history |
| `chroma-data` | Vector embeddings for the RAG knowledge base |
| `dokops-data` | Miscellaneous app data |
| `traefik-certs` | Let's Encrypt certificate store (`acme.json`) |

Backup the PostgreSQL volume for disaster recovery:

```bash
# Backup
docker exec dokops-postgres pg_dump -U dokops dokops | gzip > dokops-$(date +%Y%m%d).sql.gz

# Restore
gunzip -c dokops-20260601.sql.gz | docker exec -i dokops-postgres psql -U dokops dokops
```

---

## Logs

```bash
# All services
docker compose logs -f

# DokOps only
docker compose logs -f dokops

# Traefik access log
docker compose logs -f traefik
```

---

## Updating

```bash
docker compose pull
docker compose up -d
```

Schema migrations run automatically on startup — no manual steps required.

---

## Uninstalling

```bash
# Stop and remove containers (data volumes preserved)
docker compose down

# Also remove all volumes (DESTROYS ALL DATA)
docker compose down -v
```
