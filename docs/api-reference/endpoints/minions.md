# Minions

A **minion** is a small DokOps agent you install on a server. It connects back to DokOps and lets you run jobs, see Docker containers/services, scan for OS patches, and run "blueprints" on that machine — without DokOps needing direct network access to it.

> **Shared notes:**
> - All endpoints require a token (any logged-in user) except the streaming one, which uses a `token` query param.
> - **Approving** and **deleting** a minion require **God Mode**.
> - "Live" endpoints reach out to the minion in real time; the minion must be online.

---

## GET /api/v1/minions/

**What this does:** Lists every minion that has enrolled, with its status (online/offline, approved/pending).

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/minions/
```

**Example response (200):**

```json
[
  { "id": "m_12", "hostname": "web-01", "status": "online", "approved": true, "os": "ubuntu-22.04" }
]
```

---

## GET /api/v1/minions/{minion_id}

**What this does:** Returns full details about one minion.

**Auth required?** Token. **Path:** `minion_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/minions/m_12
```

**Example response (200):** the minion object (hostname, OS, status, last-seen, capabilities).

**Common errors:** `404` not found.

---

## POST /api/v1/minions/{minion_id}/approve

**What this does:** Approves a pending minion so it's allowed to receive jobs. (in plain terms: "yes, this server is really ours.")

**Auth required?** **God Mode required.** **Path:** `minion_id` (string, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/m_12/approve
```

**Example response (200):** `{ "status": "approved" }`

**Common errors:** `403` God Mode not active.

---

## DELETE /api/v1/minions/{minion_id}

**What this does:** Removes a minion from DokOps.

**Auth required?** **God Mode required.** **Path:** `minion_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/m_12
```

**Example response (200):** `{ "status": "deleted" }`

---

## POST /api/v1/minions/{minion_id}/jobs

**What this does:** Sends a job (command/task) to a minion to run.

**Auth required?** Token. **Path:** `minion_id` (string, required).

**Request body** (JSON): a job-definition object, e.g. `{"type":"shell","command":"uptime"}` (fields depend on the job type).

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/minions/m_12/jobs \
  -d '{"type":"shell","command":"uptime"}'
```

**Example response (200):** `{ "job_id": "job_77", "status": "queued" }`

---

## GET /api/v1/minions/{minion_id}/jobs

**What this does:** Lists jobs that have been sent to a minion.

**Auth required?** Token. **Path:** `minion_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/minions/m_12/jobs
```

**Example response (200):** array of `{ "job_id": "job_77", "status": "completed", "created_at": "..." }`.

---

## GET /api/v1/minions/{minion_id}/jobs/{job_id}

**What this does:** Returns one job's status and output.

**Auth required?** Token. **Path:** `minion_id`, `job_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/m_12/jobs/job_77
```

**Example response (200):** `{ "job_id": "job_77", "status": "completed", "output": "10:00 up 3 days..." }`

---

## POST /api/v1/minions/patches/scan-all

**What this does:** Asks **all** online minions to scan for available OS patches right now.

**Auth required?** Token. No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/patches/scan-all
```

**Example response (200):** `{ "status": "scan requested", "minions": 14 }`

---

## POST /api/v1/minions/{minion_id}/patches/scan

**What this does:** Asks one minion to scan for available OS patches immediately.

