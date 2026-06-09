# Diagnostics & Runbooks

DokOps combines an automated **Diagnostic Engine** with human-authored **Runbooks** to give the AI structured triage procedures during incident response.

---

## Diagnostic Engine

The diagnostic engine runs automated health checks across your cluster resources. It inspects:

| Check Category | What It Looks For |
|---------------|-------------------|
| **Container State** | CrashLoopBackOff, OOMKilled, Error, ImagePullBackOff |
| **Probes** | Failing liveness/readiness probes |
| **Networking** | Services with no endpoints, broken Ingress backends |
| **Storage** | PVCs in Pending or Lost state |
| **RBAC** | Service accounts missing required permissions |
| **Scheduling** | Pods stuck in Pending (insufficient resources, node selectors, taints) |
| **Security Context** | Pods running as root in restricted namespaces |
| **Resource Limits** | Containers with no resource limits set |

### Running Diagnostics via AI

Ask the AI any health-related question — it automatically invokes the diagnostic tools:

```
"Run a health check on my cluster"
"Is anything broken in the staging namespace?"
"Why is my pod failing?"
```

### Running Diagnostics via API

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/k8s/cluster/health

# Response
{
  "overall": "degraded",
  "score": 74,
  "issues": [
    {
      "severity": "critical",
      "kind": "Pod",
      "name": "api-server-6d9f7b",
      "namespace": "production",
      "reason": "CrashLoopBackOff",
      "message": "Container has been restarting for 45 minutes"
    }
  ]
}
```

---

## Runbooks

Runbooks are Markdown files that describe step-by-step triage procedures for known failure patterns. When the AI detects a failure matching a runbook, it attaches a **Runbook Card** to the chat response.

### Built-in Runbooks

| Runbook | Trigger Condition |
|---------|-----------------|
| **CrashLoopBackOff Triage** | Pod in CrashLoopBackOff state |
| **OOMKilled Triage** | Pod terminated due to OOM |
| **Pod Pending Triage** | Pod stuck in Pending state |
| **Service Unreachable Triage** | Service has no ready endpoints |
| **High CPU Node Triage** | Node CPU > 80% |
| **High Memory Node Triage** | Node Memory > 80% |
| **Default Debug** | Fallback for unknown issues |

### Viewing Runbooks

Click **Runbooks** in the sidebar to see all available runbooks. Click any runbook to read its full content.

### Runbook Matching

When diagnosing, the AI uses semantic matching to find the most relevant runbook:

```python
# The AI sends the failure description to the match endpoint
POST /api/v1/ai/runbooks/match
{
  "problem": "Pod in CrashLoopBackOff, last exit code 1"
}

# Returns the best matching runbook
{
  "runbook_id": "crashloopbackoff_triage",
  "title": "CrashLoopBackOff Triage",
  "confidence": 0.94
}
```

---

## Writing Custom Runbooks

Place Markdown files in `backend/app/runbooks/`. They are auto-loaded on startup.

### Runbook Format

```markdown
# My Custom Runbook

**Trigger:** Brief description of when this applies (used for matching)

## Overview
What this runbook covers.

## Steps

### Step 1: Check Events
```kubectl describe pod <pod-name> -n <namespace>```
Look for: ImagePullBackOff, ErrImagePull, FailedScheduling

### Step 2: Check Logs
```kubectl logs <pod-name> -n <namespace> --previous```
Look for: connection refused, permission denied, out of memory

### Step 3: Resolution
- If image pull error: check image name, tag, and registry credentials
- If OOM: increase memory limit or optimize application
```

### Runbook Naming

Name files descriptively:
- `redis_connection_triage.md`
- `ingress_502_triage.md`
- `pvc_stuck_pending.md`

---

## Ingesting Runbooks into the Knowledge Base

You can also ingest runbooks into the **Knowledge Base (RAG)** so the AI can retrieve them as context during any conversation:

1. Go to **Knowledge Base** in the sidebar.
2. Click **Ingest Runbooks** — DokOps uploads all Markdown runbooks in `backend/app/runbooks/` into ChromaDB.
3. Now the AI can reference runbook content even for failures that don't exactly match a runbook trigger.

```
User: "What should I do when Redis is refusing connections?"
AI: [Retrieves 'redis_connection_triage.md' from knowledge base]
    Based on the Redis triage runbook:
    1. Check if the Redis pod is running...
```

---

## Example: Full CrashLoopBackOff Diagnosis

```
User: The payments service is crashlooping

AI: [Step] Listing pods in namespace 'production' matching 'payments'...
    Found: payments-api-6d9f7b-abc (CrashLoopBackOff, 14 restarts)

    [Step] Fetching pod events...
    Events: Back-off restarting failed container

    [Step] Fetching logs (last 50 lines, previous container)...
    Logs:
      Error: Connection refused to payments-db:5432
      Exiting with code 1

    [Step] Checking service 'payments-db'...
    Service exists but has 0 ready endpoints.

    [Step] Listing pods matching payments-db selector...
    pods/payments-db-xxx: Pending (Insufficient memory on all nodes)

    [Runbook Card] CrashLoopBackOff Triage →

    Root Cause: payments-api cannot start because payments-db has
    no running pods. payments-db pod is Pending due to insufficient
    memory on nodes.

    Recommended Actions:
    1. Scale down a non-critical deployment to free memory
    2. Or add a node to the cluster
    3. Once payments-db starts, payments-api will recover automatically
```
