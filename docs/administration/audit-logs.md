# Audit Logs

Every mutating operation in DokOps is recorded in an immutable audit log. This provides accountability, compliance evidence, and a history of what changed and when.

---

## What Is Logged

| Source | Actions Logged |
|--------|---------------|
| **Kubernetes** | Scale deployment, restart deployment, delete pod, delete namespace, patch ConfigMap, exec into pod, create namespace |
| **Helm** | Rollback, upgrade, delete release |
| **Azure** | Resource analysis triggers (read-only, but logged) |
| **Minions** | Job execution, bulk run, patch apply |
| **System** | Login, logout, user creation, role changes, settings changes, God Mode enable/disable |
| **Pending Operations** | Created, approved, rejected, expired |

---

## Audit Log Entry Fields

Each entry contains:

| Field | Description |
|-------|-------------|
| `timestamp` | ISO 8601 datetime (UTC) |
| `actor` | Username who performed the action |
| `action` | Machine-readable action name (e.g., `scale_deployment`) |
| `resource` | Resource affected (e.g., `production/payments-api`) |
| `result` | `SUCCESS`, `FAILURE`, `REJECTED`, `EXPIRED` |
| `mode` | `GOD` (write operation) or `NORMAL` (read-only) |
| `source` | `K8S`, `AZURE`, `SYSTEM`, `MINION` |
| `details` | JSON object with action-specific details |

### Example Entry

```json
{
  "id": 1547,
  "timestamp": "2026-05-25T14:35:22Z",
  "actor": "alice",
  "action": "scale_deployment",
  "resource": "production/payments-api",
  "result": "SUCCESS",
  "mode": "GOD",
  "source": "K8S",
  "details": {
    "from_replicas": 3,
    "to_replicas": 5,
    "cluster": "prod-eu-west"
  }
}
```

---

## Viewing the Audit Log

### Via UI

1. Click **Admin** in the sidebar.
2. Click the **Audit Logs** tab.

The table shows the most recent entries first. Filters available:
- **Actor** — filter by username
- **Action** — filter by action type
- **Resource** — filter by resource name
- **Result** — SUCCESS / FAILURE / REJECTED / EXPIRED
- **Date Range** — start and end date

### Via API

```bash
# Get last 50 entries
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/audit?limit=50"

# Filter by actor
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/audit?actor=alice&limit=100"

# Filter by action
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/audit?action=scale_deployment"

# Filter by result
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/audit?result=FAILURE"

# Date range (ISO format)
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/audit?from=2026-05-01T00:00:00Z&to=2026-05-25T23:59:59Z"
```

---

## Audit Log Immutability

Audit log entries are **write-only** from DokOps's perspective:
- No API endpoint exists to delete or modify audit entries.
- The database model has no `updated_at` field.
- Admin users can view but not edit entries.

For long-term archiving:
1. Periodically export the audit log via API.
2. Store in external systems (S3, Elasticsearch) for compliance.

---

## Example: Investigating an Incident

```
Scenario: Payments service went down at 14:30 UTC on 2026-05-25.
Who did what?

# Query all actions on the payments namespace between 14:00 and 15:00
GET /api/v1/audit?resource=production/payments&from=2026-05-25T14:00:00Z&to=2026-05-25T15:00:00Z

Results:
14:23 UTC  alice  scale_deployment  production/payments-api  SUCCESS GOD
  details: {from_replicas: 5, to_replicas: 1}  ← scaled DOWN

14:28 UTC  alice  scale_deployment  production/payments-api  SUCCESS GOD
  details: {from_replicas: 1, to_replicas: 5}  ← scaled back up

14:30 UTC  system  pending_op_expired  production/payments-api  EXPIRED
  (a pending operation expired without approval)
```

This tells us: Alice scaled payments-api down to 1 replica at 14:23, then back up at 14:28. The 5-minute window with 1 replica caused the outage.

---

## Compliance Use Cases

- **SOC 2**: Audit logs demonstrate who had access and what they changed.
- **PCI DSS**: All changes to production resources are logged with actor and timestamp.
- **GDPR**: User creation/deletion can be tracked to demonstrate proper data handling.
- **ISO 27001**: Change management records for all Kubernetes mutations.

Export the audit log monthly:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/audit?from=2026-05-01T00:00:00Z&limit=10000" \
  > audit-2026-05.json
```