**Auth required?** Token. **Path:** `minion_id` (string, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/m_12/patches/scan
```

**Example response (200):** `{ "status": "scan requested" }`

---

## GET /api/v1/minions/{minion_id}/services

**What this does:** Lists the services DokOps knows about on a minion (including manual overrides).

**Auth required?** Token. **Path:** `minion_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/minions/m_12/services
```

**Example response (200):** array of `{ "id": "svc_1", "service_type": "postgres", "port": 5432, "install_type": "native" }`.

---

## POST /api/v1/minions/{minion_id}/services

**What this does:** Manually tells DokOps that a particular service runs on this minion (a "service override").

**Auth required?** Token. **Path:** `minion_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `service_type` | string | yes | – | e.g. `postgres`, `redis`, `nginx`. |
| `install_type` | string | no | `native` | `native` (installed directly) or `container`. |
| `container_name` | string | no | – | The container name (if `install_type` is `container`). |
| `port` | integer | yes | – | The port the service listens on. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/minions/m_12/services \
  -d '{"service_type":"postgres","port":5432,"install_type":"native"}'
```

**Example response (200):** the created service override.

---

## POST /api/v1/minions/{minion_id}/services/discover

**What this does:** Asks the minion to auto-detect what services are running on it.

**Auth required?** Token. **Path:** `minion_id` (string, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/m_12/services/discover
```

**Example response (200):** `{ "status": "discovery requested" }`

---

## DELETE /api/v1/minions/{minion_id}/services/{service_id}

**What this does:** Removes a manual service override.

**Auth required?** Token. **Path:** `minion_id`, `service_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/m_12/services/svc_1
```

**Example response (200):** `{ "status": "deleted" }`

---

## GET /api/v1/minions/{minion_id}/portainer

**What this does:** Returns the Portainer connection settings stored for this minion. (Portainer = a Docker management UI.)

**Auth required?** Token. **Path:** `minion_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/minions/m_12/portainer
```

**Example response (200):** `{ "base_url": "http://localhost:9000", "endpoint_id": 1, "configured": true }`

---

## PUT /api/v1/minions/{minion_id}/portainer

**What this does:** Saves the Portainer connection settings for this minion.

**Auth required?** Token. **Path:** `minion_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `base_url` | string | yes | – | Portainer URL (as seen by the minion). |
| `api_key` | string | yes | – | Portainer API key. |
| `endpoint_id` | integer | no | `1` | Which Portainer endpoint to use. |

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/minions/m_12/portainer \
  -d '{"base_url":"http://localhost:9000","api_key":"ptr_...","endpoint_id":1}'
```

**Example response (200):** `{ "status": "saved" }`

---

## GET /api/v1/minions/{minion_id}/resources/services  *(live)*

**What this does:** Asks the minion, live, for the system services running on it.

**Auth required?** Token. **Path:** `minion_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/m_12/resources/services
```

**Example response (200):** array of running services with their state.

**Common errors:** `502`/`504` if the minion is offline or doesn't respond.

---

## GET /api/v1/minions/{minion_id}/resources/services/{name}/logs  *(live)*

**What this does:** Fetches live logs for one system service on the minion.

**Auth required?** Token. **Path:** `minion_id`, `name` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/m_12/resources/services/nginx/logs
```

**Example response (200):** `{ "logs": "..." }`

---

## GET /api/v1/minions/{minion_id}/resources/docker  *(live)*

**What this does:** Asks the minion, live, for its Docker containers (via the local Portainer/Docker).

**Auth required?** Token. **Path:** `minion_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/m_12/resources/docker
```

**Example response (200):** array of `{ "name": "web", "image": "nginx", "state": "running" }`.

---

## GET /api/v1/minions/{minion_id}/resources/docker/{container}/logs  *(live)*

**What this does:** Fetches live logs for one Docker container on the minion.

**Auth required?** Token. **Path:** `minion_id`, `container` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/m_12/resources/docker/web/logs
```

**Example response (200):** `{ "logs": "..." }`

---

## POST /api/v1/minions/{minion_id}/resources/docker/{container}/analyze

**What this does:** Asks the AI to analyze a container's logs/state and explain any problems.

**Auth required?** Token. **Path:** `minion_id`, `container` (string, required).

**Request body** (JSON): an optional object with extra context, e.g. `{"query":"why is this restarting?"}`.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/minions/m_12/resources/docker/web/analyze \
  -d '{"query":"why is this container unhealthy?"}'
```

**Example response (200):** `{ "analysis": "The container exits because port 80 is already in use..." }`

---

## GET /api/v1/minions/{minion_id}/blueprint

**What this does:** Previews the blueprint(s) that would apply to this minion (compiled view).

**Auth required?** Token. **Path:** `minion_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/m_12/blueprint
```

**Example response (200):** the compiled blueprint for this minion (resources to install/configure).

---

## POST /api/v1/minions/{minion_id}/blueprint/run

**What this does:** Runs the applicable blueprint on the minion (installs/configures resources).

**Auth required?** Token. **Path:** `minion_id` (string, required).

**Request body** (JSON): an optional object (e.g. to select which blueprint or pass variables).

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/minions/m_12/blueprint/run -d '{}'
```

**Example response (200):** `{ "run_id": "run_55", "status": "started" }` — follow it with the stream endpoint below.

---

## GET /api/v1/minions/{minion_id}/blueprint/runs

**What this does:** Lists past blueprint runs for a minion.

**Auth required?** Token. **Path:** `minion_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/m_12/blueprint/runs
```

**Example response (200):** array of `{ "run_id": "run_55", "status": "completed", "started_at": "..." }`.

---

## GET /api/v1/minions/blueprint/runs/{run_id}

**What this does:** Returns one blueprint run's status and result.

**Auth required?** Token. **Path:** `run_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/blueprint/runs/run_55
```

**Example response (200):** the run object with step-by-step results.

---

## GET /api/v1/minions/blueprint/runs/{run_id}/stream  *(streaming)*

**What this does:** Streams a blueprint run's progress live, step by step.

**Auth required?** Token via the **`token` query parameter** (browser streaming can't send headers).

**Path parameters:** `run_id` (string, required).

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `token` | string | yes | Your JWT token. |

```bash
curl -N "http://localhost:8000/api/v1/minions/blueprint/runs/run_55/stream?token=$TOKEN"
```

**Example stream:** Server-Sent Events (`data: {...}`) with each step's status, ending in a final result.

**Common errors:** `401` if `token` is missing/invalid.
