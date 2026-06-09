# AI Token Analytics

The Analytics page gives administrators a real-time view of AI provider token consumption across every surface in DokOps — so you can understand cost, spot abuse, and optimise prompts.

---

## What Is Tracked

Every AI call writes a row to the `ai_token_usage` table before the response is returned to the caller:

| Field | Description |
|-------|-------------|
| `source` | Where the call came from: `chat`, `agent`, `workflow`, `alert`, `rag`, `notification` |
| `model` | Exact model name used (e.g. `gpt-4o`, `gemini-2.0-flash`) |
| `input_tokens` | Prompt token count from the provider response |
| `output_tokens` | Completion token count from the provider response |
| `user_id` | The DokOps user who triggered the call (null for system-initiated calls like alert pipeline) |
| `created_at` | UTC timestamp |

Token counts come directly from the provider's `.usage` object — they are not estimated.

---

## Navigating to Analytics

Click **Analytics** in the sidebar. Requires `admin` role.

---

## Date Range

Use the **7d / 30d / 90d** toggle at the top right to change the lookback window.

---

## Charts

### Total Tokens by Source (Bar Chart)

Shows cumulative input + output tokens broken down by source for the selected period. Useful for identifying which feature is consuming the most tokens.

### Daily Token Trend (Line Chart)

Token consumption per day across all sources. Helps spot usage spikes (e.g. a noisy alert pipeline flooding the AI) or long-term growth trends.

---

## Summary Cards

| Card | Value |
|------|-------|
| **Total Input Tokens** | All input tokens in the period |
| **Total Output Tokens** | All output tokens in the period |
| **Total Calls** | Number of individual AI completions |
| **Avg Tokens / Call** | (input + output) / calls |

---

## Top Users Table

Lists the top 10 users by total token consumption in the period. System-initiated calls (alert pipeline, scheduled agents) appear as `system`.

| Column | Description |
|--------|-------------|
| **User** | Username |
| **Total Tokens** | Input + output |
| **Calls** | Number of completions |
| **Avg / Call** | Average tokens per call |

---

## Via API

```bash
# Get token analytics summary + chart data
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/analytics/tokens?range=30d"
```

Response shape:

```json
{
  "summary": {
    "total_input": 482000,
    "total_output": 94000,
    "total_calls": 312,
    "avg_per_call": 1846
  },
  "by_source": [
    {"source": "chat", "input": 210000, "output": 51000, "calls": 180},
    {"source": "agent", "input": 160000, "output": 30000, "calls": 95}
  ],
  "daily": [
    {"date": "2026-05-11", "input": 18000, "output": 3200},
    ...
  ],
  "top_users": [
    {"username": "alice", "total": 84000, "calls": 65}
  ]
}
```

---

## Reducing Token Usage

If costs are higher than expected, consider:

- **Enable model tiering** — set a fast/cheap model (`gpt-4o-mini`, `gemini-2.0-flash`) in **Settings → AI → Fast Model**. DokOps automatically routes simple intent-detection calls to the cheaper model.
- **Check the alert pipeline** — a noisy alert source can flood the AI. Review alert deduplication settings and suppression windows in **Alert Incidents → Settings**.
- **RAG chunk size** — fewer, larger chunks mean fewer embedding calls. Adjust `DOKOPS_RAG_CHUNK_SIZE` if your ingest rate is high.
