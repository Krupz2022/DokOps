# Analytics

A single endpoint reporting **AI token usage** over a time window — how much the AI has "spent" answering questions. (in plain terms: tokens are the units AI providers bill by.)

---

## GET /api/v1/analytics/tokens

**What this does:** Returns how many AI tokens were used between two dates, useful for tracking cost.

**Auth required?** Admin / Superuser.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `start` | string (ISO date-time) | yes | Start of the window (inclusive). |
| `end` | string (ISO date-time) | yes | End of the window (exclusive). |

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/analytics/tokens?start=2026-06-01T00:00:00Z&end=2026-07-01T00:00:00Z"
```

**Example response (200):**

```json
{
  "total_tokens": 1450000,
  "prompt_tokens": 900000,
  "completion_tokens": 550000,
  "by_day": [
    { "date": "2026-06-01", "tokens": 52000 }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `total_tokens` | All tokens used in the window. |
| `prompt_tokens` | Tokens spent on inputs (your questions + context). |
| `completion_tokens` | Tokens spent on the AI's answers. |
| `by_day` | A daily breakdown. |

(Exact fields may vary.)

**Common errors:** `403` not an admin; `422` if `start`/`end` are missing or not valid dates.
