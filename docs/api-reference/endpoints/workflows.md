# Workflows

A **workflow** is an automation you build in DokOps — either a fixed sequence of steps ("scripted") or an AI **agent** that pursues a goal using approved tools. You can run them manually, on a schedule, or via a webhook, and watch runs live.

> **Shared notes:**
> - Most endpoints require a token (any logged-in user); you manage your own workflows.
> - **Deleting a workflow** requires **God Mode**.
> - The **webhook trigger** is public (so external systems can start a workflow).
> - The **run stream** authenticates with a short-lived `ticket` query param (get one from the stream-ticket endpoint).

---

## GET /api/v1/workflows

**What this does:** Lists your workflows.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/workflows
```

**Example response (200):** array of `{ "id":1,"name":"Nightly cleanup","workflow_type":"scripted","trigger_type":"cron" }`.

---

## POST /api/v1/workflows

**What this does:** Creates a workflow (scripted or agent).

**Auth required?** Token.

**Request body** (JSON) — the most useful fields:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | yes | – | Workflow name. |
| `description` | string | no | `""` | What it does. |
| `trigger_type` | string | no | `manual` | `manual`, `cron`, or `webhook`. |
| `cron_schedule` | string | no | – | Cron expression (if `trigger_type` is `cron`). |
| `trigger_config` | string | no | – | Extra trigger settings (JSON string). |
| `input_schema` | object | no | `{}` | Describes inputs the workflow accepts. |
| `steps` | array of objects | no | `[]` | The steps (for `scripted` workflows). |
| `workflow_type` | string | no | `scripted` | `scripted` or `agent`. |
| `agent_goal` | string | no | – | The goal text (for `agent` workflows). |
| `agent_approved_tools` | array of objects | no | `[]` | Tools the agent may use. |
| `agent_cluster_ids` | array of strings | no | `[]` | Clusters the agent may act on. |
| `agent_minion_ids` | array of strings | no | `[]` | Minions the agent may act on. |
| `agent_max_retries` | integer | no | `3` | Retry limit. |
| `agent_timeout_seconds` | integer | no | `900` | Overall agent timeout. |
| `agent_approval_timeout_seconds` | integer | no | `600` | How long to wait for human approval. |
| `agent_notifications` | object | no | `{}` | Notification settings. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/workflows \
  -d '{"name":"Triage crashloops","workflow_type":"agent","agent_goal":"Find and explain crashlooping pods","trigger_type":"manual"}'
```

**Example response (200):** the created workflow object (including its `id` and, for webhook workflows, a `webhook_token`).

---

## GET /api/v1/workflows/{workflow_id}

**What this does:** Returns one workflow's full definition.

**Auth required?** Token. **Path:** `workflow_id` (integer, required).

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/workflows/1
```

**Example response (200):** the workflow object.

**Common errors:** `404` not found.

---

## PUT /api/v1/workflows/{workflow_id}

**What this does:** Updates a workflow (any subset of fields).

**Auth required?** Token. **Path:** `workflow_id` (integer, required).

**Request body** (JSON): the same fields as Create, all optional.

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/workflows/1 \
  -d '{"name":"Triage crashloops v2","agent_max_retries":5}'
```

**Example response (200):** the updated workflow object.

---

## DELETE /api/v1/workflows/{workflow_id}

**What this does:** Deletes a workflow.

