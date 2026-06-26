# Chat

These endpoints power **persistent AI chat conversations** — like a saved chat thread with the DokOps AI that you can return to later. (Unlike `/ai/*/stream`, these are saved in the database.)

> **Shared note:** All endpoints require a token (any logged-in user). You only see your own conversations.

---

## POST /api/v1/chat/conversations

**What this does:** Starts a new, empty chat conversation.

**Auth required?** Token. No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/chat/conversations
```

**Example response (200):** `{ "id": "conv_abc123", "title": "New conversation", "created_at": "2026-06-26T10:00:00Z" }`

---

## GET /api/v1/chat/conversations

**What this does:** Lists your saved conversations (most recent first).

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/chat/conversations
```

**Example response (200):** array of `{ "id": "conv_abc123", "title": "Payments outage", "updated_at": "..." }`.

---

## GET /api/v1/chat/conversations/{conversation_id}

**What this does:** Opens one conversation and returns all its messages.

**Auth required?** Token. **Path:** `conversation_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/chat/conversations/conv_abc123
```

**Example response (200):**

```json
{
  "id": "conv_abc123",
  "title": "Payments outage",
  "messages": [
    { "role": "user", "content": "why is payments-api down?" },
    { "role": "assistant", "content": "It can't reach its database..." }
  ]
}
```

**Common errors:** `404` conversation not found (or not yours).

---

## PATCH /api/v1/chat/conversations/{conversation_id}

**What this does:** Renames a conversation.

**Auth required?** Token. **Path:** `conversation_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `title` | string | yes | New title. |

```bash
curl -X PATCH -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/chat/conversations/conv_abc123 \
  -d '{"title": "Payments DB outage – June"}'
```

**Example response (200):** `{ "id": "conv_abc123", "title": "Payments DB outage – June" }`

---

## DELETE /api/v1/chat/conversations/{conversation_id}

**What this does:** Permanently deletes a conversation.

**Auth required?** Token. **Path:** `conversation_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/chat/conversations/conv_abc123
```

**Example response (200):** `{ "status": "deleted" }`

---

## POST /api/v1/chat/conversations/{conversation_id}/message  *(streaming)*

**What this does:** Sends a message into a conversation and **streams** the AI's reply back live. The full exchange is saved.

**Auth required?** Token. **Headers:** `X-Cluster-Context` (optional).

**Path parameters:** `conversation_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `content` | string | yes | Your message. |
| `runbook_id` | string | no | Force a specific runbook. |

```bash
curl -N -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/chat/conversations/conv_abc123/message \
  -d '{"content": "what pods are failing in production?"}'
```

**Example stream:** Server-Sent Events (`data: {...}` lines) with the AI's steps and final answer, same shape as the `/ai/*/stream` endpoints.

---

## POST /api/v1/chat/conversations/{conversation_id}/compact

**What this does:** "Compacts" a long conversation — summarizes older messages so the thread stays within the AI's memory limit while keeping context.

**Auth required?** Token. **Path:** `conversation_id` (string, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/chat/conversations/conv_abc123/compact
```

**Example response (200):** `{ "status": "compacted", "messages_summarized": 12 }`
