# Patching

These endpoints manage **OS patch compliance** across your fleet of minions: see who's up to date, build promotion **pipelines** (test → staging → production), schedule automatic patching, and track results.

> **Shared notes:**
> - Reading reports is allowed for any logged-in user.
> - **Applying patches and changing pipelines/schedules** require **God Mode**.
> - Key terms (in plain terms): a *pipeline* is a sequence of *stages* (e.g. "test" then "prod"); a *promotion* is one batch of patches moving through a stage; a *CVE/advisory* is a published security issue a patch fixes.

---

## Reporting (read-only)

### GET /api/v1/patches/compliance

**What this does:** Per-device summary of how many patches each minion is missing. Filterable by org or group.

**Auth required?** Token.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `org_id` | string | no | Only this organisation. |
| `group_id` | string | no | Only this group. |

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/patches/compliance?group_id=grp_3"
```

**Example response (200):** array of `{ "minion_id":"m_12","hostname":"web-01","missing":4,"security":2,"last_scan":"..." }`.

---

### GET /api/v1/patches/by-device/{minion_id}

**What this does:** Lists all known patches for one device.

**Auth required?** Token. **Path:** `minion_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patches/by-device/m_12
```

**Example response (200):** array of patch records for that minion.

---

### GET /api/v1/patches/minions/{minion_id}/patches

**What this does:** Same idea — the patch list for one minion (alternate path used by the UI).

**Auth required?** Token. **Path:** `minion_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patches/minions/m_12/patches
```

**Example response (200):** array of patch records.

---

### GET /api/v1/patches/by-cve

**What this does:** Aggregated view — one row per security advisory/CVE, with how many devices it affects. (Excludes deleted minions.)

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/patches/by-cve
```

**Example response (200):** array of `{ "cve":"CVE-2026-1234","severity":"high","affected_devices":12 }`.

---

## Pipelines

### GET /api/v1/patches/organisations/{org_id}/pipelines

**What this does:** Lists the patch pipelines in an organisation.

**Auth required?** Token. **Path:** `org_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patches/organisations/org_1/pipelines
```

**Example response (200):** array of pipeline objects with their stages.

---

### POST /api/v1/patches/organisations/{org_id}/pipelines

**What this does:** Creates a new patch pipeline in an org.

**Auth required?** **God Mode required.** **Path:** `org_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | yes | – | Pipeline name. |
| `auto_promote` | boolean | no | `false` | Automatically move to the next stage when one succeeds. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/patches/organisations/org_1/pipelines \
  -d '{"name":"Monthly Patching","auto_promote":false}'
```

**Example response (200):** the created pipeline object.

---

### DELETE /api/v1/patches/pipelines/{pipeline_id}

**What this does:** Deletes a pipeline.

**Auth required?** **God Mode required.** **Path:** `pipeline_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patches/pipelines/pl_1
```

**Example response (200):** `{ "status": "deleted" }`

---

### POST /api/v1/patches/pipelines/{pipeline_id}/stages

**What this does:** Adds a stage (e.g. "test", "prod") to a pipeline.

**Auth required?** **God Mode required.** **Path:** `pipeline_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | yes | Stage name. |
| `group_id` | string | yes | The minion group this stage targets. |
| `order` | integer | yes | Position in the pipeline (1, 2, 3…). |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/patches/pipelines/pl_1/stages \
  -d '{"name":"test","group_id":"grp_test","order":1}'
```

**Example response (200):** the created stage object.

---

### PATCH /api/v1/patches/pipelines/{pipeline_id}/stages/{stage_id}

**What this does:** Renames a stage or points it at a different group.

**Auth required?** **God Mode required.** **Path:** `pipeline_id`, `stage_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | no | New stage name. |
| `group_id` | string | no | New target group. |

```bash
curl -X PATCH -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/patches/pipelines/pl_1/stages/st_1 \
  -d '{"name":"staging"}'
```

**Example response (200):** the updated stage object.

---

### DELETE /api/v1/patches/pipelines/{pipeline_id}/stages/{stage_id}

**What this does:** Deletes a stage from a pipeline.

**Auth required?** **God Mode required.** **Path:** `pipeline_id`, `stage_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patches/pipelines/pl_1/stages/st_1
```

**Example response (200):** `{ "status": "deleted" }`

---

### POST /api/v1/patches/pipelines/{pipeline_id}/stages/{stage_id}/apply

**What this does:** Starts patching for a stage — the first promotion. This is the "go" button for a stage.

**Auth required?** **God Mode required.** **Path:** `pipeline_id`, `stage_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `scope` | string | yes | – | What to patch, e.g. `all`, `security`, `custom`. |
| `custom_packages` | array of strings | no | – | Specific packages (when `scope` is `custom`). |
| `reboot_after` | boolean | no | `false` | Reboot the machines after patching. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/patches/pipelines/pl_1/stages/st_1/apply \
  -d '{"scope":"security","reboot_after":true}'
```

**Example response (200):** `{ "promotion_id": "promo_1", "status": "started" }`

---

### POST /api/v1/patches/pipelines/{pipeline_id}/stages/{stage_id}/promote

**What this does:** Promotes the exact same ("frozen") set of packages from this stage to the **next** stage in the pipeline — so prod gets precisely what test got.

**Auth required?** **God Mode required.** **Path:** `pipeline_id`, `stage_id` (string, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patches/pipelines/pl_1/stages/st_1/promote
```

