# Keys

A **key** is an enrollment key used when installing a new minion — it decides which org/group a new minion joins and which blueprints run on it when it first connects.

> **Shared notes:**
> - Reading is allowed for any logged-in user.
> - **Creating, editing, and deleting** keys are **admin-only**.

---

## GET /api/v1/keys/

**What this does:** Lists all enrollment keys.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/keys/
```

**Example response (200):**

```json
[
  {
    "id": "key_1",
    "name": "Web servers key",
    "org_id": "org_1",
    "group_id": "grp_3",
    "run_on_attach": true,
    "enabled": true,
    "blueprint_ids": ["bp_1"]
  }
]
```

---

## GET /api/v1/keys/{key_id}

**What this does:** Returns one key's details.

**Auth required?** Token. **Path:** `key_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/keys/key_1
```

**Example response (200):** the key object.

**Common errors:** `404` not found.

---

## POST /api/v1/keys/

**What this does:** Creates a new enrollment key.

**Auth required?** Admin / Superuser.

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | yes | – | A label for the key. |
| `org_id` | string | no | – | Org new minions join. |
| `group_id` | string | no | – | Group new minions join. |
| `run_on_attach` | boolean | no | `false` | Run the listed blueprints as soon as a minion enrolls. |
| `enabled` | boolean | no | `true` | Whether the key currently works. |
| `blueprint_ids` | array of strings | no | `[]` | Blueprints to run on attach. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/keys/ \
  -d '{"name":"Web servers key","org_id":"org_1","group_id":"grp_3","run_on_attach":true,"blueprint_ids":["bp_1"]}'
```

**Example response (200):** the created key object (often including the secret token to use during install).

---

## PUT /api/v1/keys/{key_id}

**What this does:** Updates an enrollment key.

**Auth required?** Admin / Superuser. **Path:** `key_id` (string, required).

**Request body** (JSON): same fields as Create above.

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/keys/key_1 \
  -d '{"name":"Web servers key","enabled":false,"blueprint_ids":[]}'
```

**Example response (200):** the updated key object.

---

## DELETE /api/v1/keys/{key_id}

**What this does:** Deletes an enrollment key (existing minions are unaffected; the key just can't be used for new enrollments).

**Auth required?** Admin / Superuser. **Path:** `key_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/keys/key_1
```

**Example response (200):** `{ "status": "deleted" }`
