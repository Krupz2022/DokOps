# Knowledge Sources

A **knowledge source** is an external system the AI can pull information from (for example a wiki, a docs site, or a ticketing system). These endpoints register, test, toggle, and remove those connectors.

> **Shared notes:**
> - **Listing** and **testing a saved source** are allowed for any logged-in user.
> - **Creating, updating, deleting, toggling, and test-config** are **admin-only**.

---

## GET /api/v1/knowledge-sources

**What this does:** Lists all configured knowledge sources.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/knowledge-sources
```

**Example response (200):** array of `{ "id":"ks_1","name":"Ops Wiki","provider":"confluence","enabled":true }`.

---

## POST /api/v1/knowledge-sources

**What this does:** Registers a new knowledge source.

**Auth required?** Admin / Superuser.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | yes | Friendly name. |
| `provider` | string | yes | Connector type (e.g. `confluence`, `web`, `github`). |
| `config` | object | yes | Provider-specific settings (URLs, tokens, etc.). |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/knowledge-sources \
  -d '{"name":"Ops Wiki","provider":"confluence","config":{"base_url":"https://acme.atlassian.net/wiki","space":"OPS"}}'
```

**Example response (200):** the created source object.

**Common errors:** `403` not admin; `422` missing fields.

---

## PUT /api/v1/knowledge-sources/{source_id}

**What this does:** Updates a knowledge source.

**Auth required?** Admin / Superuser. **Path:** `source_id` (string, required).

**Request body** (JSON): same fields as Create (`name`, `provider`, `config`).

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/knowledge-sources/ks_1 \
  -d '{"name":"Ops Wiki (new)","provider":"confluence","config":{"base_url":"https://acme.atlassian.net/wiki","space":"OPS"}}'
```

**Example response (200):** the updated source object.

---

## DELETE /api/v1/knowledge-sources/{source_id}

**What this does:** Deletes a knowledge source.

**Auth required?** Admin / Superuser. **Path:** `source_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/knowledge-sources/ks_1
```

**Example response (200):** `{ "status": "deleted" }`

---

## PATCH /api/v1/knowledge-sources/{source_id}/toggle

**What this does:** Enables or disables a knowledge source without deleting it.

**Auth required?** Admin / Superuser. **Path:** `source_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `enabled` | boolean | yes | `true` to enable, `false` to disable. |

```bash
curl -X PATCH -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/knowledge-sources/ks_1/toggle \
  -d '{"enabled": false}'
```

**Example response (200):** `{ "id": "ks_1", "enabled": false }`

---

## POST /api/v1/knowledge-sources/test-config

**What this does:** Tests a provider config **before** saving it (validates the connection details).

**Auth required?** Admin / Superuser.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `provider` | string | yes | Connector type. |
| `config` | object | yes | The settings to test. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/knowledge-sources/test-config \
  -d '{"provider":"confluence","config":{"base_url":"https://acme.atlassian.net/wiki","api_token":"..."}}'
```

**Example response (200):** `{ "success": true }`

---

## POST /api/v1/knowledge-sources/{source_id}/test

**What this does:** Tests an already-saved knowledge source.

**Auth required?** Token. **Path:** `source_id` (string, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/knowledge-sources/ks_1/test
```

**Example response (200):** `{ "success": true }`
