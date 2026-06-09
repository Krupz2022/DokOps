# Azure Integration

DokOps integrates with your Azure subscription to provide cost management, resource discovery, anomaly detection, and AI-powered cost optimization recommendations — all within the same interface you use for Kubernetes.

---

## Connecting Azure

1. Go to **Integrations** → **Azure** in the sidebar.
2. Click **Connect Azure Subscription**.
3. Fill in your Service Principal credentials:

```
Tenant ID:       xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Client ID:       xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Client Secret:   (stored encrypted in DokOps DB)
Subscription ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Resource Group:  (optional — scope to one resource group)
AKS Cluster:     (optional — link to a DokOps-managed cluster)
```

4. Click **Connect** — DokOps validates the credentials against the Azure API.
5. Toggle on the features you want to use.

### Required Azure RBAC Permissions

The Service Principal needs:

```
Role: Cost Management Reader          (for cost data)
Role: Reader                          (for resource discovery)
Role: Azure Kubernetes Service Reader (for AKS data)
```

Or use the **Contributor** role for full access (broader than needed — use Reader roles in production).

---

## Features

Enable/disable each feature independently from the **Azure Integration** settings card:

| Feature | Description |
|---------|-------------|
| **Cost Optimization** | Current spend, forecasts, budget alerts |
| **Resource Discovery** | Inventory all resources in your subscription |
| **Azure Monitor** | Pull Azure Monitor metrics and alerts |
| **Cost Anomaly Alerting** | Detect unusual spend spikes |
| **AI Cost Recommendations** | GPT-4o analysis of your spending patterns |

---

## Cost Dashboard

The Cost Dashboard shows:

- **Monthly spend** — current month vs. previous month
- **Spend by resource group** — pie chart breakdown
- **Spend by service** (Compute, Storage, Networking, etc.)
- **30-day trend** — daily spend line chart
- **Forecast** — projected end-of-month spend

### Example

```
Monthly Spend (May 2026)
Total: $4,231.50 (+12% vs April)

By Service:
  Virtual Machines:    $2,100.00 (49%)
  AKS:                   $980.00 (23%)
  Storage:               $450.00 (11%)
  Networking:            $420.00 (10%)
  Other:                 $281.50 (7%)
```

---

## Resource Discovery

The Resource Discovery tab lists all Azure resources in your subscription (or scoped resource group):

- Resource name, type, region, resource group
- Tags
- Creation date
- Running cost (per-resource if available)

### AI Analysis

Click **Analyze Resources** to ask the AI to review your Azure inventory:

```
AI: Analyzing 247 resources in subscription 'prod'...

    Findings:
    1. 12 disks are unattached (not mounted to any VM). Monthly cost: ~$48.
       Recommendation: Review and delete unused disks.

    2. 3 public IP addresses are unassigned. Monthly cost: ~$9.
       Recommendation: Release unused public IPs.

    3. VM 'worker-legacy-001' has been running for 847 days with <5% CPU
       for the last 30 days. Consider downsizing or decommissioning.

    Estimated monthly savings: $180–$320
```

---

## Cost Anomaly Detection

DokOps monitors your Azure spend and flags anomalies:

- **Spike Detection** — unusual single-day spend (vs. rolling average)
- **Trending Alerts** — resource group spend trending up over N days
- **New High-Cost Resource** — a new resource appearing with unexpectedly high cost

Anomalies appear in the **Anomalies** tab with:
- Severity (Warning, Critical)
- Affected resource/group
- Expected vs. actual spend
- Detection date

---

## AI Cost Recommendations

Click **Get AI Recommendations** for a detailed cost optimization report:

The AI analyzes:
1. Idle or underutilized VMs
2. Oversized AKS node pools
3. Unattached disks and IPs
4. Reserved Instance opportunities (if you're paying on-demand)
5. Region cost differences for new deployments

```
User: Give me cost optimization recommendations

AI: Based on your Azure subscription spend analysis:

    HIGH IMPACT:
    - AKS node pool 'agentpool' averages 23% CPU utilization.
      Downsize from Standard_D4s_v3 to Standard_D2s_v3 → save ~$340/month

    MEDIUM IMPACT:
    - 3 VMs in 'dev-rg' are stopped but still incur disk costs.
      Delete or snapshot-and-delete → save ~$60/month

    LOW IMPACT:
    - Migrate storage accounts to LRS (from GRS) in non-prod environments
      → save ~$25/month

    Total estimated savings: ~$425/month
```

---

## Disconnect Azure

1. Go to **Integrations** → **Azure**.
2. Click **Disconnect**.
3. All Azure connection data and credentials are deleted from DokOps. Your Azure resources are untouched.

---

## Via API

```bash
# Get Azure connection status
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/integrations/azure/status

# Get cost data
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/integrations/azure/cost

# Get anomalies
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/integrations/azure/anomalies

# Toggle a feature
curl -X PATCH http://localhost:8000/api/v1/integrations/azure/features/cost_optimization \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```
