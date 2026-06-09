# Vault — Cluster-Scoped Middleware Credentials

The Vault is an extension of the [Service Credential Store](../security/secrets.md) that adds **cluster-level scoping** and **automatic token resolution** inside toolset commands. Instead of embedding usernames and passwords in YAML toolsets, you store credentials once in the Vault and reference them with a `$VAULT:service:field` token.

---

## How It Works

1. You add a credential to the credential store with `scope_type: cluster` and a target `cluster_id`.
2. In any toolset command you write `$VAULT:service_type:field` (e.g. `$VAULT:redis:host`).
3. When the AI executes the toolset command, the executor resolves every `$VAULT:` token by looking up the matching credential for the active cluster before spawning the subprocess.

This means the same toolset YAML works across clusters — the right credentials are injected per cluster at run time.

---

## Supported Services

| Service | Token prefix | Fields |
|---------|-------------|--------|
| RabbitMQ | `$VAULT:rabbitmq:*` | `host`, `port`, `username`, `password`, `vhost` |
| Redis | `$VAULT:redis:*` | `host`, `port`, `password` |
| CouchDB | `$VAULT:couchdb:*` | `host`, `port`, `username`, `password` |
| MongoDB | `$VAULT:mongodb:*` | `host`, `port`, `username`, `password` |
| MySQL | `$VAULT:mysql:*` | `host`, `port`, `username`, `password` |
| Postgres | `$VAULT:postgres:*` | `host`, `port`, `username`, `password`, `database` |

---

## Adding a Cluster Credential

1. Go to **Settings → Service Credentials**.
2. Click **Add Credential**.
3. Set:
   - **Scope Type:** `cluster`
   - **Cluster:** select the target cluster
   - **Service Type:** e.g. `redis`
   - **Host:** the middleware host/IP
   - **Username / Password:** service credentials (stored Fernet-encrypted)
4. Click **Save**.

---

## Using `$VAULT:` Tokens in Toolsets

Any toolset command can use tokens. Examples:

```yaml
# redis.yaml
tools:
  - name: redis_ping
    description: Ping Redis and return PONG
    command: redis-cli -h $VAULT:redis:host -p 6379 PING

  - name: redis_info
    description: Get Redis server info
    command: redis-cli -h $VAULT:redis:host -a $VAULT:redis:password INFO server

  - name: pg_list_databases
    description: List all PostgreSQL databases
    command: psql -h $VAULT:postgres:host -U $VAULT:postgres:username -d $VAULT:postgres:database -c "\l"
```

If a token cannot be resolved (no matching credential for the active cluster), the executor raises a `VaultCredentialNotFound` error and the tool call fails with a clear message — it never passes a literal `$VAULT:…` string to the subprocess.

---

## Vault Coverage Page

Navigate to **Vault** in the sidebar to see a coverage matrix:

| Cluster | Provider | Configured Services | Total Services |
|---------|----------|-------------------|----------------|
| prod-cluster | GKE | redis, postgres | 2 / 6 |
| staging-cluster | AKS | redis | 1 / 6 |
| local-dev | kubeconfig | — | 0 / 6 |

Clusters with gaps are highlighted so you can identify missing credentials before a tool call fails.

---

## Via API

```bash
# Get coverage for all clusters
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/vault/coverage

# List all service credentials
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/service-credentials

# Create a cluster-scoped credential
curl -X POST http://localhost:8000/api/v1/service-credentials \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "scope_type": "cluster",
    "scope_id": "prod-cluster-id",
    "service_type": "redis",
    "host": "redis.prod.internal",
    "username": "default",
    "password": "s3cr3t"
  }'
```

---

## Security

- Passwords are stored with **Fernet encryption** (`ENCRYPTION_KEY` env var).
- Plaintext credentials are never written to logs, audit records, or AI responses.
- Usernames are masked in API responses (`a***`).
- The `$VAULT:` resolver runs server-side; the AI only sees the resolved command output, not the credentials themselves.
