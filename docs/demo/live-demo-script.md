# DokOps Live Demo Script

**Stack:** minikube · backend `localhost:8000` · frontend `localhost:5173`

Run **Setup** once before the demo. The three use cases are independent — you can run any one alone.

---

## One-Time Pre-Demo Setup

```bash
# 1. Confirm minikube is running
minikube status

# 2. Start backend (terminal 1)
cd backend
uvicorn app.main:app --reload --port 8000

# 3. Start frontend (terminal 2)
cd frontend
npm run dev

# 4. Set the alertmanager webhook secret in the UI
#    → Settings → Alert Response → Webhook Secrets → alertmanager → "demodemo123" → Save
#    OR via API:
curl -s -X PUT http://localhost:8000/api/v1/alerts/webhook-config \
  -H "Authorization: Bearer <your-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"alertmanager":"demodemo123"}'
```

---

## Use Case 1 — Autonomous Alert Triage (No Human Paged)

**Story:** 3AM, a pod crashes. DokOps receives the alert, diagnoses the root cause, and has a report ready before anyone wakes up.

### Setup (run before presenting)

```bash
# Deploy a pod that will crash immediately (bad command)
kubectl create deployment demo-crasher \
  --image=busybox \
  -- /bin/sh -c "echo starting && sleep 2 && exit 1"

# Wait for it to start crash-looping (~30s)
kubectl get pods -w
# You should see demo-crasher-xxx   0/1   CrashLoopBackOff
```

### Live Steps

**Step 1 — Fire the simulated alert (paste this curl live)**

```bash
curl -s -X POST http://localhost:8000/api/v1/alerts/webhook/alertmanager \
  -H "Authorization: Bearer demodemo123" \
  -H "Content-Type: application/json" \
  -d '{
    "alerts": [{
      "labels": {
        "alertname": "KubePodCrashLooping",
        "pod": "demo-crasher",
        "namespace": "default",
        "severity": "critical"
      },
      "annotations": {
        "summary": "Pod demo-crasher has been restarting repeatedly"
      },
      "status": "firing",
      "startsAt": "2026-06-07T03:00:00Z",
      "fingerprint": "demo-uc1-001"
    }]
  }'
# Response: {"status":"accepted","alerts_queued":1}
```

**Step 2 — Show the UI**

Navigate to **Alert Incidents** in the sidebar. The alert appears within seconds. The agent is already running in the background — click into it and watch the RCA populate in real time.

**Step 3 — Talk track while it runs**

> "We didn't page anyone. DokOps received this at 3AM, fetched the logs, identified the root cause, and now our on-call engineer comes in to a ready-made report with a one-click remediation option. MTTR drops from 45 minutes to the time it takes to read one screen."

### Teardown

```bash
kubectl delete deployment demo-crasher
```

---

## Use Case 2 — ImagePullBackOff: Agent Finds the Fix

**Story:** Someone deployed a version of an internal DNS addon that doesn't exist. The pod is stuck. DokOps diagnoses it, searches the container registry for valid versions, and proposes a one-click patch — without anyone Googling anything.

### Setup (run before presenting)

```bash
# Enable Registry Lookup in the UI first
# → Settings → Registry Lookup → toggle ON

# This deployment is ALREADY RUNNING in kube-system from our demo prep.
# Verify it's still stuck:
kubectl get pods -n kube-system -l app=ingress-dns-demo
# ingress-dns-demo-xxx   0/1   ImagePullBackOff

# If it was deleted or is missing, recreate it:
kubectl create deployment ingress-dns-demo \
  --image="kicbase/minikube-ingress-dns:0.0.9" \
  -n kube-system

# Confirm (wait ~30s):
kubectl get pods -n kube-system -l app=ingress-dns-demo -w
# ingress-dns-demo-xxx   0/1   ImagePullBackOff
```

### Live Steps

**Step 1 — Open AI Chat, type this prompt**

```
There's a failing DNS addon deployment in kube-system called ingress-dns-demo. Investigate and fix it.
```

**What the agent does (you narrate each step as it happens):**

1. Calls `describe_pod("ingress-dns-demo-xxx", "kube-system")` → sees `ImagePullBackOff`, extracts the image: `kicbase/minikube-ingress-dns:0.0.9`
2. Calls `get_pod_events("ingress-dns-demo-xxx", "kube-system")` → reads the error: `manifest for kicbase/minikube-ingress-dns:0.0.9 not found`
3. Calls `search_container_image("kicbase/minikube-ingress-dns:0.0.9")` → Registry Lookup queries Docker Hub; returns available tags: `["0.0.4", "0.0.3", "0.0.2", "0.0.1"]`
4. Calls `apply_manifest(...)` → proposes patching the deployment to use `kicbase/minikube-ingress-dns:0.0.4`

