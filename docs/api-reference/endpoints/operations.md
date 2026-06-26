# Operations

When the AI wants to do something risky, it creates a **pending operation** and waits for a human to approve or reject it. These endpoints manage that approval queue.

> **Shared note:** All endpoints require a token (any logged-in user). A "session" groups the operations belonging to one chat/diagnosis session.

The pending-operation object looks like this:

| Field | Meaning |
|-------|---------|
| `id` | The operation's ID. |
| `session_id` | Which session it belongs to. |
| `tool_name` | The action the AI wants to run (e.g. `delete_pod`). |
| `tool_inputs` | The inputs for that action (object). |
| `confirmation_message` | Plain-English description of what will happen. |
| `risk_level` | `low` / `medium` / `high`. |
| `created_at` | When proposed (timestamp number). |
| `status` | `pending`, `approved`, `rejected`. |
| `executed_at` | When it ran (or `null`). |
| `result` | The outcome after approval (or `null`). |

---

## POST /api/v1/operations/pending

**What this does:** Creates a new pending operation (normally the AI does this for you).

**Auth required?** Token.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | yes | Session this belongs to. |
| `tool_name` | string | yes | The action to run. |
| `tool_inputs` | object | yes | Inputs for the action. |
| `confirmation_message` | string | yes | What it will do, in plain words. |
| `risk_level` | string | yes | `low`, `medium`, or `high`. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/operations/pending \
  -d '{"session_id":"s1","tool_name":"delete_pod","tool_inputs":{"namespace":"prod","pod":"x"},"confirmation_message":"Delete pod x?","risk_level":"high"}'
```

**Example response (200):** the full pending-operation object with `status: "pending"`.

---

## GET /api/v1/operations/pending

**What this does:** Lists the pending operations for one session.

**Auth required?** Token.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | yes | The session to list operations for. |

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/operations/pending?session_id=s1"
```

**Example response (200):** an array of pending-operation objects.

**Common errors:** `422` if `session_id` is missing.

---

## GET /api/v1/operations/pending/{op_id}

**What this does:** Returns one specific pending operation.

**Auth required?** Token. **Path:** `op_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/operations/pending/op_123
```

**Example response (200):** the pending-operation object.

**Common errors:** `404` operation not found.

---

## POST /api/v1/operations/pending/{op_id}/approve

**What this does:** Approves a pending operation **and runs it**. (in plain terms: clicking "Yes, do it".)

**Auth required?** Token. **Path:** `op_id` (string, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/operations/pending/op_123/approve
```

**Example response (200):** the operation object now with `status: "approved"`, an `executed_at`, and a `result`.

**Common errors:** `404` not found; `400` if it was already approved/rejected.

---

## POST /api/v1/operations/pending/{op_id}/reject

**What this does:** Rejects a pending operation so it never runs.

**Auth required?** Token. **Path:** `op_id` (string, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/operations/pending/op_123/reject
```

**Example response (200):** the operation object now with `status: "rejected"`.
