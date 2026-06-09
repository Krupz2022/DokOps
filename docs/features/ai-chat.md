# AI Chat

The AI Chat is the core of DokOps. It gives you a natural language interface to your Kubernetes cluster, powered by a function-calling agent loop that calls real K8s APIs during the conversation.

---

## How It Works

When you send a message:

1. The backend sends your message + conversation history to the AI provider.
2. The AI decides which Kubernetes tools to call (e.g., `list_pods`, `get_pod_logs`, `describe_deployment`).
3. The backend executes those tools against your real cluster.
4. The tool results are fed back to the AI.
5. Steps 2–4 repeat until the AI has enough information.
6. The final response streams back to your browser as Server-Sent Events (SSE).

You see each tool call as a **step card** in the chat — so you always know exactly what the AI queried.

---

## Conversations

### Create a Conversation
- Click **+ New Chat** in the conversation list on the left.
- Each conversation has its own history and context.

### Rename a Conversation
- Click the pencil icon next to the conversation name.

### Conversation Compaction
Long conversations are automatically summarized when token usage gets high. A **Compaction Banner** appears in the chat to indicate that older messages were compressed. The AI retains the key facts from prior messages.

You can also manually compact: click the **Compact** button in the conversation toolbar.

### Delete a Conversation
- Hover over the conversation → click the trash icon.

---

## Token Badge

Each message shows a token count badge. The total conversation token usage appears in the chat header. This helps you monitor cost and know when compaction will kick in.

---

## Streaming Response Types

The AI response is structured into different card types:

| Card Type | What it Shows |
|-----------|--------------|
| **Step Card** | A tool call the AI made (e.g., "Fetching logs from pod nginx-abc123...") |
| **Action Card** | A proposed action (e.g., "Restart deployment nginx") — clickable in God Mode |
| **Runbook Card** | A matched runbook guide (e.g., CrashLoopBackOff triage steps) |
| **Text** | The AI's narrative explanation and recommendations |
| **Pending Operation** | A God Mode operation awaiting your approval |

---

## Available Kubernetes Tools

The AI can call these tools during a conversation:

**Pods**
- `list_pods` — list pods in a namespace (or all namespaces)
- `describe_pod` — full pod spec, events, conditions
- `get_pod_logs` — fetch recent log lines
- `get_pod_metrics` — CPU and memory usage
- `exec_in_pod` — run a command inside a container (God Mode)
- `delete_pod` — delete a pod (God Mode)

**Deployments**
- `list_deployments` — list deployments and replica status
- `describe_deployment` — full deployment spec and rollout status
- `scale_deployment` — change replica count (God Mode)
- `restart_deployment` — rolling restart (God Mode)
- `get_deployment_yaml` — raw YAML

**Services, Ingresses, ConfigMaps, Secrets**
- `list_services`, `list_ingresses`, `list_configmaps`
- `get_configmap` — read ConfigMap data
- `list_secrets` — names only (values are never exposed)

**Nodes**
- `list_nodes`, `describe_node`, `get_node_metrics`

**Storage**
- `list_pvcs`, `describe_pvc`, `list_storage_classes`

**Namespaces**
- `list_namespaces`, `create_namespace`, `delete_namespace` (God Mode)

**Cluster-Wide**
- `get_cluster_health` — overall cluster health
- `get_topology` — dependency graph for blast radius

**Helm** (if Helm toolset is enabled)
- `helm_list`, `helm_status`, `helm_history`, `helm_diff_upgrade`
- `helm_rollback`, `helm_upgrade`, `helm_delete` (God Mode)

---

## Example Conversations

### Diagnose a Crashing Pod

```
User: Why is my api-server pod crashing in the production namespace?

AI: [Step] Listing pods in namespace 'production'...
    [Step] Describing pod 'api-server-6d9f7b-xyz'...
    [Step] Fetching logs from pod 'api-server-6d9f7b-xyz' (last 100 lines)...
    [Step] Fetching events for pod 'api-server-6d9f7b-xyz'...

    The pod is in CrashLoopBackOff. Logs show:
    "Error: ECONNREFUSED 10.96.0.5:5432 - database connection failed"

    Root cause: The pod cannot reach the PostgreSQL service. The service
    'postgres-svc' exists but has 0 ready endpoints — the database pod
    is not running.

    [Runbook] CrashLoopBackOff Triage →

    Recommended actions:
    1. Check the postgres deployment status
    2. If postgres pod is OOMKilled, increase its memory limit
```

### Check Node Pressure

```
User: Are any of my nodes under resource pressure?

AI: [Step] Listing nodes...
    [Step] Fetching metrics for all nodes...

    Node status:
    - worker-1: CPU 82% ⚠️, Memory 61% ✅
    - worker-2: CPU 34% ✅, Memory 78% ⚠️
    - worker-3: CPU 21% ✅, Memory 55% ✅

    worker-1 is under CPU pressure. Running 47 pods.
    worker-2 is approaching memory limit. Suggest checking for memory leaks.
```

### Roll Back a Helm Release

```
User: Roll back the payments chart to the previous version

AI: [Step] Fetching Helm history for release 'payments'...

    Release history:
    REVISION  STATUS     CHART VERSION
    3         deployed   payments-2.1.0 (current)
    2         superseded payments-2.0.5
    1         superseded payments-2.0.0

    [Action Card] Roll back 'payments' from revision 3 → revision 2
    [Requires God Mode to execute]
```

---

## Tips

- **Be specific about namespaces**: "pods in the production namespace" gives better results than "pods".
- **Chain questions**: The AI remembers the full conversation — you can say "now check its logs" and it knows which pod you mean.
- **Ask for YAML**: "Show me the YAML for the nginx deployment" returns the full raw manifest.
- **Observability queries**: If Prometheus/Elasticsearch is connected, the AI can query metrics and logs directly during diagnosis.
