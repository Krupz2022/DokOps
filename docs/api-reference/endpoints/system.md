# System

System-level controls: checking status, the very first setup, the **God Mode** switch, signup settings, and the OpenAI-compatible API key.

---

## GET /api/v1/system/status

**What this does:** Reports overall system status (whether setup is done, current mode, etc.). Useful as a "is everything OK?" check.

**Auth required?** Optional — works with or without a token (more detail shown when logged in).

**curl example:**

```bash
curl http://localhost:8000/api/v1/system/status
```

**Example response (200):** a status object (fields vary by install state), e.g. `{"setup_complete": true, "mode": "normal", ...}`.

---

## POST /api/v1/system/setup

**What this does:** One-time first-run setup — creates the very first administrator account. Only works before any setup has been completed.

**Auth required?** No (it's for the first boot, before any users exist).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `username` | string | yes | Username for the first admin. |
| `password` | string | yes | Password for the first admin. |

**curl example:**

```bash
curl -X POST -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/system/setup \
  -d '{"username": "admin", "password": "SuperSecret123"}'
```

**Example response (200):** confirmation, typically including a token so you're logged straight in.

**Common errors:** `400`/`403` if setup has already been completed.

---

## POST /api/v1/system/mode

**What this does:** Turns **God Mode** on or off for your own session. God Mode is required before doing dangerous things like deleting cluster resources. (in plain terms: the master safety switch.)

**Auth required?** Admin / Superuser.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `mode` | string | yes | `"god"` to enable, `"normal"` to disable. |

**curl example:**

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/system/mode \
  -d '{"mode": "god"}'
```

**Example response (200):** `{"mode": "god", "god_mode_active": true}` (shape may vary).

**Common errors:** `400` insufficient privileges (non-admins cannot use God Mode).

---

## PUT /api/v1/system/settings

**What this does:** Controls whether the public signup form is enabled and what role new signups get.

**Auth required?** Admin / Superuser.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `signup_enabled` | boolean | yes | Allow public self-registration. |
| `signup_default_role` | string | yes | Role assigned to self-registered users (e.g. `user`). |

**curl example:**

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/system/settings \
  -d '{"signup_enabled": true, "signup_default_role": "user"}'
```

---

## GET /api/v1/system/openai-compat

**What this does:** Shows the current configuration of the OpenAI-compatible API (whether it's on, and a masked key).

**Auth required?** Token (any logged-in user).

**curl example:**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/system/openai-compat
```

**Example response (200):** `{"enabled": true, "api_key_masked": "dokops_****"}` (shape may vary).

---

## PATCH /api/v1/system/openai-compat

**What this does:** Enables or disables the OpenAI-compatible API.

**Auth required?** Token (any logged-in user).

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `enabled` | boolean | no | – | `true` to turn the OpenAI-compatible endpoint on, `false` to turn it off. |

**curl example:**

```bash
curl -X PATCH -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/system/openai-compat \
  -d '{"enabled": true}'
```

---

## POST /api/v1/system/openai-compat/regenerate-key

**What this does:** Generates a brand-new OpenAI-compatible API key (the `dokops_...` key). The old key stops working immediately. The new key is shown **only once**.

**Auth required?** Token (any logged-in user).

**curl example:**

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/system/openai-compat/regenerate-key
```

**Example response (200):** `{"api_key": "dokops_abc123...new..."}` — copy it now; it won't be shown again. See [openai-compatible.md](./openai-compatible.md) for how to use it.
