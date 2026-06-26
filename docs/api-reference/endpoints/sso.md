# SSO (Single Sign-On)

These endpoints power **single sign-on** — logging in via an external identity provider (Google, Azure AD, Okta, etc.) instead of a username/password. They are normally used by your **browser**, not called by hand.

> **Note:** All three endpoints are public (no token required) — they are part of the login flow that *gives* you a token.

---

## GET /api/v1/auth/sso/providers

**What this does:** Lists the SSO providers configured for this install — used to draw the "Sign in with…" buttons on the login page.

**Auth required?** No.

```bash
curl http://localhost:8000/api/v1/auth/sso/providers
```

**Example response (200):**

```json
[
  { "id": "google", "name": "Google", "login_url": "/api/v1/auth/sso/google/login" },
  { "id": "azure", "name": "Azure AD", "login_url": "/api/v1/auth/sso/azure/login" }
]
```

---

## GET /api/v1/auth/sso/{provider}/login

**What this does:** Starts the SSO login by redirecting your browser to the provider's sign-in page. You open this in a browser; you don't call it from a script.

**Auth required?** No.

**Path parameters:** `provider` (string, required) — e.g. `google`, `azure`, `okta`.

**Open in a browser:**

```
http://localhost:8000/api/v1/auth/sso/google/login
```

**Response:** an HTTP redirect (302) to the provider's authorization page.

**Common errors:** `404`/`422` if the provider isn't configured.

---

## GET /api/v1/auth/sso/{provider}/callback

**What this does:** The provider sends the user back here after they sign in. DokOps validates the response, figures out the user's role, mints a DokOps token, and redirects the browser into the app. You never call this directly — the provider does.

**Auth required?** No (it's the return leg of the login flow).

**Path parameters:** `provider` (string, required).

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `code` | string | yes | Authorization code from the provider. |
| `state` | string | yes | Anti-forgery value that must match the one DokOps issued. |

**Response:** an HTTP redirect into the DokOps frontend, now logged in.

**Common errors:** `400`/`422` if `code`/`state` are missing or invalid (e.g. an expired or tampered login attempt).
