# Registries

These endpoints connect **Docker image registries** (where container images are stored — e.g. Docker Hub, GitHub Container Registry, a private registry) so DokOps can browse them and check whether images exist.

> **Shared note:** All endpoints require a token (any logged-in user).

---

## GET /api/v1/registries/

**What this does:** Lists connected registries.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/registries/
```

**Example response (200):**

```json
[
  {
    "id": "reg_1",
    "name": "Docker Hub",
    "url": "https://registry-1.docker.io",
    "username": "acme",
    "added_by": "admin",
    "created_at": "2026-06-01T09:00:00Z"
  }
]
```

(The password is never returned.)

---

## POST /api/v1/registries/

**What this does:** Connects a new registry.

**Auth required?** Token.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | yes | Friendly name. |
| `url` | string | yes | Registry URL. |
| `username` | string | no | Login username (for private registries). |
| `password` | string | no | Login password/token. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/registries/ \
  -d '{"name":"Docker Hub","url":"https://registry-1.docker.io","username":"acme","password":"..."}'
```

**Example response (200):** the created registry object (without the password).

---

## DELETE /api/v1/registries/{registry_id}

**What this does:** Removes a registry connection.

**Auth required?** Token. **Path:** `registry_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/registries/reg_1
```

**Example response (200):** `{ "status": "deleted" }`

---

## POST /api/v1/registries/{registry_id}/test

**What this does:** Tests that DokOps can log in to and reach the registry.

**Auth required?** Token. **Path:** `registry_id` (string, required). No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/registries/reg_1/test
```

**Example response (200):** `{ "success": true }`

---

## GET /api/v1/registries/{registry_id}/catalog

**What this does:** Lists all repositories (image names) available in a connected registry.

**Auth required?** Token. **Path:** `registry_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/registries/reg_1/catalog
```

**Example response (200):** `{ "repositories": ["acme/web", "acme/api"] }`

---

## POST /api/v1/registries/{registry_id}/check-image

**What this does:** Checks whether a specific image (and tag) exists in the registry.

**Auth required?** Token. **Path:** `registry_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `image` | string | yes | The image reference, e.g. `acme/web:1.2.3`. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/registries/reg_1/check-image \
  -d '{"image":"acme/web:1.2.3"}'
```

**Example response (200):** `{ "exists": true, "image": "acme/web:1.2.3" }`

---

## GET /api/v1/registries/settings

**What this does:** Returns whether the registry feature is enabled.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/registries/settings
```

**Example response (200):** `{ "enabled": true }`

---

## POST /api/v1/registries/settings

**What this does:** Enables or disables the registry feature.

**Auth required?** Token.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `enabled` | boolean | yes | `true` to enable the feature, `false` to disable. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/registries/settings \
  -d '{"enabled":true}'
```

**Example response (200):** `{ "enabled": true }`
