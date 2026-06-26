# CLI Tools

These endpoints detect and **install command-line tools** on the DokOps server (e.g. `kubectl`, `helm`, `aws`), and let you define your own custom installers. Installing anything is a system change, so it needs **God Mode**.

> **Shared note:** Listing/detecting needs admin rights; running installs needs **God Mode**.

---

## GET /api/v1/system/cli-tools/

**What this does:** Detects the pre-defined tools and reports which are installed and which are missing.

**Auth required?** Admin / Superuser.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/system/cli-tools/
```

**Example response (200):**

```json
[
  { "name": "kubectl", "installed": true, "version": "v1.30.1" },
  { "name": "helm", "installed": false, "version": null }
]
```

---

## POST /api/v1/system/cli-tools/{tool_name}/install

**What this does:** Installs one of the pre-defined tools on the server.

**Auth required?** **God Mode required.**

**Path parameters:** `tool_name` (string, required) — e.g. `helm`.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/system/cli-tools/helm/install
```

**Example response (200):** `{ "status": "installed", "tool": "helm", "version": "v3.15.0" }`

**Common errors:** `403` God Mode not active; `404` unknown tool; `500` if the install command fails.

---

## GET /api/v1/system/cli-tools/custom

**What this does:** Lists your saved custom tool installer definitions.

**Auth required?** Admin / Superuser.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/system/cli-tools/custom
```

**Example response (200):** array of `{ "name": "mytool", "platform": "linux", "command": "apt-get install -y mytool" }`.

---

## POST /api/v1/system/cli-tools/custom

**What this does:** Saves a custom tool installer (a name + the command that installs it).

**Auth required?** Admin / Superuser.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | yes | Name for the tool. |
| `platform` | string | yes | Target platform (e.g. `linux`, `darwin`, `windows`). |
| `command` | string | yes | The shell command that installs it. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/system/cli-tools/custom \
  -d '{"name":"mytool","platform":"linux","command":"apt-get install -y mytool"}'
```

**Example response (200):** `{ "status": "saved", "name": "mytool" }`

---

## DELETE /api/v1/system/cli-tools/custom/{tool_name}

**What this does:** Deletes a custom tool definition.

**Auth required?** Admin / Superuser. **Path:** `tool_name` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/system/cli-tools/custom/mytool
```

**Example response (200):** `{ "status": "deleted" }`

---

## POST /api/v1/system/cli-tools/custom/{tool_name}/install

**What this does:** Runs a custom tool's install command on the server.

**Auth required?** **God Mode required.** **Path:** `tool_name` (string, required).

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/system/cli-tools/custom/mytool/install
```

**Example response (200):** `{ "status": "installed", "tool": "mytool" }`

**Common errors:** `403` God Mode not active; `404` unknown custom tool; `500` if the command fails.
