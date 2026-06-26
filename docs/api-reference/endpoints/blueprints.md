# Blueprints

A **blueprint** is a reusable bundle of "install/configure this" instructions (written as YAML) that you can apply to minions. It can carry attached files ("sources") and be assigned to orgs/groups/individual minions.

> **Shared notes:**
> - Reading is allowed for any logged-in user.
> - **Creating, editing, deleting, uploading sources, and assigning** are **admin-only**.

---

## GET /api/v1/blueprints/

**What this does:** Lists all blueprints.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/blueprints/
```

**Example response (200):** array of `{ "id":"bp_1","name":"Base hardening","updated_at":"..." }`.

---

## POST /api/v1/blueprints/

**What this does:** Creates a new blueprint.

**Auth required?** Admin / Superuser.

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | yes | – | Blueprint name. |
| `yaml_body` | string | no | `resources: []` | The blueprint definition as YAML. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/blueprints/ \
  -d '{"name":"Base hardening","yaml_body":"resources:\n  - type: package\n    name: ufw"}'
```

**Example response (200):** the created blueprint object.

**Common errors:** `403` not admin; `422` invalid YAML.

---

## GET /api/v1/blueprints/{blueprint_id}

**What this does:** Returns one blueprint's full definition.

**Auth required?** Token. **Path:** `blueprint_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/blueprints/bp_1
```

**Example response (200):** the blueprint object including `yaml_body`.

**Common errors:** `404` not found.

---

## PUT /api/v1/blueprints/{blueprint_id}

**What this does:** Updates a blueprint's name and/or YAML.

**Auth required?** Admin / Superuser. **Path:** `blueprint_id` (string, required).

**Request body** (JSON): `name` (required), `yaml_body` (optional, default `resources: []`).

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/blueprints/bp_1 \
  -d '{"name":"Base hardening v2","yaml_body":"resources: []"}'
```

**Example response (200):** the updated blueprint object.

---

## DELETE /api/v1/blueprints/{blueprint_id}

**What this does:** Deletes a blueprint.

**Auth required?** Admin / Superuser. **Path:** `blueprint_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/blueprints/bp_1
```

**Example response (200):** `{ "status": "deleted" }`

---

## POST /api/v1/blueprints/reseed

**What this does:** Re-imports blueprints from the on-disk seed folder (`backend/app/blueprints/`). Useful after a deploy adds new YAML files. Safe to call anytime (idempotent).

**Auth required?** Admin / Superuser. No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/blueprints/reseed
```

**Example response (200):** `{ "status": "reseeded", "count": 5 }`

---

## GET /api/v1/blueprints/{blueprint_id}/sources

**What this does:** Lists the attached "source" files of a blueprint (scripts/configs it ships).

**Auth required?** Token. **Path:** `blueprint_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/blueprints/bp_1/sources
```

**Example response (200):** array of `{ "name":"setup.sh","size":1024,"encoding":"utf-8" }`.

---

## PUT /api/v1/blueprints/{blueprint_id}/sources/{name}

**What this does:** Creates or replaces a text source file on a blueprint (provide the content inline).

**Auth required?** Admin / Superuser. **Path:** `blueprint_id`, `name` (string, required).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `content` | string | yes | The file's text content. |

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/blueprints/bp_1/sources/setup.sh \
  -d '{"content":"#!/bin/bash\necho hello"}'
```

**Example response (200):** `{ "status": "saved", "name": "setup.sh" }`

---

## POST /api/v1/blueprints/{blueprint_id}/sources/{name}/upload

**What this does:** Uploads a binary/large file as a blueprint source (e.g. an installer).

**Auth required?** Admin / Superuser. **Path:** `blueprint_id`, `name` (string, required).

**Request body** (`multipart/form-data`):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `file` | file | yes | The file to attach. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -F "file=@/home/me/installer.bin" \
  http://localhost:8000/api/v1/blueprints/bp_1/sources/installer.bin/upload
```

**Example response (200):** `{ "status": "uploaded", "name": "installer.bin", "size": 204800 }`

---

## GET /api/v1/blueprints/{blueprint_id}/assignments

**What this does:** Lists where a blueprint is assigned (which orgs/groups/minions it applies to).

**Auth required?** Token. **Path:** `blueprint_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/blueprints/bp_1/assignments
```

**Example response (200):** array of `{ "id":"as_1","scope_type":"group","scope_id":"grp_3" }`.

---

## POST /api/v1/blueprints/{blueprint_id}/assignments

**What this does:** Assigns a blueprint to a scope (an org, a group, or a single minion).

**Auth required?** Admin / Superuser. **Path:** `blueprint_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `scope_type` | string | yes | `org`, `group`, or `minion`. |
| `scope_id` | string | yes | The ID of that org/group/minion. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/blueprints/bp_1/assignments \
  -d '{"scope_type":"group","scope_id":"grp_3"}'
```

**Example response (200):** the created assignment object.

---

## DELETE /api/v1/blueprints/assignments/{assignment_id}

**What this does:** Removes a blueprint assignment.

**Auth required?** Admin / Superuser. **Path:** `assignment_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/blueprints/assignments/as_1
```

**Example response (200):** `{ "status": "deleted" }`

> **Related:** To run a blueprint on a minion and watch it live, see the blueprint endpoints in [minions.md](./minions.md) (`/minions/{id}/blueprint/run` and the run stream).
