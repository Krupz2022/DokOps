# Kubernetes Resources

The Resources page gives you a full browser for all Kubernetes objects in your cluster. It is the primary UI for inspecting workloads without typing `kubectl`.

---

## Navigation

1. Click **Resources** in the sidebar.
2. Select a **namespace** from the dropdown (or pick "All Namespaces").
3. Switch between tabs:

| Tab | Objects |
|-----|---------|
| **Pods** | All pods with status, restarts, age, node |
| **Deployments** | Deployments with replica counts |
| **Services** | ClusterIP, NodePort, LoadBalancer services |
| **Storage** | PersistentVolumeClaims and their bound volumes |
| **Config** | ConfigMaps and Secrets (names only — values hidden) |

---

## Pods

### Pod List

The pod list shows:
- **Name** — pod name
- **Status** — colored badge: `Running` (green), `Pending` (yellow), `Error`/`CrashLoopBackOff` (red), `Completed` (grey)
- **Restarts** — restart count (high restarts shown in orange/red)
- **Age** — time since creation
- **Node** — which worker node it's scheduled on
- **IP** — pod IP address

### Pod Detail

Click any pod to open the detail drawer:

**Overview Tab**
- Container images and their pull policy
- Resource requests and limits (CPU, Memory)
- Environment variables (values for non-secret vars)
- Volume mounts

**Logs Tab**
- Live log tail (last 100 lines by default)
- Container selector (if multi-container pod)
- Log search/filter
- Auto-scroll toggle

**Events Tab**
- Kubernetes events for this pod
- Shows scheduling failures, image pull errors, OOMKilled reasons

### Pod Actions (requires God Mode)

| Action | Description |
|--------|-------------|
| **Delete Pod** | Terminates the pod; the controller re-creates it |
| **Exec into Pod** | Opens an interactive terminal session in the container |
| **Download Logs** | Download full log output as a text file |

---

## Deployments

### Deployment List

Shows:
- **Name** — deployment name
- **Ready** — `3/3` means 3 of 3 desired replicas are available
- **Up-to-Date** — replicas running the current image version
- **Available** — replicas passing readiness probes
- **Age** — deployment age

### Deployment Actions (requires God Mode)

| Action | Description |
|--------|-------------|
| **Scale** | Change the number of replicas |
| **Restart** | Trigger a rolling restart (updates `rollingUpdate` annotations) |
| **Delete** | Remove the deployment and all its pods |
| **View YAML** | Show raw deployment manifest |

### Scale Example

1. Click a deployment → click **Scale**.
2. Enter the desired replica count (e.g., `5`).
3. Click **Confirm** — DokOps calls `PATCH /apis/apps/v1/namespaces/{ns}/deployments/{name}/scale`.
4. The deployment list updates in real time.

---

## Services

Shows all services with:
- **Type**: ClusterIP, NodePort, LoadBalancer, ExternalName
- **Cluster IP**: internal service IP
- **Port(s)**: exposed ports and protocols
- **Selector**: which pods this service routes to
- **External IP**: for LoadBalancer services

---

## Storage

Shows PersistentVolumeClaims:
- **Status**: Bound (green), Pending (yellow), Lost (red)
- **Capacity**: requested storage size
- **Access Modes**: ReadWriteOnce, ReadWriteMany, ReadOnlyMany
- **Storage Class**: provisioner used
- **Volume**: name of the bound PersistentVolume

---

## Config

### ConfigMaps

Shows all ConfigMaps with:
- Name, namespace, age
- Key count
- Click to expand and view keys and values

### Secrets

Shows all Secrets with:
- Name, namespace, type, age
- **Values are never shown** — only key names are displayed
- This is enforced at the API layer, not just the UI

---

## Search

Use the global **Pod Search** (available from the header) to find pods by name across all namespaces:

```
# Example: find all pods with "nginx" in the name
/pods?search=nginx
```

---

## Example: Investigating an OOMKilled Pod

1. Go to **Resources** → select namespace `production`.
2. In the Pods tab, look for a pod with red `OOMKilled` status.
3. Click the pod → **Overview** — note the memory limit (e.g., `128Mi`).
4. Click **Events** — look for `OOMKilled` events.
5. Click **Logs** — the last few lines before the kill.
6. Open AI Chat and ask: *"The pod payments-api-xyz was OOMKilled. Suggest a new memory limit."*

---

## Namespace Operations (God Mode)

From the namespace dropdown:
- **Create Namespace** — creates a new namespace
- **Delete Namespace** — permanently removes namespace and all resources (dangerous)
