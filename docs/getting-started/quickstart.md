# Quickstart — 5 Minutes to Your First AI Diagnosis

This guide assumes DokOps is running and you have completed [First Run setup](first-run.md).

---

## 1. Check the Dashboard (30 seconds)

Open DokOps at `http://localhost:3000`. The Dashboard shows:

- **Namespaces** — how many namespaces are in your cluster
- **Nodes** — node count and health (green = Ready, red = NotReady)
- **Pods** — total pod count and how many are Running vs. not
- **Health** — overall cluster health percentage

If you see a red health percentage, something is already failing — perfect for testing the AI.

---

## 2. Run Your First AI Diagnosis (2 minutes)

1. Click **AI Chat** in the sidebar.
2. Type: `What pods are not running in my cluster?`
3. Watch the streaming response:
   - The AI calls `list_pods` across all namespaces.
   - It identifies pods in `Error`, `CrashLoopBackOff`, `Pending`, or `OOMKilled` states.
   - It returns a structured summary with pod names, namespaces, and recommended next steps.

### Example Queries to Try

```
# Find failing workloads
"What's failing in my cluster right now?"

# Deep-dive into a specific pod
"Why is my nginx pod in namespace production crashing?"

# Check resource pressure
"Are any nodes under memory pressure?"

# Deployment status
"How many replicas does the payments deployment have?"

# Recent changes
"What events happened in the kube-system namespace in the last hour?"
```

---

## 3. View Resources (1 minute)

1. Click **Resources** in the sidebar.
2. Select a namespace from the dropdown (try `default` or `kube-system`).
3. Switch tabs: **Pods**, **Deployments**, **Services**, **Storage**, **Config**.
4. Click on any pod to see:
   - Status, restart count, node placement
   - Live logs (last 100 lines)
   - Events
   - Resource usage

---

## 4. View the Topology Graph (1 minute)

1. Click **Topology** in the sidebar.
2. Wait for the graph to load (it scans your cluster live).
3. You'll see colored nodes:
   - **Blue** = Pods
   - **Green** = Services
   - **Orange** = Ingresses
   - **Purple** = ConfigMaps
   - **Teal** = PersistentVolumeClaims
4. Click any node to see its details and what it depends on.
5. The graph shows **blast radius** — if you delete a node, what else breaks?

---

## 5. Enable God Mode and Restart a Pod (1 minute)

> Skip this step if you don't want to make changes to your cluster.

1. Click the **Normal Mode** banner in the header.
2. Click **Enable God Mode** and confirm.
3. Go to **Resources** → select a namespace → click a pod.
4. Click **Restart Pod** (or **Scale** on a Deployment).
5. A confirmation dialog appears with the exact action that will be taken.
6. Click **Confirm** — the action executes and appears in the **Audit Log**.

To view the audit trail: **Admin** → **Audit Logs**.

---

## Next Steps

| Want to... | Go to... |
|-----------|---------|
| Upload your own runbooks | [Diagnostics & Runbooks](../features/diagnostics-runbooks.md) |
| Connect Prometheus or Grafana | [Observability](../features/observability.md) |
| Set up SSO login | [Authentication](../security/authentication.md) |
| Automate operations | [Workflow Builder](../features/workflows.md) |
| Manage bare-metal servers | [Minions](../features/minions.md) |
| Deploy to production | [Helm Charts](../deployment/helm.md) |
