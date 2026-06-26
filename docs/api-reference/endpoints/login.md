# Login & Registration

These endpoints are how you **get a token** (log in), create a new account, and log out. The token from here is what unlocks every other endpoint.

Base URL: `http://localhost:8000` · All paths below are exact.

---

## POST /api/v1/login/access-token

**What this does:** Logs you in with a username and password and hands back a token you use for every other call. (in plain terms: this is the "sign in" button.)

**Auth required?** No — this is how you get authenticated in the first place.

**Request body** (form-encoded, `application/x-www-form-urlencoded` — *not* JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `username` | string | yes | – | Your account username. |
| `password` | string | yes | – | Your account password. |
| `grant_type` | string | no | – | OAuth2 field; leave blank. |
| `scope` | string | no | `""` | OAuth2 field; leave blank. |
| `client_id` | string | no | – | OAuth2 field; leave blank. |
| `client_secret` | string | no | – | OAuth2 field; leave blank. |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/login/access-token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=SuperSecret123"
```

**Example response (200):**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "username": "admin",
  "is_superuser": true,
  "role": "admin"
}
```

| Field | Meaning |
|-------|---------|
| `access_token` | The token. Send it as `Authorization: Bearer <token>` on other calls. |
| `token_type` | Always `bearer`. |
| `username` | Who you logged in as. |
| `is_superuser` | `true` if this account is an administrator. |
| `role` | The account's role (e.g. `admin`, `user`). |

The same token is also set as an `httpOnly` cookie called `access_token`, so browsers stay logged in automatically.

**Common errors:**

| Code | Meaning |
|------|---------|
| `400` | "Incorrect email or password" — wrong username/password, or "Inactive user" if the account is disabled. |
| `422` | You forgot `username` or `password`. |

---

## POST /api/v1/register

**What this does:** Creates a brand-new user account (only works if the administrator has turned public signups on, and SSO is off).

**Auth required?** No.

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `username` | string | yes | – | Desired username. |
| `password` | string | yes | – | Desired password. |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "ChangeMe123"}'
```

**Example response (200):** Same shape as login — you are returned a ready-to-use token:

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "username": "alice",
  "is_superuser": false,
  "role": "user"
}
```

**Common errors:**

| Code | Meaning |
|------|---------|
| `403` | "Public signups are disabled" or "Registration is disabled when SSO is enabled". |
| `400` | "Username already taken". |
| `422` | Missing `username` or `password`. |

---

## POST /api/v1/logout

**What this does:** Logs you out by clearing the login cookie. (Header-based tokens simply expire on their own.)

**Auth required?** No (it just clears the cookie if present).

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/logout
```

**Example response (200):**

```json
{ "message": "Logged out" }
```