**Example response (200):** `{ "promotion_id": "promo_2", "status": "started", "to_stage": "st_2" }`

---

### GET /api/v1/patches/pipelines/{pipeline_id}/promotions

**What this does:** Lists the promotions (patch batches) that have run through a pipeline.

**Auth required?** Token. **Path:** `pipeline_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patches/pipelines/pl_1/promotions
```

**Example response (200):** array of promotion summaries with status.

---

### GET /api/v1/patches/promotions/{promotion_id}/results

**What this does:** Per-minion results for one promotion, including which advisory each patch addressed.

**Auth required?** Token. **Path:** `promotion_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patches/promotions/promo_1/results
```

**Example response (200):** array of `{ "minion_id":"m_12","status":"success","packages":["openssl"],"rebooted":true }`.

---

### POST /api/v1/patches/promotions/{promo_id}/retry

**What this does:** Re-runs the patch job only on the minions that **failed** in a partial promotion.

**Auth required?** **God Mode required.** **Path:** `promo_id` (string, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patches/promotions/promo_1/retry
```

**Example response (200):** `{ "status": "retrying", "minions": 3 }`

---

### POST /api/v1/patches/promotions/{promo_id}/exclude/{minion_id}

**What this does:** Excludes a specific minion from a promotion (so it won't be patched in this batch).

**Auth required?** **God Mode required.** **Path:** `promo_id`, `minion_id` (string, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patches/promotions/promo_1/exclude/m_12
```

**Example response (200):** `{ "status": "excluded", "minion_id": "m_12" }`

---

## Apply directly to a group

### POST /api/v1/patches/groups/{group_id}/patches/apply

**What this does:** Applies patches directly to all minions in a group (without a pipeline).

**Auth required?** **God Mode required.** **Path:** `group_id` (string, required).

**Request body** (JSON): same as the stage `apply` body — `scope` (required), optional `custom_packages`, `reboot_after`.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/patches/groups/grp_3/patches/apply \
  -d '{"scope":"all","reboot_after":false}'
```

**Example response (200):** `{ "status": "started", "minions": 8 }`

---

## Schedules

### GET /api/v1/patches/schedules/

**What this does:** Lists automatic patch schedules.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/patches/schedules/
```

**Example response (200):** array of schedule objects.

---

### POST /api/v1/patches/schedules/

**What this does:** Creates a recurring patch schedule (cron-based) for a pipeline stage.

**Auth required?** **God Mode required.**

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `pipeline_id` | string | yes | – | The pipeline. |
| `stage_id` | string | yes | – | The stage to patch on schedule. |
| `cron_expr` | string | yes | – | Cron expression (when to run). |
| `timezone` | string | no | `UTC` | Timezone for the cron. |
| `patch_scope` | string | yes | – | `all`, `security`, or `custom`. |
| `custom_packages` | array of strings | no | – | Packages (when scope is `custom`). |
| `promote_from_previous` | boolean | no | `false` | Promote the previous stage's package set instead of re-scanning. |
| `auto_reboot` | boolean | no | `false` | Reboot after patching. |
| `week_of_month` | integer | no | – | Restrict to a given week (1–5). |
| `notifications` | object | no | – | Where to send notifications. |
| `ai_beautify` | boolean | no | `false` | Use AI to format the notification summary nicely. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/patches/schedules/ \
  -d '{"pipeline_id":"pl_1","stage_id":"st_1","cron_expr":"0 2 * * 0","patch_scope":"security","auto_reboot":true}'
```

**Example response (200):** the created schedule object.

---

### PATCH /api/v1/patches/schedules/{schedule_id}

**What this does:** Updates a schedule (any subset of its fields, including enabling/disabling it).

**Auth required?** **God Mode required.** **Path:** `schedule_id` (string, required).

**Request body** (JSON): any of `cron_expr`, `timezone`, `patch_scope`, `custom_packages`, `promote_from_previous`, `auto_reboot`, `week_of_month`, `notifications`, `ai_beautify`, `enabled` — all optional.

```bash
curl -X PATCH -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/patches/schedules/sch_1 \
  -d '{"enabled":false}'
```

**Example response (200):** the updated schedule object.

---

### DELETE /api/v1/patches/schedules/{schedule_id}

**What this does:** Deletes a schedule.

**Auth required?** **God Mode required.** **Path:** `schedule_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patches/schedules/sch_1
```

**Example response (200):** `{ "status": "deleted" }`

---

## Alerts

### GET /api/v1/patches/alerts/

**What this does:** Lists unacknowledged patch alert events (e.g. "a critical CVE now affects your fleet").

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/patches/alerts/
```

**Example response (200):** array of `{ "id":"al_1","cve":"CVE-2026-1234","severity":"critical","affected":12 }`.

---

### POST /api/v1/patches/alerts/{alert_id}/acknowledge

**What this does:** Marks a patch alert as acknowledged (clears it from the unacknowledged list).

**Auth required?** **God Mode required.** **Path:** `alert_id` (string, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patches/alerts/al_1/acknowledge
```

**Example response (200):** `{ "status": "acknowledged" }`

**Common errors (this group):** `403` God Mode not active; `404` pipeline/stage/promotion/schedule/alert not found; `422` invalid body.
