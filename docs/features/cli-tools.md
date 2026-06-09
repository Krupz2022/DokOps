# CLI Tools

DokOps can register and execute CLI tools directly from the web UI. This lets you run Helm, kubectl plugins, custom scripts, or any shell command through DokOps — with environment variable injection and a consistent audit trail.

---

## Built-in CLI Tools

DokOps ships with the following pre-defined tools. Each can be detected (shows installed version) and installed directly from the UI:

| Tool | Description |
|------|-------------|
| **helm** | Kubernetes package manager — install, upgrade, and rollback releases |
| **kubectl** | Official Kubernetes CLI — raw cluster operations |
| **kubectx** | Fast cluster and namespace context switcher |
| **kustomize** | Kubernetes native config management via overlays |
| **flux** | FluxCD GitOps CLI — manage continuous delivery pipelines |
| **argocd** | Argo CD CLI — declarative GitOps for Kubernetes |
| **helm-diff** | Helm plugin — preview what changes a `helm upgrade` would apply |

Built-in tools appear under **CLI Tools** in the sidebar. Click any tool name to open an execution panel.

---

## Executing a CLI Tool

1. Click **CLI Tools** in the sidebar.
2. Select a tool from the list.
3. Enter the arguments (e.g., `get pods -n production -o wide`).
4. Click **Run** — output streams back in real time.

The working directory and environment variables are automatically injected from your configured env var store.

---

## Environment Variables

CLI tools run with injected environment variables, configured in **Toolsets** → **Environment Variables**:

1. Go to **Toolsets** in the sidebar.
2. Click the **Environment Variables** tab.
3. Add key-value pairs (e.g., `KUBECONFIG=/root/.kube/config`).
4. These are available to all CLI tool executions.

```bash
# CLI tool execution runs with injected env:
kubectl get pods -n production
# runs as: KUBECONFIG=/root/.kube/config kubectl get pods -n production
```

---

## Custom CLI Tools

You can register custom shell scripts or executables as DokOps CLI tools:

1. Click **CLI Tools** → **Custom Tools** tab.
2. Click **Add Custom Tool**.
3. Fill in:
   - **Name** — tool identifier (e.g., `my-healthcheck`)
   - **Description** — shown in the UI
   - **Command** — the executable path (e.g., `/opt/scripts/healthcheck.sh`)
   - **Arguments Template** — default arguments (can include `$VAR_NAME` references)
4. Click **Save**.

### Custom Tool with Arguments

```json
{
  "name": "database-backup",
  "description": "Backup a PostgreSQL database",
  "command": "/opt/scripts/pg-backup.sh",
  "args_template": "--database $DB_NAME --output /backups"
}
```

The user fills in `$DB_NAME` from the UI before running.

### Installing Tools on the Server

If a tool isn't installed on the DokOps backend server, you can trigger installation:

1. Click the tool → click **Install**.
2. DokOps runs the appropriate package manager command (`apt-get install`, `pip install`, etc.) on the backend.
3. The tool becomes available for execution.

---

## Helm Toolset

The Helm toolset is pre-configured with common Helm commands. View and edit it under **Toolsets** → select the Helm toolset:

```yaml
# backend/app/toolsets/helm_toolset.yaml
tools:
  helm_list:
    command: helm list
    args: "--all-namespaces -o json"
    god_mode_required: false
    description: "List all Helm releases"

  helm_status:
    command: helm status
    args: "$RELEASE_NAME -n $NAMESPACE"
    god_mode_required: false
    description: "Get status of a Helm release"

  helm_history:
    command: helm history
    args: "$RELEASE_NAME -n $NAMESPACE"
    god_mode_required: false
    description: "Show revision history of a release"

  helm_rollback:
    command: helm rollback
    args: "$RELEASE_NAME $REVISION -n $NAMESPACE"
    god_mode_required: true          # Requires God Mode
    description: "Roll back a release to a previous revision"

  helm_upgrade:
    command: helm upgrade
    args: "$RELEASE_NAME $CHART --values $VALUES_FILE -n $NAMESPACE"
    god_mode_required: true
    description: "Upgrade a Helm release"
```

### Example: Helm via AI Chat

```
User: "Show me the history of the payments Helm release"

AI: [Step] Running helm_history for release 'payments'...
    Command: helm history payments -n production

    REVISION  UPDATED                  STATUS     CHART           APP VERSION
    1         Mon May 20 10:00:00 2026 superseded payments-2.0.0  1.5.0
    2         Tue May 21 14:30:00 2026 superseded payments-2.0.5  1.5.1
    3         Wed May 22 09:00:00 2026 deployed   payments-2.1.0  1.6.0

    Current release is revision 3 (payments-2.1.0).
    Previous stable version: revision 2 (payments-2.0.5).
```

---

## Toolset YAML Editor

Go to **Toolsets** to view and edit toolset YAML directly in the browser:

1. Click **Toolsets** in the sidebar.
2. Select a toolset (e.g., Helm).
3. Edit the YAML in the syntax-highlighted editor.
4. Click **Save** — changes take effect immediately.

The editor includes:
- Syntax highlighting
- Real-time YAML validation
- Error messages for invalid YAML

---

## Via API

```bash
# List built-in CLI tools
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/system/cli-tools

# List custom tools
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/system/cli-tools/custom

# Register a custom tool
curl -X POST http://localhost:8000/api/v1/system/cli-tools/custom \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "healthcheck",
    "description": "Run cluster health check script",
    "command": "/opt/scripts/healthcheck.sh",
    "args_template": "--namespace $NAMESPACE"
  }'

# Install a built-in tool on the server
curl -X POST http://localhost:8000/api/v1/system/cli-tools/helm/install \
  -H "Authorization: Bearer $TOKEN"
```
