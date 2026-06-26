# Activation

These two endpoints handle **license activation** for DokOps.

> **Note:** These endpoints do not require a login token — they are reachable before the app is fully set up.

---

## GET /api/v1/activation/status

**What this does:** Tells you whether the product is activated and shows license details.

**Auth required?** No.

```bash
curl http://localhost:8000/api/v1/activation/status
```

**Example response (200):**

```json
{
  "activated": true,
  "plan": "enterprise",
  "expires_at": "2027-01-01T00:00:00Z"
}
```

| Field | Meaning |
|-------|---------|
| `activated` | Whether a valid license is installed. |
| `plan` | The license tier. |
| `expires_at` | When the license expires. |

(Exact fields depend on your license.)

---

## POST /api/v1/activation/activate

**What this does:** Activates DokOps with a license key.

**Auth required?** No.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `license_key` | string | yes | The license key you were given. |

```bash
curl -X POST -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/activation/activate \
  -d '{"license_key":"DOKOPS-XXXX-YYYY-ZZZZ"}'
```

**Example response (200):** `{ "activated": true, "plan": "enterprise" }`

**Common errors:** `400`/`422` for an invalid or expired key.
