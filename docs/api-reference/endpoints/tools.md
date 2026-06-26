# Tools

These endpoints manage the **toolsets** the AI can use and the **environment variables** those tools need (like API keys for external systems).

> **Shared notes:**
> - Listing/reading is allowed for any logged-in user; **creating or changing** toolsets and env-vars is **admin-only**.
> - *Toolset* (in plain terms) = a YAML file describing a set of commands the AI is allowed to run.
> - Toolset commands can reference env-vars using `$VAR_NAME` syntax.

---

## GET /api/v1/tools/builtin

**What this does:** Lists the built-in global tools that ship with DokOps.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/tools/builtin
```

**Example response (200):** array of tool descriptors `{ "name": "get_logs", "description": "..." }`.

---

## GET /api/v1/tools/builtin-toolsets

**What this does:** Lists the built-in (read-only) toolsets shipped with DokOps.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/tools/builtin-toolsets
```

**Example response (200):** array of toolset summaries.

---

## GET /api/v1/tools/toolsets

**What this does:** Lists all toolsets available to the AI (built-in + custom).

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/tools/toolsets
```

**Example response (200):** array of `{ "id": "k8s-basics", "name": "Kubernetes Basics", "tool_count": 6 }`.

---

## GET /api/v1/tools/toolsets/{toolset_id}

**What this does:** Returns the parsed definition of one toolset.

**Auth required?** Token. **Path:** `toolset_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/tools/toolsets/k8s-basics
```

**Example response (200):** the toolset object with its tools listed.

**Common errors:** `404` toolset not found.

---

## GET /api/v1/tools/toolsets/{toolset_id}/raw

**What this does:** Returns the raw YAML text of a toolset — handy for the editor.

**Auth required?** Token. **Path:** `toolset_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/tools/toolsets/k8s-basics/raw
```

**Example response (200):** `{ "raw": "name: k8s-basics\ntools:\n  - ..." }`

---

## POST /api/v1/tools/toolsets/{toolset_id}

**What this does:** Creates or updates a custom toolset (by saving its YAML).

**Auth required?** Admin / Superuser. **Path:** `toolset_id` (string, required).

**Request body** (JSON string): the raw YAML as a string.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/tools/toolsets/my-tools \
  -d '"name: my-tools\ntools: []"'
```

**Example response (200):** `{ "status": "saved", "id": "my-tools" }`

**Common errors:** `403` not admin; `422` invalid YAML.

---

## GET /api/v1/tools/env-vars

**What this does:** Lists all toolset environment variables. **Values are masked** for safety.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/tools/env-vars
```

**Example response (200):** `[{ "key": "GITHUB_TOKEN", "value": "****" }]`

---

## POST /api/v1/tools/env-vars

**What this does:** Sets or updates one environment variable used by toolsets.

**Auth required?** Admin / Superuser.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `key` | string | yes | Variable name (e.g. `GITHUB_TOKEN`). |
| `value` | string | yes | Variable value. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/tools/env-vars \
  -d '{"key":"GITHUB_TOKEN","value":"ghp_abc123"}'
```

**Example response (200):** `{ "status": "saved", "key": "GITHUB_TOKEN" }`

---

## POST /api/v1/tools/env-vars/bulk

**What this does:** Imports many environment variables at once from a JSON object.

**Auth required?** Admin / Superuser.

**Request body** (JSON): a flat object `{ "KEY1": "value1", "KEY2": "value2" }`.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/tools/env-vars/bulk \
  -d '{"GITHUB_TOKEN":"ghp_abc","SLACK_TOKEN":"xoxb-..."}'
```

**Example response (200):** `{ "imported": 2 }`

---

## DELETE /api/v1/tools/env-vars/{key}

**What this does:** Deletes one environment variable.

**Auth required?** Admin / Superuser. **Path:** `key` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/tools/env-vars/GITHUB_TOKEN
```

**Example response (200):** `{ "status": "deleted", "key": "GITHUB_TOKEN" }`
