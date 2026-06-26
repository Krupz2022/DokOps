# Alerts

These endpoints handle **incoming alerts** from external monitoring systems, turn them into **incidents**, and let the AI run automatic root-cause analysis (RCA). There's also config for webhooks, RCA limits, and Jira ticketing.

> **Shared notes:**
> - The inbound webhook endpoint is **public** (so monitoring tools can post to it without a login).
> - Most reading is for any logged-in user; **policy, webhook-config, RCA-concurrency, resolving incidents, and Jira config/test** are **admin-only**.

---

## POST /api/v1/alerts/webhook/{source}  *(public)*

**What this does:** Receives an alert from an external monitoring system (e.g. Prometheus Alertmanager, Grafana, Elastic). DokOps queues it and may auto-run an RCA.

**Auth required?** **No** — this is meant to be called by your monitoring system. (Secure it with the webhook config / a secret in the payload as appropriate for your setup.)

**Path parameters:** `source` (string, required) — a label for where the alert came from, e.g. `prometheus`, `grafana`, `elastic`.

**Request body** (JSON): the alert payload from your monitoring system (free-form; shape depends on the source).

```bash
curl -X POST -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/alerts/webhook/prometheus \
  -d '{"alerts":[{"labels":{"alertname":"PodCrashLooping","namespace":"prod"},"status":"firing"}]}'
```

**Example response (202 Accepted):** `{ "status": "accepted", "incident_id": 41 }` — accepted for background processing.

---

## GET /api/v1/alerts/incidents

**What this does:** Lists incidents created from alerts.

**Auth required?** Token.

**Query parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `status` | string | no | – | Filter by status (e.g. `open`, `resolved`). |
| `severity` | string | no | – | Filter by severity (e.g. `critical`, `warning`). |
| `limit` | integer | no | `50` | Max to return. |
| `offset` | integer | no | `0` | How many to skip (paging). |

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/alerts/incidents?status=open&limit=20"
```

**Example response (200):** array of `{ "id":41,"title":"PodCrashLooping","severity":"critical","status":"open","created_at":"..." }`.

---

## GET /api/v1/alerts/incidents/{incident_id}

**What this does:** Returns one incident in detail, including any AI root-cause analysis.

**Auth required?** Token. **Path:** `incident_id` (integer, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/alerts/incidents/41
```

**Example response (200):** the incident object with `rca` text and timeline.

**Common errors:** `404` not found.

---

## POST /api/v1/alerts/incidents/{incident_id}/resolve

**What this does:** Marks an incident as resolved.

**Auth required?** Admin / Superuser. **Path:** `incident_id` (integer, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/alerts/incidents/41/resolve
```

**Example response (200):** the incident object now `status: "resolved"`.

---

## GET /api/v1/alerts/policy

**What this does:** Returns the alert-handling policy (when to auto-RCA, severity thresholds, etc.).

**Auth required?** Admin / Superuser.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/alerts/policy
```

**Example response (200):** the policy object.

---

## PUT /api/v1/alerts/policy

**What this does:** Updates the alert-handling policy.

**Auth required?** Admin / Superuser.

**Request body** (JSON): the policy object (free-form; mirrors what `GET` returns).

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/alerts/policy \
  -d '{"auto_rca": true, "min_severity": "warning"}'
```

**Example response (200):** the updated policy.

---

## GET /api/v1/alerts/webhook-config

**What this does:** Returns webhook configuration (e.g. expected secrets/sources).

**Auth required?** Admin / Superuser.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/alerts/webhook-config
```

**Example response (200):** the webhook-config object.

---

## PUT /api/v1/alerts/webhook-config

**What this does:** Updates webhook configuration.

**Auth required?** Admin / Superuser.

**Request body** (JSON): the webhook-config object (free-form).

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/alerts/webhook-config \
  -d '{"shared_secret":"abc123"}'
```

**Example response (200):** the updated config.

---

## GET /api/v1/alerts/rca-concurrency

**What this does:** Returns how many automatic RCA jobs can run at once.

**Auth required?** Admin / Superuser.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/alerts/rca-concurrency
```

**Example response (200):** `{ "max_concurrent_rca": 3 }`

---

## PUT /api/v1/alerts/rca-concurrency

**What this does:** Sets how many automatic RCA jobs can run at once (to control AI cost/load).

**Auth required?** Admin / Superuser.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `max_concurrent_rca` | integer | yes | Maximum parallel RCA jobs. |

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/alerts/rca-concurrency \
  -d '{"max_concurrent_rca": 3}'
```

**Example response (200):** `{ "max_concurrent_rca": 3 }`

---

## GET /api/v1/alerts/jira-config

**What this does:** Returns the Jira ticketing config used when incidents are filed as tickets.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/alerts/jira-config
```

**Example response (200):** `{ "base_url":"https://acme.atlassian.net","project_key":"OPS","instance_type":"cloud","configured":true }`

---

## PUT /api/v1/alerts/jira-config

**What this does:** Saves the Jira ticketing config.

**Auth required?** Admin / Superuser.

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `instance_type` | string | no | `cloud` | `cloud` or `server`/`datacenter`. |
| `base_url` | string | yes | – | Your Jira base URL. |
| `email` | string | no | – | Account email (Cloud). |
| `username` | string | no | – | Username (Server). |
| `api_token` | string | no | – | API token / password. |
| `project_key` | string | no | – | Default project for new tickets. |

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/alerts/jira-config \
  -d '{"base_url":"https://acme.atlassian.net","email":"me@acme.com","api_token":"...","project_key":"OPS"}'
```

**Example response (200):** `{ "status": "saved" }`

---

## POST /api/v1/alerts/jira-test

**What this does:** Tests the saved Jira credentials.

**Auth required?** Admin / Superuser. No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/alerts/jira-test
```

**Example response (200):** `{ "success": true }`
