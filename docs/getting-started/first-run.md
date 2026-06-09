# First Run & Setup

When you open DokOps for the first time, the **Setup Wizard** appears. This walks you through creating an admin account and connecting an AI provider.

---

## Step 1 — Create Admin Account

Fill in a username and password. This becomes your first superuser account.

> If you pre-seeded credentials via environment variables (`DOKOPS_ADMIN_USERNAME` / `DOKOPS_ADMIN_PASSWORD`), you can skip this step — those credentials are already active.

---

## Step 2 — Connect an AI Provider

DokOps supports three AI backends. Choose whichever you have access to:

### Google Gemini (Recommended for Quick Start)

1. Get an API key from [Google AI Studio](https://aistudio.google.com/).
2. Select **Gemini** in the dropdown.
3. Paste your API key.
4. Select model: `gemini-2.0-flash` (fast) or `gemini-2.0-pro` (thorough).
5. Click **Test Connection** → should return "Connection successful".

### OpenAI

1. Get an API key from your OpenAI account.
2. Select **OpenAI** in the dropdown.
3. Paste your `sk-...` key.
4. Select model: `gpt-4o` (recommended).
5. Click **Test Connection**.

### Azure OpenAI

1. Create an Azure OpenAI resource and deploy a model (e.g., `gpt-4o`).
2. Select **Azure** in the dropdown.
3. Fill in:
   - **Endpoint**: `https://your-resource.openai.azure.com/`
   - **API Key**: your Azure OpenAI key
   - **Deployment Name**: the deployment name (e.g., `gpt-4o`)
   - **API Version**: `2024-02-01` (or latest)
4. Click **Test Connection**.

---

## Step 3 — Connect a Cluster

After setup, go to **Clusters** in the sidebar.

### Option A: Upload kubeconfig

1. Click **Add Cluster** → **Upload kubeconfig**.
2. Paste or upload your kubeconfig file.
3. If it has multiple contexts, select which context to use.
4. Give it a friendly name (e.g., "Production EKS").
5. Click **Verify** — DokOps will test the connection.

### Option B: Bearer Token

1. Click **Add Cluster** → **Connect via Token**.
2. Provide the API server URL and a service account bearer token.
3. Optionally provide the cluster CA certificate.

### Option C: Cloud Auto-Discovery

**Azure AKS:**
1. Go to **Clusters** → **Cloud Credentials** → **Add Azure Credentials**.
2. Enter your Azure Service Principal credentials (tenant ID, client ID, client secret, subscription ID).
3. Click **Discover Clusters** — DokOps lists all AKS clusters in your subscription.
4. Click **Import** next to any cluster.

**AWS EKS:**
1. Click **Add AWS Credentials**.
2. Enter your Access Key ID, Secret Access Key, and region.
3. Click **Discover Clusters** — lists all EKS clusters.
4. Click **Import**.

---

## Step 4 — Set Default Cluster

If you have multiple clusters, mark one as default:

1. Go to **Clusters**.
2. Click the ⭐ next to the cluster you want as default.
3. All dashboard and AI chat queries will use this cluster unless you switch context from the header.

---

## Step 5 — (Optional) Enable God Mode

God Mode allows write operations (scale, delete, restart, patch). It is **disabled by default**.

To enable for your session:
1. Click **Normal Mode** in the header banner.
2. Read the warning dialog.
3. Click **Enable God Mode**.

The header banner turns red. All destructive operations are now unlocked but require a confirmation dialog and are logged in the audit trail.

> God Mode is per-session. It resets to Normal Mode on logout.

---

## You're Ready

- Open [AI Chat](../features/ai-chat.md) and try: *"What pods are failing in the default namespace?"*
- Browse [Kubernetes Resources](../features/kubernetes-resources.md) for a full cluster view.
- Check the [Quickstart](quickstart.md) for a guided 5-minute walkthrough.
