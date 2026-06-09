# Secrets Management

DokOps is designed so that secrets never appear in logs, UI, or AI responses. This page explains the protections in place.

---

## Encryption at Rest

Sensitive values stored in the DokOps database are encrypted using **Fernet symmetric encryption** (AES-128-CBC with HMAC-SHA256):

| Data Type | Encrypted |
|-----------|-----------|
| Cluster kubeconfigs | ✅ |
| AI provider API keys | ✅ |
| Observability integration credentials | ✅ |
| Azure Service Principal secret | ✅ |
| Minion authentication tokens | ✅ (hashed with bcrypt, not Fernet) |
| MCP server auth tokens | ✅ |
| SSO provider client secrets | ✅ |
| Middleware service credentials (RabbitMQ, Redis, etc.) | ✅ |

### Dedicated Encryption Key

DokOps uses a **separate `ENCRYPTION_KEY` environment variable** for Fernet encryption — independent of the JWT signing key:

```env
ENCRYPTION_KEY=your-32-byte-base64-url-safe-fernet-key
```

Generate one:
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

If `ENCRYPTION_KEY` is not set, DokOps falls back to deriving the key from `AUTH_SECRET_KEY` (weaker — not recommended for production).

> **If you set `ENCRYPTION_KEY` after initial setup**, re-enter all stored credentials — existing encrypted values cannot be decrypted with the new key.

---

## Kubernetes Secrets: Names Only

DokOps never retrieves Kubernetes Secret values. The API and UI show only:

- Secret name
- Secret type (e.g., `kubernetes.io/dockerconfigjson`, `Opaque`)
- Secret keys (names of the keys, not their values)

This is enforced at the service layer:

```python
# k8s_service.py — secrets are sanitized before returning
def _sanitize_secret(secret):
    return {
        "name": secret.metadata.name,
        "type": secret.type,
        "keys": list(secret.data.keys()),  # keys only, no values
        "namespace": secret.metadata.namespace,
    }
```

Even with God Mode enabled, secret values cannot be viewed through DokOps.

---

## AI Response Sanitization

All AI responses pass through a **sanitizer** before being sent to the browser. The sanitizer scans for common secret patterns and redacts them:

| Pattern | Redacted As |
|---------|-------------|
| `sk-...` (OpenAI keys) | `[REDACTED:openai_key]` |
| `AKIA...` (AWS access key IDs) | `[REDACTED:aws_key]` |
| `ghp_...` / `github_pat_...` | `[REDACTED:github_token]` |
| `eyJ...` (JWT tokens) | `[REDACTED:jwt]` |
| `-----BEGIN * KEY-----` | `[REDACTED:private_key]` |
| Kubernetes secret values | `[REDACTED:k8s_secret]` |
| Base64-encoded values > 20 chars in secret context | `[REDACTED:base64_secret]` |

If the AI attempts to include a secret in its response (e.g., from a ConfigMap that contains a password), it is redacted before display.

---

## SSRF Protection

DokOps validates all user-supplied URLs before fetching them (used in the Knowledge Base URL ingest and observability integrations):

**Blocked by default:**
- `10.0.0.0/8` — private RFC 1918
- `172.16.0.0/12` — private RFC 1918
- `192.168.0.0/16` — private RFC 1918
- `169.254.0.0/16` — link-local (AWS metadata: `169.254.169.254`)
- `127.0.0.0/8` — loopback
- `::1` — IPv6 loopback
- DNS names that resolve to private IPs

To allow private URLs (e.g., to reach an internal Grafana instance):

```env
ALLOW_PRIVATE_CLUSTER_IPS=true
```

Use this only in trusted, isolated environments.

---

## Startup Secret Validation

DokOps **refuses to start** if `AUTH_SECRET_KEY` is set to a known-weak value:

```
RuntimeError: AUTH_SECRET_KEY is set to a known-weak default value.
Set a cryptographically random value via the AUTH_SECRET_KEY environment variable.
```

Rejected values include: `changethis`, `secret`, `password`, and the empty string. This is checked at process startup (skipped during test runs).

## JWT Security

- Tokens are signed with HMAC-SHA256 (`HS256`) using `AUTH_SECRET_KEY`.
- Default expiry: 8 days (`ACCESS_TOKEN_EXPIRE_MINUTES=11520`).
- No token refresh — users must re-authenticate after expiry.
- Tokens are accepted via `Authorization: Bearer <token>` header **or** an `access_token` httpOnly cookie (set by the SSO callback flow).

**Production recommendations:**
1. Set `AUTH_SECRET_KEY` to a 256-bit (32-byte) random value:
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
2. Set `ENCRYPTION_KEY` to a separate Fernet key (see above).
3. Reduce `ACCESS_TOKEN_EXPIRE_MINUTES` to `480` (8 hours) or less.
4. Use HTTPS — tokens in transit must be protected.

---

## Database Security

- Development default: SQLite at `./sql_app.db` — no authentication required.
- Production: PostgreSQL with a strong password.

```env
DATABASE_URL=postgresql://dokops:strongpassword@postgres:5432/dokops
```

The SQLite file contains encrypted credentials. Protect it with filesystem permissions:

```bash
chmod 600 ./sql_app.db
```

---

## Environment Variable Secrets

Secrets configured as environment variables (e.g., `GEMINI_API_KEY`) are read at startup and stored encrypted in the database. They are never logged.

To audit what was seeded:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/system/status
# Returns which settings are configured (not the values)
```

---

## Summary Checklist

Before going to production:

- [ ] `AUTH_SECRET_KEY` is a random 256-bit value (not the default — server refuses to start otherwise)
- [ ] `ENCRYPTION_KEY` is a separate Fernet key (not derived from JWT secret)
- [ ] Database uses PostgreSQL with a strong password
- [ ] DokOps is behind HTTPS (TLS termination at load balancer or Ingress)
- [ ] `ACCESS_TOKEN_EXPIRE_MINUTES` is set to an appropriate short value
- [ ] `DOKOPS_SIGNUP_ENABLED=false` if open registration is not desired
- [ ] `ALLOW_PRIVATE_CLUSTER_IPS` is false unless specifically needed
- [ ] The DokOps service account in Kubernetes follows least-privilege RBAC
- [ ] Alert webhook secrets are configured in **Settings → Alert Webhooks** (not left empty)
- [ ] Middleware credentials are scoped as narrowly as possible (minion > group > global)
