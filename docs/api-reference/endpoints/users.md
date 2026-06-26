# Users

These endpoints manage **user accounts** — who can log in, their roles, and so on. Most of them are **admin-only**.

> **Shared notes for this group:**
> - Every endpoint here accepts the token via the `Authorization: Bearer <token>` header (or the `access_token` cookie).
> - The user object returned always includes `hashed_password` as a field, but it is the *hashed* (scrambled) value — never the real password.

---

## GET /api/v1/users/me

**What this does:** Tells you who you currently are — your username, role, and whether God Mode is on.

**Auth required?** Token (any logged-in user).

**curl example:**

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/users/me
```

**Example response (200):**

```json
{
  "id": 1,
  "username": "admin",
  "is_active": true,
  "is_superuser": true,
  "role": "admin",
  "email": null,
  "provider": null,
  "external_id": null,
  "god_mode_active": false
}
```

| Field | Meaning |
|-------|---------|
| `id` | Internal numeric user ID. |
| `username` | Login name. |
| `is_active` | `false` means the account is disabled. |
| `is_superuser` | `true` for administrators. |
| `role` | Role string, e.g. `admin` or `user`. |
| `email` / `provider` / `external_id` | Filled in when the user logged in via SSO. |
| `god_mode_active` | Whether God Mode is currently switched on for this session. |

**Common errors:** `401` if your token is missing or invalid.

---

## GET /api/v1/users/

**What this does:** Lists all user accounts. Admin-only.

**Auth required?** Admin / Superuser.

**Query parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `skip` | integer | no | `0` | How many users to skip (for paging). |
| `limit` | integer | no | `100` | Maximum number to return. |

**curl example:**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/users/?skip=0&limit=50"
```

**Example response (200):** an array of user objects (same shape as `/users/me`).

**Common errors:** `400` "The user doesn't have enough privileges" if you are not an admin.

---

## POST /api/v1/users/

**What this does:** Creates a new user account directly (no signup form). Admin-only.

**Auth required?** Admin / Superuser.

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `username` | string | yes | – | New account's username. |
| `hashed_password` | string | yes | – | The password. (Despite the field name, send the plain password you want; the server hashes/stores it.) |
| `is_superuser` | boolean | no | `false` | Make this user an admin. |
| `role` | string | no | `"user"` | Role to assign. |
| `is_active` | boolean | no | `true` | Whether the account is enabled. |

**curl example:**

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/users/ \
  -d '{"username": "bob", "hashed_password": "TempPass123", "role": "user"}'
```

**Example response (200):** the created user object.

**Common errors:** `400` insufficient privileges; `422` missing required fields.

---

## PUT /api/v1/users/{user_id}

**What this does:** Updates an existing user (e.g. activate/deactivate, change details). Admin-only.

**Auth required?** Admin / Superuser.

**Path parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | integer | yes | ID of the user to update. |

**Request body** (JSON, full user object): `username` (required), plus optional `id`, `is_active`, `is_superuser`, `role`, `email`, `god_mode_active`, etc.

**curl example:**

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/users/2 \
  -d '{"username": "bob", "is_active": false, "role": "user"}'
```

**Example response (200):** the updated user object.

**Common errors:** `400` insufficient privileges; `404` user not found; `422` invalid body.

---

## PATCH /api/v1/users/{user_id}/role

**What this does:** Changes just one user's role. Admin-only.

**Auth required?** Admin / Superuser.

**Path parameters:** `user_id` (integer, required).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `role` | string | yes | New role to assign (e.g. `admin`, `user`). |

**curl example:**

```bash
curl -X PATCH -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/users/2/role \
  -d '{"role": "admin"}'
```

**Example response (200):** the updated user object.

---

## DELETE /api/v1/users/{user_id}

**What this does:** Permanently removes a user account. Admin-only.

**Auth required?** Admin / Superuser.

**Path parameters:** `user_id` (integer, required).

**curl example:**

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/users/2
```

**Example response (200):** the deleted user object.

**Common errors:** `400` insufficient privileges; `404` user not found.
