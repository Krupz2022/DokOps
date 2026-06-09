# Workflow Builder & Agents

DokOps has two complementary automation systems:

- **Scripted Workflows** — deterministic, step-by-step pipelines you define explicitly. Each step is a fixed action (K8s command, HTTP call, Slack message, etc.).
- **Agents** — goal-driven, AI-powered workers that choose their own sequence of tools at run time. You define the goal and which tools are pre-approved; the AI figures out how to achieve it.

Both can be triggered manually, on a cron schedule, or via webhook. Both stream real-time progress back to the UI.

---

## Agents

### What is an Agent?

An Agent is a `workflow_type: agent` workflow. Instead of a fixed sequence of steps, you give it:

1. **A goal** — a plain English description ("investigate why the payments pod is crashing and notify Slack")
2. **A pre-approved tool set** — which tools from the catalog the agent is allowed to call
3. **Target context** — which clusters and minions it can touch

At run time the AI autonomously decides which tools to call, in what order, based on what it finds. The agent loops until it reaches an answer or hits its timeout.

### Human Approval Gate

Destructive tools (restart pod, scale deployment, drain node, etc.) are **never pre-approved by default**. When the agent wants to call one, it pauses and shows an approval card in the UI:

```
Agent wants to: restart pod "payments-api-5d9b7" in namespace "production"

[Approve]  [Skip]
```

- **Approve** — agent executes the action and continues
- **Skip** — agent skips that action and tries an alternative

> God Mode must be active to approve destructive actions.

If no human responds within the `agent_approval_timeout_seconds` (default 600), the action is automatically skipped.

### Creating an Agent

1. Click **Agents** in the sidebar.
2. Click **New Agent**.
3. Fill in:

| Field | Description |
|-------|-------------|
| **Name** | Display name |
| **Goal** | Plain English description of what the agent should achieve |
| **Discover Tools** | Click to let the AI suggest tools based on your goal |
| **Approved Tools** | Review and adjust the tool list; toggle off any you don't want |
| **Target Clusters** | Which clusters the agent can query |
| **Target Minions** | Which minion servers the agent can access |
| **Trigger** | Manual, cron, or webhook |
| **Max Retries** | How many times to retry a failed tool call (default: 3) |
| **Timeout** | Maximum agent run time in seconds (default: 900) |

4. Click **Save**.

### AI Tool Discovery

Click **Discover Tools** in the agent creation drawer to let the AI pre-select tools from the catalog based on your goal text. You can add/remove tools from the suggestion before saving.

### Running an Agent

- **Manual:** Click **Run** on the agent card.
- **Webhook:** `POST http://localhost:8000/api/v1/workflows/{id}/webhook/{token}`
- **Cron:** Fires on the configured schedule.

### Viewing Agent Runs

Click an agent → **History** tab. Each run shows:
- Status: `pending` / `running` / `awaiting_approval` / `completed` / `failed`
- Click a run to open the **Live Run Panel** — streams tool calls, results, and any approval requests in real time

### Agent Tool Catalog

The full catalog available for agent use:

| Category | Tools |
|----------|-------|
| **K8s Read** | `search_pods`, `get_pod_status`, `get_pod_logs`, `get_pod_events`, `describe_pod`, `get_events`, `get_deployment_status`, `list_deployments`, `get_node_status`, `list_services`, `get_service`, `list_namespaces`, `get_cluster_health`, `get_top_pods`, `get_pod_metrics`, `list_statefulsets`, `list_daemonsets`, `list_pvcs` |
| **K8s Write** (need approval) | `restart_pod`, `scale_deployment`, `rollback_deployment`, `patch_deployment_resources`, `cordon_node`, `drain_node`, `delete_deployment` |
| **Notifications** | `post_teams`, `post_slack` |
| **Minion** | `run_minion_command`, `list_minion_services`, `run_service_probe`, `get_service_logs` |

### API

