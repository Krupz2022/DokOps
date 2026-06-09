# God Mode

God Mode is DokOps's safety mechanism for write operations. By default, DokOps is read-only — you can inspect everything but change nothing. Enabling God Mode unlocks destructive and mutating operations, but every action is logged in an immutable audit trail and requires explicit confirmation.

---

## Normal Mode vs. God Mode

| Capability | Normal Mode | God Mode |
|-----------|------------|---------|
| View pods, deployments, services | ✅ | ✅ |
| View logs and events | ✅ | ✅ |
| AI diagnostics (read-only) | ✅ | ✅ |
| Run Helm list/status/history | ✅ | ✅ |
| Scale a deployment | ❌ | ✅ |
| Restart a deployment | ❌ | ✅ |
| Delete a pod | ❌ | ✅ |
| Delete a namespace | ❌ | ✅ |
| Patch a ConfigMap | ❌ | ✅ |
| Helm rollback/upgrade/delete | ❌ | ✅ |
| Execute into a pod | ❌ | ✅ |
| Apply patches on Minions | ❌ | ✅ |
| Bulk Minion commands | ❌ | ✅ |

---

## Enabling God Mode

1. Look for the **Normal Mode** banner at the top of the screen.
2. Click the banner (or the lock icon).
3. Read the warning dialog:
   > "You are about to enable God Mode. All mutating operations will be logged. Proceed?"
4. Click **Enable God Mode**.

The header banner turns **red** with "GOD MODE" displayed. All write operations are now available.

---

## Disabling God Mode

Click the red **GOD MODE** banner → click **Disable**.

God Mode also resets to Normal Mode on logout. It is **never** persistent across sessions.

---

## Pending Operations

Some God Mode actions go through a **Pending Operations** queue before execution. This provides an additional approval layer for particularly destructive actions (e.g., namespace deletion, bulk Minion operations).

### How It Works

1. You trigger a destructive action (e.g., "Delete namespace `prod-v1`").
2. DokOps creates a **Pending Operation** with:
   - Action details (what will be done)
   - Requester (your username)
   - Timestamp
   - Expiry (operations expire after 10 minutes if not approved)
3. A confirmation dialog appears in the UI.
4. Click **Approve** — the operation executes.
5. Click **Reject** — the operation is cancelled.
6. The result (approved/rejected/expired) is recorded in the audit log.

### Viewing Pending Operations

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/operations/pending

# Approve
curl -X POST http://localhost:8000/api/v1/operations/pending/{op_id}/approve \
  -H "Authorization: Bearer $TOKEN"

# Reject
curl -X POST http://localhost:8000/api/v1/operations/pending/{op_id}/reject \
  -H "Authorization: Bearer $TOKEN"
```

---

## Audit Trail

Every God Mode action (successful or rejected) is recorded in the **Audit Log**:

| Field | Value |
|-------|-------|
| Timestamp | ISO 8601 datetime |
| Actor | Username who performed the action |
| Action | Human-readable description |
| Resource | Kubernetes resource affected |
| Result | `SUCCESS`, `FAILURE`, `REJECTED`, `EXPIRED` |
| Mode | `GOD` or `NORMAL` |
| Source | `K8S`, `AZURE`, `SYSTEM`, `MINION` |

### Viewing the Audit Log

1. Click **Admin** in the sidebar.
2. Click the **Audit Logs** tab.
3. Filter by: actor, action, resource, date range.

### Via API

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/audit?limit=50&actor=admin"
```

---

## Role Enforcement

God Mode actions are restricted based on user role:

| Role | Can Enable God Mode | Can Approve Pending Ops |
|------|-------------------|------------------------|
| **admin** | ✅ | ✅ |
| **viewer** | ❌ | ❌ |

Viewers attempting God Mode operations receive HTTP 403.

---

## Example: Scaling a Deployment with Audit Trail

```
1. User enables God Mode
2. User goes to Resources → Deployments → payments-api
3. User clicks "Scale" → enters 5 replicas → clicks "Confirm"

4. DokOps creates Pending Operation:
   {
     "action": "scale_deployment",
     "resource": "payments-api",
     "namespace": "production",
     "params": {"replicas": 5},
     "requester": "alice",
     "expires_at": "2026-05-25T14:45:00Z"
   }

5. Confirmation dialog appears: "Scale payments-api to 5 replicas?"
6. User clicks "Approve"

7. Kubernetes API call:
   PATCH /apis/apps/v1/namespaces/production/deployments/payments-api/scale

8. Audit log entry:
   {
     "timestamp": "2026-05-25T14:35:22Z",
     "actor": "alice",
     "action": "scale_deployment",
     "resource": "production/payments-api",
     "result": "SUCCESS",
     "mode": "GOD",
     "details": {"from_replicas": 3, "to_replicas": 5}
   }
```

---

## Best Practices

- Enable God Mode only when you need it. Disable it immediately after.
- Use a dedicated admin account for God Mode operations — this makes audit logs more meaningful.
- For production clusters, consider requiring two-person approval (implement via Pending Operations + manual out-of-band confirmation).
- Review the audit log weekly to catch unexpected actions.
- Set `AUTH_SECRET_KEY` to a strong random value in production — stolen JWT tokens could be used to perform God Mode operations.
