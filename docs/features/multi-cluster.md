# Multi-Cluster Management

DokOps can manage multiple Kubernetes clusters simultaneously. You switch between clusters using the **Cluster Context Selector** in the header — every page (Dashboard, Resources, AI Chat, Topology) respects the currently selected cluster.

---

## Adding Clusters

Go to **Clusters** in the sidebar. Click **Add Cluster** and choose a connection method:

### Method 1 — Upload Kubeconfig

Best for clusters you already access with `kubectl`.

1. Click **Upload Kubeconfig**.
2. Paste your kubeconfig YAML, or click **Browse** to upload a file.
3. If the kubeconfig has multiple contexts, select which context to use.
4. Give the cluster a name (e.g., `prod-eu-west`, `staging-us-east`).
5. Click **Save & Verify** — DokOps tests the connection.

The kubeconfig is stored **encrypted** in the database using Fernet encryption. The raw kubeconfig is never stored in plaintext.

### Method 2 — Bearer Token

Best for service account tokens or when you don't have a kubeconfig file.

1. Click **Connect via Token**.
2. Fill in:
   - **API Server URL**: e.g., `https://my-cluster.example.com:6443`
   - **Bearer Token**: service account token (base64-decoded)
   - **CA Certificate** (optional): cluster CA for TLS verification

### Method 3 — Azure AKS Auto-Discovery

1. Click **Cloud Credentials** → **Add Azure Credentials**.
2. Enter:
   - **Tenant ID**, **Client ID**, **Client Secret**
   - **Subscription ID** (to scope discovery)
   - Optionally: **Resource Group** (to further scope)
3. Click **Save Credentials**.
4. Click **Discover AKS Clusters** — DokOps queries the Azure API and lists all AKS clusters in your subscription.
5. Click **Import** next to each cluster you want to manage.

### Method 4 — AWS EKS Auto-Discovery

1. Click **Cloud Credentials** → **Add AWS Credentials**.
2. Enter:
   - **Access Key ID**
   - **Secret Access Key**
   - **Region** (e.g., `us-east-1`)
3. Click **Discover EKS Clusters** — lists all EKS clusters in that region.
4. Click **Import** next to each cluster.

---

## Verifying a Cluster

After adding a cluster, click the **Verify** button on its card. DokOps will:

1. Connect to the cluster API server.
2. List namespaces (requires `list` permission on `namespaces`).
3. Show **Verified** (green) or display the error.

If verification fails, common causes:
- The API server is not reachable from the DokOps backend (check firewall/VPN)
- The service account token expired
- The kubeconfig context points to a different cluster

---

## Switching Clusters

The **Cluster Context Selector** lives in the top header bar. Click the current cluster name to open the dropdown and select a different cluster.

All data shown in the Dashboard, Resources, Topology, and AI Chat will switch to the newly selected cluster immediately.

---

## Setting a Default Cluster

1. Go to **Clusters**.
2. Click the ⭐ (star) icon on the cluster card you want as default.
3. On login, DokOps always starts with the default cluster active.

---

## Deleting a Cluster

1. Go to **Clusters**.
2. Click the **Delete** (trash) icon on the cluster card.
3. Confirm the deletion.

This removes the cluster connection from DokOps. It does **not** delete anything from the actual Kubernetes cluster.

---

## Example: Multi-Cluster AI Diagnosis

You can switch clusters mid-conversation. The AI always uses the currently selected cluster:

```
# Select "prod-eu" cluster in header
User: What pods are failing in production?
AI: [calls list_pods on prod-eu cluster]...

# Switch to "staging-us" in header, continue conversation
User: Same question for staging
AI: [calls list_pods on staging-us cluster]...
```

---

## Required Kubernetes Permissions

DokOps needs the following RBAC permissions on each cluster:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: dokops-reader
rules:
  # Read-only (Normal Mode)
  - apiGroups: ["", "apps", "batch", "networking.k8s.io", "storage.k8s.io"]
    resources: ["pods", "pods/log", "deployments", "services", "ingresses",
                "configmaps", "secrets", "nodes", "namespaces",
                "persistentvolumeclaims", "persistentvolumes", "events",
                "replicasets", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch"]
  # God Mode additions
  - apiGroups: ["", "apps"]
    resources: ["pods", "deployments", "namespaces", "deployments/scale"]
    verbs: ["delete", "patch", "update", "create"]
  - apiGroups: [""]
    resources: ["pods/exec"]
    verbs: ["create"]
```

Apply the DokOps agent manifest for a pre-built service account:

```bash
kubectl apply -f http://localhost:8000/static/dokops-agent.yaml
```

This creates the `dokops` service account, the ClusterRole, and a ClusterRoleBinding. The generated token is shown in the UI for you to copy into the cluster connection form.