```bash
# Discover tools for a goal
curl -X POST http://localhost:8000/api/v1/workflows/agents/discover-tools \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"goal": "investigate pod crash and notify Slack"}'

# Stream a run's events (SSE)
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/workflows/runs/{run_id}/stream

# Approve a paused run
curl -X POST http://localhost:8000/api/v1/workflows/runs/{run_id}/approve \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"decision":"approve"}'
```

---

## Scripted Workflows

### Core Concepts

**Workflow** — a named sequence of steps with a trigger and optional input schema.

**Trigger** — what starts the workflow:
- **Manual** — triggered from the UI
- **Webhook** — triggered by an HTTP POST to a unique URL
- **Cron** — triggered on a schedule

**Step** — a single action in the workflow. Steps can reference outputs from previous steps using template variables.

**Connector** — the external service a step calls (Slack, Jira, email, HTTP, etc.).

---

## Creating a Scripted Workflow

1. Click **Workflows** in the sidebar.
2. Click **New Workflow**.
3. Give it a name and description.
4. Choose a trigger type.
5. Add steps.
6. Click **Save**.

---

## Trigger Types

### Manual Trigger

The workflow runs when you click **Run** from the UI. You can define an input schema (JSON) that the user fills in before running:

```json
{
  "namespace": {"type": "string", "description": "Target namespace"},
  "replica_count": {"type": "number", "description": "New replica count"}
}
```

### Webhook Trigger

DokOps generates a unique webhook URL:
```
POST http://localhost:8000/api/v1/workflows/{id}/webhook/{token}
```

Any HTTP client can trigger the workflow by POSTing JSON to this URL. The JSON body becomes the workflow input.

Example: Trigger from Alertmanager:

```yaml
# alertmanager.yml
receivers:
  - name: dokops-webhook
    webhook_configs:
      - url: http://dokops.internal:8000/api/v1/workflows/abc123/webhook/xyz789
        send_resolved: true
```

### Cron Trigger

Use standard cron syntax:

```
0 9 * * 1-5        # 9am weekdays
*/30 * * * *       # every 30 minutes
0 0 * * *          # daily at midnight
```

---

## Steps

### Kubernetes Step

Execute a Kubernetes operation:

```json
{
  "type": "kubernetes",
  "action": "scale_deployment",
  "params": {
    "namespace": "{{input.namespace}}",
    "deployment": "{{input.deployment}}",
    "replicas": "{{input.replicas}}"
  }
}
```

### HTTP Step

Call any HTTP endpoint:

```json
{
  "type": "http",
  "method": "POST",
  "url": "https://api.pagerduty.com/incidents",
  "headers": {
    "Authorization": "Token token={{env.PAGERDUTY_TOKEN}}",
    "Content-Type": "application/json"
  },
  "body": {
    "incident": {
      "title": "K8s alert: {{input.alert_name}}",
      "service": {"id": "{{env.PD_SERVICE_ID}}"}
    }
  }
}
```

### Slack Step

```json
{
  "type": "slack",
  "webhook_url": "{{env.SLACK_WEBHOOK_URL}}",
  "message": "Deployment {{input.deployment}} scaled to {{input.replicas}} replicas by {{context.actor}}"
}
```

### Microsoft Teams Step

```json
{
  "type": "teams",
  "webhook_url": "{{env.TEAMS_WEBHOOK_URL}}",
  "title": "DokOps Alert",
  "message": "{{input.alert_message}}"
}
```

### Jira Step

DokOps supports both **Atlassian Cloud** and **self-hosted Jira Server/Data Center**. Configure credentials under **Settings → Integrations → Jira** and select the correct `instance_type`.

| Instance Type | API Version | Auth | Body format |
|---------------|------------|------|-------------|
| `cloud` | REST v3 | Email + API token | Atlassian Document Format (ADF) |
| `server` | REST v2 | Username + Password or PAT | Plain string |

