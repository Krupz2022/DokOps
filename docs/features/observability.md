# Observability Integrations

DokOps connects to your existing observability stack so the AI can query metrics and logs during incident diagnosis — without you having to copy-paste data.

---

## Supported Providers

| Provider | What DokOps Can Query |
|----------|----------------------|
| **Prometheus** | PromQL metrics (CPU, memory, request rates, error rates) |
| **Grafana** | Dashboard panel data, alert states |
| **Elasticsearch** | Full-text log search (KQL / Lucene queries) |
| **Loki** | Structured log queries (LogQL) |
| **Datadog** | Metrics, logs, APM traces |

---

## Connecting a Provider

1. Click **Integrations** → **Observability** in the sidebar.
2. Click **Add Integration**.
3. Select the provider type.
4. Fill in the connection form:

### Prometheus

```
Base URL:  http://prometheus.monitoring.svc.cluster.local:9090
Auth Type: None / Basic / Bearer Token
```

### Grafana

```
Base URL:  http://grafana.monitoring.svc.cluster.local:3000
Auth Type: API Key
API Key:   glsa_...
```

### Elasticsearch

```
Base URL:  https://elasticsearch.logging.svc.cluster.local:9200
Auth Type: Basic
Username:  elastic
Password:  (stored encrypted)
Index:     logs-*
```

### Loki

```
Base URL:  http://loki.logging.svc.cluster.local:3100
Auth Type: None / Basic / Bearer Token
```

### Datadog

```
Base URL:  https://api.datadoghq.com (or .eu for EU region)
Auth Type: API Key + App Key
```

5. Click **Test Connection** — DokOps sends a lightweight health-check query.
6. Click **Save** if the test passes.

---

## Using Observability in AI Chat

Once connected, the AI will automatically query your observability providers during diagnosis:

```
User: "The payments service is slow. What's the latency?"

AI: [Step] Querying Prometheus for request latency of 'payments-svc'...
    Query: histogram_quantile(0.99, rate(http_request_duration_seconds_bucket
           {service="payments"}[5m]))

    p99 latency: 2340ms (normal: ~120ms) ⚠️

    [Step] Querying Loki for recent error logs from 'payments-api'...
    Query: {namespace="production", app="payments-api"} |= "error"

    Found 847 error log lines in last 10 minutes.
    Most common: "Error: slow query in payments-db (avg 2100ms)"

    Root Cause: The payments-db database is responding slowly.
    Recent error pattern matches a full table scan on the orders table.
```

---

## Observability Page

The **Observability** page (under Integrations) gives a unified view of data from all connected providers.

### Viewing Metrics

Select a connected Prometheus or Datadog instance and enter a query:

```promql
# CPU usage by namespace
sum(rate(container_cpu_usage_seconds_total[5m])) by (namespace)

# Memory usage for a deployment
sum(container_memory_working_set_bytes{pod=~"payments-api-.*"}) by (pod)
```

### Viewing Logs

Select Elasticsearch or Loki and search:

```
# Elasticsearch KQL
error AND kubernetes.namespace: production AND @timestamp: [now-1h TO now]

# Loki LogQL
{namespace="production", app="payments-api"} |= "ERROR" | json
```

---

## Managing Integrations

### Test a Connection

From the Integrations list, click the **Test** button on any integration card to verify it's still reachable.

### Edit an Integration

Click the **Edit** (pencil) icon to update the URL, credentials, or auth type.

### Delete an Integration

Click the **Delete** (trash) icon. This removes the integration from DokOps but does not affect the provider itself.

---

## Multiple Instances

You can connect multiple instances of the same provider type. For example:

- `prometheus-prod` (production cluster)
- `prometheus-staging` (staging cluster)

The AI uses whichever instance matches the currently selected cluster context, or asks you if there's ambiguity.

---

## Via API

```bash
# List all observability integrations
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/integrations/obs

# Connect a new Prometheus instance
curl -X POST http://localhost:8000/api/v1/integrations/obs/connect \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "prometheus",
    "display_name": "Prod Prometheus",
    "base_url": "http://prometheus.monitoring:9090",
    "auth_type": "none"
  }'

# Test an existing integration
curl -X POST http://localhost:8000/api/v1/integrations/obs/{id}/test \
  -H "Authorization: Bearer $TOKEN"
```

