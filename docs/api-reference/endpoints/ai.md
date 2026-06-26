# AI

These endpoints power the **AI assistant** that diagnoses cluster problems, analyzes logs, and runs "runbooks" (saved troubleshooting recipes). Several of them **stream** their answer back live.

> **Shared notes:**
> - The AI config endpoints are **admin-only**; the analysis/diagnosis endpoints work for any logged-in user.
> - Streaming endpoints send Server-Sent Events (newline-delimited `data: {...}` lines). Use `curl -N` to see them live.
> - *Runbook* (in plain terms) = a saved, step-by-step troubleshooting guide the AI can follow.

---

## GET /api/v1/ai/config

**What this does:** Returns the current AI settings (provider, model, etc.) — secret API keys are hidden.

**Auth required?** Admin / Superuser.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/ai/config
```

**Example response (200):** `{ "provider": "azure_openai", "model": "gpt-4o", "configured": true }`

---

## POST /api/v1/ai/config

**What this does:** Saves AI settings (which provider/model to use, API keys, endpoints).

**Auth required?** Admin / Superuser.

**Request body** (JSON): a free-form settings object (provider name, model, API key, endpoint, etc.).

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/ai/config \
  -d '{"provider": "azure_openai", "model": "gpt-4o", "api_key": "sk-...", "endpoint": "https://..."}'
```

**Example response (200):** `{ "status": "saved" }`

---

## POST /api/v1/ai/test

**What this does:** Checks that DokOps can actually reach and talk to the configured AI provider.

**Auth required?** Admin / Superuser.

**Request body** (JSON, optional): optionally a config to test instead of the saved one.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/ai/test -d '{}'
```

**Example response (200):** `{ "success": true, "message": "Connection OK" }`

---

## POST /api/v1/ai/analyze/logs

**What this does:** Asks the AI to read a pod's logs and explain what's wrong, in plain language.

**Auth required?** Token.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `namespace` | string | yes | The pod's namespace. |
| `pod_name` | string | yes | The pod to analyze. |
| `query` | string | yes | Your question, e.g. "why is this crashing?" |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/ai/analyze/logs \
  -d '{"namespace":"production","pod_name":"payments-api-xyz","query":"why is this crashing?"}'
```

**Example response (200):** an AI explanation, e.g. `{ "analysis": "The pod cannot reach its database because..." }`

---

## GET /api/v1/ai/runbooks

**What this does:** Lists the available runbooks (saved troubleshooting recipes).

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/ai/runbooks
```

**Example response (200):** array of runbooks, e.g. `[{ "id": "crashloop", "name": "CrashLoopBackOff RCA" }]`.

---

## POST /api/v1/ai/runbooks/match

**What this does:** Given a plain-English question, asks the AI which runbook best fits.

**Auth required?** Token.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query` | string | yes | What you're trying to troubleshoot. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/ai/runbooks/match \
  -d '{"query": "my pod keeps restarting"}'
```

**Example response (200):** `{ "runbook_id": "crashloop", "confidence": 0.92 }`

---

## POST /api/v1/ai/runbooks/{runbook_id}

**What this does:** Creates or updates a runbook (its YAML/markdown definition).

**Auth required?** Admin / Superuser.

**Path parameters:** `runbook_id` (string, required).

**Request body** (JSON string): the runbook content as a string.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/ai/runbooks/crashloop \
  -d '"# CrashLoop Runbook\n1. Get pod\n2. Get events\n3. Get logs"'
```

**Example response (200):** `{ "status": "saved", "id": "crashloop" }`

---

## POST /api/v1/ai/diagnose/stream  *(streaming)*

**What this does:** Streams a live AI diagnosis of a single pod — you watch the AI's steps ("Fetching events…", "Reading logs…") then the conclusion.

**Auth required?** Token. **Headers:** `X-Cluster-Context` (optional).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `namespace` | string | yes | The pod's namespace. |
| `pod_name` | string | yes | The pod to diagnose. |
| `query` | string | yes | Your question/intent. |
| `runbook_id` | string | no | Force a specific runbook to be followed. |

```bash
curl -N -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/ai/diagnose/stream \
  -d '{"namespace":"production","pod_name":"payments-api-xyz","query":"what is wrong?"}'
```

**Example stream:**

```
data: {"type": "step", "content": "Fetching pod events..."}
data: {"type": "step", "content": "Reading recent logs..."}
data: {"type": "result", "message": "The pod is failing because the database password is wrong."}
data: {"type": "done"}
```

---

## POST /api/v1/ai/global/stream  *(streaming)*

**What this does:** Streams a live AI answer to a **cluster-wide** question (not tied to one pod). The AI can list pods, read events, etc., to answer.

**Auth required?** Token. **Headers:** `X-Cluster-Context` (optional).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query` | string | yes | Your question, e.g. "what pods are failing?" |
| `runbook_id` | string | no | Force a specific runbook. |

```bash
curl -N -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/ai/global/stream \
  -d '{"query": "what pods are failing across the cluster?"}'
```

**Example stream:** same `data: {...}` event shape as `diagnose/stream`.

---

## POST /api/v1/ai/analyze/batch  *(streaming)*

**What this does:** Streams an AI analysis across **several pods at once** (a "ReAct" reasoning loop).

**Auth required?** Token. **Headers:** `X-Cluster-Context` (optional).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `pods` | array of objects | yes | The pods to analyze, e.g. `[{"namespace":"prod","name":"a"}, ...]`. |
| `query` | string | yes | The question to apply to all of them. |
| `runbook_id` | string | no | Force a specific runbook. |

```bash
curl -N -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/ai/analyze/batch \
  -d '{"pods":[{"namespace":"prod","name":"a"},{"namespace":"prod","name":"b"}],"query":"summarize failures"}'
```

**Example stream:** streamed `data: {...}` events ending in a `result` then `done`.

---

## POST /api/v1/ai/command

**What this does:** Sends a natural-language command to the AI. It replies either with an **action proposal** (a suggested change for you to approve) or **search results**.

**Auth required?** Token.

**Request body** (JSON): a free-form object, typically `{"command": "scale payments-api to 5 replicas"}`.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/ai/command \
  -d '{"command": "restart the payments-api deployment in production"}'
```

**Example response (200):**

```json
{
  "type": "action_proposal",
  "tool": "restart_deployment",
  "inputs": { "namespace": "production", "deployment": "payments-api" },
  "confirmation_message": "Restart deployment payments-api in production?",
  "risk_level": "medium"
}
```

Use the [Operations](./operations.md) endpoints to approve or reject a proposed action.

**Common errors (this group):** `401` not authenticated; `403` admin-only on config/test/runbook-create; `422` missing fields; `500`/`502` if the AI provider is unreachable.
