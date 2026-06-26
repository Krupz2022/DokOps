# Audit

The audit log is a **history book** of changes made through DokOps — who did what and when. There is one endpoint to read it.

---

## GET /api/v1/audit/

**What this does:** Lists audit-log entries (a record of actions taken, such as deleting a pod or changing settings), newest first. You can page through them and filter by where the action came from.

**Auth required?** Token (any logged-in user).

**Query parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `skip` | integer | no | `0` | How many records to skip (for paging). |
| `limit` | integer | no | `100` | Maximum records to return. |
| `source` | string | no | – | Only show entries from this source. Known values: `SYSTEM`, `K8S`, `AZURE`. |

**curl example:**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/audit/?limit=20&source=K8S"
```

**Example response (200):** an array of audit-log entries:

```json
[
  {
    "id": 41,
    "user": "admin",
    "action": "DELETE",
    "source": "K8S",
    "resource": "pod/production/payments-api-xyz",
    "detail": "Pod deleted via God Mode",
    "timestamp": "2026-06-26T10:15:00Z"
  }
]
```

| Field | Meaning |
|-------|---------|
| `id` | Record number. |
| `user` | Who performed the action. |
| `action` | What kind of action (e.g. `DELETE`, `UPDATE`). |
| `source` | The subsystem it touched (`SYSTEM`, `K8S`, `AZURE`). |
| `resource` | What was acted on. |
| `detail` | Human-readable description. |
| `timestamp` | When it happened (UTC). |

(Exact fields depend on the action recorded.)

**Common errors:** `401` not authenticated; `422` invalid query value.