---

## Autonomous Alert Response

DokOps can receive alerts from external monitoring systems and autonomously respond: collect evidence, run AI root-cause analysis, create a Jira ticket, and optionally restart the affected pod — all before an engineer opens their laptop.

### How It Works

```
Alert fires (e.g. Alertmanager)
  └─► POST /api/v1/alerts/webhook/alertmanager
        │
        ├─ Parse → NormalizedAlert
        ├─ Deduplicate (same alert within suppression window → drop)
        │
        └─ Background pipeline:
            1. Collect evidence (pod logs, events, metrics)
            2. Run AI RCA → store structured report
            3. Create Jira incident ticket (if connector configured)
            4. Notify Slack / Teams
            5. Auto-remediate if alert type is in allowlist (restart pod only)
```

Evidence is **always collected and saved before any remediation action**. Auto-remediation never happens unless the alert name is explicitly listed in the remediation policy.

### Supported Alert Sources

| Source | Endpoint |
|--------|----------|
| Alertmanager | `POST /api/v1/alerts/webhook/alertmanager` |
| Grafana | `POST /api/v1/alerts/webhook/grafana` |
| Datadog | `POST /api/v1/alerts/webhook/datadog` |
| PagerDuty | `POST /api/v1/alerts/webhook/pagerduty` |
| OpsGenie | `POST /api/v1/alerts/webhook/opsgenie` |
| Elasticsearch | `POST /api/v1/alerts/webhook/elasticsearch` |
| Generic | `POST /api/v1/alerts/webhook/generic` |

### Configuring Alertmanager

```yaml
# alertmanager.yml
receivers:
  - name: dokops
    webhook_configs:
      - url: http://dokops.internal:8000/api/v1/alerts/webhook/alertmanager
        http_config:
          authorization:
            credentials: YOUR_WEBHOOK_SECRET
        send_resolved: false
```

### Webhook Security

Each source has its own secret, configured in **Settings → Alert Webhooks**. Set a shared secret per source and DokOps will validate the HMAC signature (or bearer token, depending on the source format) before processing the payload.

Requests with missing or invalid signatures are rejected with HTTP 401.

### Configuring Notifications

In **Settings → Alert Notifications**:

- **Slack Webhook URL** — DokOps posts an alert summary and RCA to this channel
- **Teams Webhook URL** — same for Microsoft Teams

### Alert Incidents Page

Go to **Alert Incidents** in the sidebar to see all received alerts and their status:

| Status | Meaning |
|--------|---------|
| `pending` | Received, pipeline not yet started |
| `collecting` | Gathering evidence (logs, events, metrics) |
| `rca_running` | AI is analyzing evidence |
| `notified` | Slack/Teams/Jira notification sent |
| `remediated` | Auto-remediation applied |
| `closed` | Manually closed |

Click any incident to expand:
- **RCA Summary** — AI-generated root cause analysis
- **Evidence** — last log lines and recent events captured
- **Jira Ticket** — link to the created ticket (if configured)
- **Remediation** — what action was taken and its outcome

### Alert Suppression Window

DokOps deduplicates alerts with the same fingerprint within a configurable window (default: 5 minutes). Configure in **Settings → Alert Suppression**:

```
Suppression window: [5] minutes
```

Duplicate alerts within the window are dropped silently — useful when noisy alerting systems fire the same alert repeatedly.

### Remediation Policy

Auto-remediation is **opt-in** and controlled by an explicit allowlist. Configure in **Settings → Alert Remediation Policy**:

```json
{
  "allowed_alerts": ["CrashLoopBackOff", "OOMKilled"],
  "action": "restart_pod"
}
```

Only alert names in `allowed_alerts` will trigger the `restart_pod` action. The AI never decides to remediate on its own — the decision must be pre-configured.

### API

```bash
# List all alert incidents
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/alerts/incidents

# Get a specific incident
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/alerts/incidents/{id}

# Close an incident
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/alerts/incidents/{id}/close
```
