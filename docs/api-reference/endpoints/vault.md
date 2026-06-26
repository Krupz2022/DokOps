# Vault

A single read-only endpoint that reports how well your stored credentials ("the vault") cover your fleet of minions and services.

---

## GET /api/v1/vault/coverage

**What this does:** Returns a coverage report — which minions/services have the credentials they need stored, and which are missing them. (in plain terms: a checklist of "do we have the passwords we need?")

**Auth required?** Token (any logged-in user).

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/vault/coverage
```

**Example response (200):**

```json
{
  "total_services": 40,
  "covered": 33,
  "missing": 7,
  "gaps": [
    { "minion_id": "m_12", "service_type": "postgres", "reason": "no credential at any scope" }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `total_services` | How many service slots exist across the fleet. |
| `covered` | How many have a usable credential. |
| `missing` | How many are missing one. |
| `gaps` | The specific items lacking credentials. |

(Exact fields depend on your fleet.) See [service-credentials.md](./service-credentials.md) to fill the gaps.

**Common errors:** `401` not authenticated.