```json
{
  "type": "jira",
  "action": "create_issue",
  "project": "OPS",
  "summary": "K8s incident: {{input.alert_name}}",
  "description": "{{input.details}}",
  "priority": "High",
  "labels": ["kubernetes", "automated"],
  "custom_fields": {
    "customfield_10014": "{{input.sprint_id}}",
    "customfield_10016": 5
  }
}
```

The `custom_fields` map accepts any Jira field key. Values are passed through as-is — strings, numbers, or nested objects — so you can populate Epic links, story points, or any project-specific field.

### Jenkins Step

```json
{
  "type": "jenkins",
  "url": "http://jenkins.internal:8080",
  "job": "deploy-application",
  "params": {
    "ENVIRONMENT": "{{input.environment}}",
    "VERSION": "{{input.version}}"
  }
}
```

### ArgoCD Step

```json
{
  "type": "argocd",
  "url": "http://argocd.internal:8080",
  "action": "sync_app",
  "app_name": "{{input.app_name}}"
}
```

### Email Step

```json
{
  "type": "email",
  "to": ["oncall@example.com"],
  "subject": "DokOps Alert: {{input.alert_name}}",
  "body": "Cluster: {{context.cluster}}\nNamespace: {{input.namespace}}\nDetails: {{input.details}}"
}
```

---

## Template Variables

Use `{{variable}}` syntax in any step field:

| Variable | Value |
|----------|-------|
| `{{input.field_name}}` | Value from the workflow input |
| `{{steps.step_id.output}}` | Output from a previous step |
| `{{env.VAR_NAME}}` | Environment variable from DokOps env var store |
| `{{context.actor}}` | Username who triggered the workflow |
| `{{context.cluster}}` | Currently selected cluster name |
| `{{context.timestamp}}` | ISO timestamp of execution start |

---

## Execution History

Every workflow run is recorded:

1. Click **Workflows** → click a workflow name.
2. Click the **History** tab.
3. See all past runs with:
   - Trigger (manual/webhook/cron), trigger input
   - Status (running/completed/failed)
   - Per-step results and outputs
   - AI summary of what happened

---

## Example: Alert-to-Ticket Automation

This workflow creates a Jira ticket whenever Alertmanager fires a K8s alert.

```json
{
  "name": "Alert → Jira Ticket",
  "trigger_type": "webhook",
  "steps": [
    {
      "id": "get_pod_logs",
      "type": "kubernetes",
      "action": "get_pod_logs",
      "params": {
        "namespace": "{{input.labels.namespace}}",
        "pod": "{{input.labels.pod}}",
        "lines": 50
      }
    },
    {
      "id": "create_ticket",
      "type": "jira",
      "action": "create_issue",
      "project": "OPS",
      "summary": "K8s Alert: {{input.labels.alertname}} in {{input.labels.namespace}}",
      "description": "Alert fired at {{input.startsAt}}\n\nLast 50 log lines:\n{{steps.get_pod_logs.output}}"
    },
    {
      "id": "notify_slack",
      "type": "slack",
      "webhook_url": "{{env.SLACK_OPS_WEBHOOK}}",
      "message": "🚨 *{{input.labels.alertname}}* in `{{input.labels.namespace}}`\nJira ticket: {{steps.create_ticket.output.key}}"
    }
  ]
}
```

---

## Example: Daily Patch Report

```json
{
  "name": "Daily Patch Compliance Report",
  "trigger_type": "cron",
  "cron_schedule": "0 8 * * 1-5",
  "steps": [
    {
      "id": "scan_patches",
      "type": "http",
      "method": "POST",
      "url": "http://localhost:8000/api/v1/minions/patches/scan-all"
    },
    {
      "id": "get_compliance",
      "type": "http",
      "method": "GET",
      "url": "http://localhost:8000/api/v1/patches/compliance"
    },
    {
      "id": "email_report",
      "type": "email",
      "to": ["team@example.com"],
      "subject": "Daily Patch Compliance Report - {{context.timestamp}}",
      "body": "Compliance summary:\n{{steps.get_compliance.output}}"
    }
  ]
}
```