> "The agent understood the problem, searched the actual registry, found a valid version, and built the patch. Nobody googled anything."

**Step 2 — The amber "Pending Approval" card appears**

> "This is the safety layer enterprises need. The AI cannot deploy without human sign-off. It gets you to the decision, you make the call."

Click **Approve**.

**Step 3 — Confirm it worked**

```bash
kubectl get pods -n kube-system -l app=ingress-dns-demo
# ingress-dns-demo-xxx   1/1   Running
```

### Fallback: If Registry Lookup returns no results

If Docker Hub is unreachable, the agent will say:
> "I couldn't find valid tags for this image on the configured registries. The image may have moved. Can you provide the correct image reference?"

**You respond in chat:** `"The correct image is docker.io/kicbase/minikube-ingress-dns:0.0.4"` — the agent then proposes `apply_manifest` with that image. This still demonstrates the full diagnostic loop and approval gate; it just skips the auto-discovery step.

Toggle Registry Lookup OFF before the demo if you want to show this fallback path instead.

### Teardown

```bash
kubectl delete deployment ingress-dns-demo -n kube-system
```

---

## Use Case 3 — God Mode: Memory Patch with Full Audit Trail

**Story:** A payment service is OOMKilled repeatedly. DokOps diagnoses it, calculates the right memory limit, proposes an exact patch. Senior engineer reviews and approves with a full audit trail.

### Setup (run before presenting)

```bash
# Deploy with an absurdly low memory limit so it OOMKills immediately
kubectl create deployment payments-demo --image=nginx
kubectl set resources deployment payments-demo \
  --limits=memory=5Mi --requests=memory=5Mi

# Wait for OOMKill (~15s)
kubectl get pods -w
# payments-demo-xxx   0/1   OOMKilled  (or CrashLoopBackOff after a few cycles)
```

### Live Steps

**Step 1 — Open AI Chat, type this prompt**

```
Why does payments-demo keep crashing in the default namespace?
```

**What the agent does:**

1. Calls `diagnose_pod("payments-demo-xxx")` → identifies `OOMKilled`, reports current limit is `5Mi`
2. Calls `get_pod_events("payments-demo-xxx")` → confirms repeated OOM events
3. Proposes: call `apply_manifest` with `limits.memory: 256Mi`
4. Amber card appears: **"Patch payments-demo memory limit from 5Mi → 256Mi — Approve?"**

**Step 2 — Enable God Mode**

Click the **God Mode** toggle in the top header. It turns red/amber.

> "God Mode is required for any write operation against production clusters. It's scoped to the session, logged, and can be revoked centrally."

**Step 3 — Approve the patch**

Click **Approve** on the pending card.

**Step 4 — Show the Audit page**

Navigate to **Audit** in the sidebar. The log entry shows:

```
[timestamp]  admin  APPLY_MANIFEST  payments-demo/deployment  GOD_MODE  
  → limits.memory: 5Mi → 256Mi
```

> "Every action is logged. Who approved it, when, what changed, and whether God Mode was active. This is what your compliance team needs."

**Step 5 — Confirm pod is running**

```bash
kubectl get pods
# payments-demo-xxx   1/1   Running
```

### Teardown

```bash
kubectl delete deployment payments-demo
```

---

## Demo Order Recommendation

Run them in this order for maximum impact:

| # | Use Case | Wow Factor |
|---|----------|------------|
| 1 | Alert triage (UC1) | Opens with "it ran automatically at 3AM" |
| 2 | ImagePullBackOff fix (UC2) | "AI searched the registry, found the tag, proposed the patch" |
| 3 | God Mode memory patch (UC3) | Closes with governance + audit trail — the compliance story |

**Total live demo time:** ~12 minutes if you run all three.

---

## Fallback: If Registry Lookup Returns Nothing (Use Case 2)

This can happen if gcr.io's OCI tags endpoint is unavailable or returns nothing. The agent will ask for the correct image reference — you respond in chat with `docker.io/kicbase/minikube-ingress-dns:0.0.4`. The diagnostic loop and approval gate still work; auto-discovery is just skipped. Toggle Registry Lookup OFF in Settings if you want to demo the no-search path intentionally.