**Auth required?** **God Mode required.** **Path:** `workflow_id` (integer, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/workflows/1
```

**Example response (200):** `{ "status": "deleted" }`

---

## POST /api/v1/workflows/{workflow_id}/run

**What this does:** Runs a workflow now, optionally with input values.

**Auth required?** Token. **Path:** `workflow_id` (integer, required).

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `input` | object | no | `{}` | Inputs matching the workflow's `input_schema`. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/workflows/1/run \
  -d '{"input":{"namespace":"production"}}'
```

**Example response (200):** `{ "run_id": 99, "status": "started" }`

---

## GET /api/v1/workflows/{workflow_id}/runs

**What this does:** Lists past runs of a workflow.

**Auth required?** Token. **Path:** `workflow_id` (integer, required).

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/workflows/1/runs
```

**Example response (200):** array of `{ "run_id":99,"status":"completed","started_at":"..." }`.

---

## GET /api/v1/workflows/runs/{run_id}

**What this does:** Returns one run's status and output.

**Auth required?** Token. **Path:** `run_id` (integer, required).

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/workflows/runs/99
```

**Example response (200):** the run object with step results.

---

## POST /api/v1/workflows/runs/{run_id}/stream-ticket

**What this does:** Exchanges your normal token for a short-lived, single-purpose **ticket** you can safely put in a streaming URL.

**Auth required?** Token. **Path:** `run_id` (integer, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/workflows/runs/99/stream-ticket
```

**Example response (200):** `{ "ticket": "tk_short_lived_abc" }`

---

## GET /api/v1/workflows/runs/{run_id}/stream  *(streaming)*

**What this does:** Streams a run's progress live, step by step.

**Auth required?** A `ticket` from the endpoint above (or a token via header/cookie if your client can send one).

**Path parameters:** `run_id` (integer, required).

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `ticket` | string | no | The short-lived ticket from `stream-ticket`. |

```bash
curl -N "http://localhost:8000/api/v1/workflows/runs/99/stream?ticket=tk_short_lived_abc"
```

**Example stream:** Server-Sent Events (`data: {...}`) with each step's status and the final result.

---

## POST /api/v1/workflows/{workflow_id}/runs/{run_id}/approve

**What this does:** Approves an action a workflow run is waiting on (agent workflows pause for human approval before risky actions).

**Auth required?** Token. **Path:** `workflow_id`, `run_id` (integer, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/workflows/1/runs/99/approve
```

**Example response (200):** `{ "message": "approved" }`

**Common errors:** `400` if the run isn't currently awaiting approval; `404` not found.

---

## POST /api/v1/workflows/{workflow_id}/runs/{run_id}/skip

**What this does:** Skips the action a workflow run is waiting on (instead of approving it).

**Auth required?** Token. **Path:** `workflow_id`, `run_id` (integer, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/workflows/1/runs/99/skip
```

**Example response (200):** `{ "message": "skipped" }`

---

## POST /api/v1/workflows/webhook/{token}  *(public)*

**What this does:** Starts a workflow run from an external system, using the workflow's secret webhook token in the URL.

**Auth required?** **No** — the secret `token` in the path is the authorization.

**Path parameters:** `token` (string, required) — the workflow's webhook token (from the workflow object).

**Request body** (JSON): a free-form payload passed to the workflow as input.

```bash
curl -X POST -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/workflows/webhook/wht_secret123 \
  -d '{"event":"deploy_failed","service":"payments"}'
```

**Example response (200):** `{ "run_id": 100, "status": "started" }`

**Common errors:** `404` if the token doesn't match any workflow.

---

## POST /api/v1/workflows/agents/discover-tools

**What this does:** Asks the AI which tools would help achieve a stated goal — useful when configuring an agent workflow.

**Auth required?** Token.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `goal` | string | yes | The agent's goal. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/workflows/agents/discover-tools \
  -d '{"goal":"find and restart crashlooping pods"}'
```

**Example response (200):** a list of suggested tools.

---

## Jira connector helpers

These three help you build Jira-related workflow steps. All require a token and take Jira connection details in the body.

### POST /api/v1/workflows/connectors/jira/fields

**What this does:** Lists the fields available for a Jira project + issue type (so you can map them in a workflow).

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `base_url` | string | yes | – | Jira base URL. |
| `email` | string | yes | – | Account email (Cloud). |
| `api_token` | string | yes | – | Jira API token. |
| `project_key` | string | yes | – | The project. |
| `issue_type` | string | no | `Bug` | Issue type to inspect. |
| `instance_type` | string | no | `cloud` | `cloud` or `server`. |
| `username` | string | no | `""` | Username (Server). |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/workflows/connectors/jira/fields \
  -d '{"base_url":"https://acme.atlassian.net","email":"me@acme.com","api_token":"...","project_key":"OPS"}'
```

**Example response (200):** a list of Jira fields.

### POST /api/v1/workflows/connectors/jira/issue-types

**What this does:** Lists the issue types available in a Jira project.

**Request body** (JSON): `base_url`, `email`, `api_token`, `project_key` (required); `instance_type` (default `cloud`), `username` optional.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/workflows/connectors/jira/issue-types \
  -d '{"base_url":"https://acme.atlassian.net","email":"me@acme.com","api_token":"...","project_key":"OPS"}'
```

**Example response (200):** a list of issue types.

### POST /api/v1/workflows/connectors/jira/users/search

**What this does:** Searches Jira users (e.g. to set an assignee in a workflow).

**Request body** (JSON): `base_url`, `email`, `api_token`, `query` (required); `instance_type` (default `cloud`), `username` optional.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/workflows/connectors/jira/users/search \
  -d '{"base_url":"https://acme.atlassian.net","email":"me@acme.com","api_token":"...","query":"alice"}'
```

**Example response (200):** a list of matching Jira users.

**Common errors (this group):** `401` not authenticated; `403` God Mode required (delete); `404` not found; `422` missing fields; `502` if Jira is unreachable.
