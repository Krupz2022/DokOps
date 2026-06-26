# Service Credentials

These endpoints store the **passwords/credentials** that minions use to connect to services (databases, message queues, etc.). Credentials can be set at different "scopes" (global, org, group, or one minion), and DokOps picks the most specific one.

> **Shared notes:**
> - Listing and resolve-preview are allowed for any logged-in user.
> - **Adding, editing, and deleting** credentials require **God Mode** (they're sensitive).
> - The real password is **never returned** by any read endpoint.

---

## GET /api/v1/service-credentials/

**What this does:** Lists stored service credentials (without passwords). You can filter by scope.

**Auth required?** Token.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `scope_type` | string | no | Filter by scope: `global`, `org`, `group`, or `minion`. |
| `scope_id` | string | no | The ID for that scope (e.g. the org/group/minion ID). |

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/service-credentials/?scope_type=group&scope_id=grp_3"
```

**Example response (200):**

```json
[
  {
    "id": "cred_1",
    "scope_type": "group",
    "scope_id": "grp_3",
    "service_type": "postgres",
    "instance_name": "main-db",
    "username": "dokops",
    "host": "10.0.0.5",
    "port": 5432,
    "extra": "{}",
    "created_at": "2026-06-01T09:00:00Z",
    "updated_at": "2026-06-10T11:00:00Z"
  }
]
```

(Note: no `password` field — it's write-only.)

---

## POST /api/v1/service-credentials/

**What this does:** Adds a new service credential.

**Auth required?** **God Mode required.**

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `scope_type` | string | yes | – | `global`, `org`, `group`, or `minion`. |
| `scope_id` | string | no | – | ID for the scope (omit for `global`). |
| `service_type` | string | yes | – | e.g. `postgres`, `redis`, `mysql`. |
| `instance_name` | string | no | – | A label if there are multiple of the same type. |
| `username` | string | no | – | Login username. |
| `password` | string | yes | – | The secret (stored encrypted; never returned). |
| `port` | integer | no | – | Service port. |
| `host` | string | no | – | Service host. |
| `extra` | string | no | `{}` | Extra JSON settings as a string. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/service-credentials/ \
  -d '{"scope_type":"group","scope_id":"grp_3","service_type":"postgres","username":"dokops","password":"s3cr3t","host":"10.0.0.5","port":5432}'
```

**Example response (201):** the created credential object (without the password).

**Common errors:** `403` God Mode not active; `422` missing required fields.

---

## PUT /api/v1/service-credentials/{cred_id}

**What this does:** Updates an existing credential (including changing the password).

**Auth required?** **God Mode required.** **Path:** `cred_id` (string, required).

**Request body** (JSON): same fields as Add above (`password` is required).

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/service-credentials/cred_1 \
  -d '{"scope_type":"group","scope_id":"grp_3","service_type":"postgres","username":"dokops","password":"newPass"}'
```

**Example response (200):** the updated credential object (without the password).

---

## DELETE /api/v1/service-credentials/{cred_id}

**What this does:** Deletes a credential.

**Auth required?** **God Mode required.** **Path:** `cred_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/service-credentials/cred_1
```

**Example response (200):** `{ "status": "deleted" }`

---

## GET /api/v1/service-credentials/resolve/{minion_id}/{service_type}

**What this does:** Previews **which** credential a given minion would actually use for a given service type — without revealing the password. Helps you confirm the scope hierarchy is set up correctly.

**Auth required?** Token. **Path:** `minion_id`, `service_type` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/service-credentials/resolve/m_12/postgres
```

**Example response (200):**

```json
{
  "resolved": true,
  "scope_type": "group",
  "scope_id": "grp_3",
  "credential_id": "cred_1",
  "username": "dokops"
}
```

| Field | Meaning |
|-------|---------|
| `resolved` | Whether a credential was found. |
| `scope_type` / `scope_id` | Which level the chosen credential came from. |
| `credential_id` | The winning credential's ID. |
| `username` | Its username (never the password). |
