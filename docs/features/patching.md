# Patch Management

DokOps provides a complete patch management system for your **Minion fleet** (bare-metal/VM servers). It tracks patch compliance, CVE exposure, and supports multi-stage patch pipelines with approval gates.

---

## Overview

Patching in DokOps works at three levels:

1. **Compliance** — scan servers for outdated packages and CVE exposure
2. **Groups** — organize servers into logical groups (dev, staging, prod)
3. **Pipelines** — apply patches in stages with promotion gates

---

## Patch Compliance Dashboard

Click **Patching** in the sidebar to see the compliance overview:

| Metric | Description |
|--------|-------------|
| **Total Minions** | Number of registered minions |
| **Fully Patched** | Minions with no outstanding updates |
| **Patch Available** | Minions with pending updates |
| **Critical CVEs** | Minions with known critical vulnerabilities |
| **Compliance %** | Percentage of minions fully patched |

Each row in the compliance table includes an **OS family badge** (`linux` / `windows`) detected from the minion's grains — useful for filtering in mixed-OS fleets.

### Per-Device Patch List

Click any minion row in the compliance table to see all outstanding patches for that specific server, sorted by severity (Critical → High → Medium → Low → None):

| Column | Description |
|--------|-------------|
| **Package** | Package or update name |
| **Installed** | Currently installed version |
| **Available** | Version to update to |
| **Advisory** | Advisory ID (e.g., `USN-1234`, `KB5034441`) |
| **CVE IDs** | Associated CVEs |
| **Severity** | Critical / High / Medium / Low |

### CVE View

Click **CVEs** to see vulnerabilities sorted by severity:

- **CVE ID** — e.g., `CVE-2024-1234`
- **Severity** — Critical, High, Medium, Low
- **Package** — affected package name
- **Affected Minions** — which servers have this CVE
- **Fix Available** — whether a patched version exists

---

## Scanning for Patches

### Manual Scan

1. Go to **Minions** → click a minion → click **Scan Patches**.
2. Or from **Patching** → click **Scan All Minions**.

### Automated Scan (via Schedule)

Create a [Patch Schedule](#patch-schedules) with a cron expression to scan automatically.

### What the Scan Checks

On Debian/Ubuntu:
```bash
apt list --upgradable 2>/dev/null
apt-get -s upgrade  # simulation mode to list packages
```

On RHEL/CentOS:
```bash
yum check-update
```

On **Windows**: the agent queries the **Windows Update Agent (WUA) COM API** (`win32com.client.Dispatch("Microsoft.Update.Session")`), which returns pending updates including KB article IDs, severity, and bulletin IDs. No third-party tools required.

CVE data is cross-referenced against a public CVE database using the package name and version.

---

## Applying Patches to a Group

Once compliance is scanned:

1. Go to **Patching** → select a group.
2. Review the list of pending patches.
3. Configure the apply scope:
   - **Security** — only packages with known CVEs or security advisories
   - **All** — all available updates
   - **Custom** — specify exact package names
4. Toggle **Reboot after patching** if the server should be restarted automatically once patches are applied (useful for kernel updates).
5. Click **Apply Patches** — this runs `apt upgrade` (or `yum update` / WUA on Windows) on all minions in the group.
6. Output streams per-minion.

> **God Mode is required** for apply operations.

---

## Patch Pipelines

Patch pipelines enforce a promotion-based workflow: patches must be applied and verified in each stage before moving to the next.

### Creating a Pipeline

1. Go to **Pipelines** in the sidebar.
2. Click **New Pipeline**.
3. Give it a name (e.g., "Monthly Security Patches").
4. Add stages:

| Stage | Target Group | Auto-Promote | Wait (hours) |
|-------|-------------|--------------|-------------|
| Dev | dev-servers | Yes | 2 |
| Staging | staging-servers | No (manual approval) | — |
| Production | prod-servers | No (manual approval) | — |

5. Click **Save**.

### Managing Pipeline Stages

Stages can be edited or deleted after the pipeline is created (God Mode required):

- **Rename a stage** — click the pencil icon on the stage row and change the name.
- **Reassign a group** — change which minion group a stage targets.
- **Delete a stage** — click the trash icon; the pipeline re-orders remaining stages.
- **Apply a single stage** — click **Apply** on a specific stage to patch that group without running the full pipeline from the start.

### Running a Pipeline

1. Click the pipeline → click **Start Run**.
2. The pipeline executes Stage 1 (Dev):
   - Patches are applied to the dev-servers group.
   - After the wait period, or immediately if auto-promote is on, the stage completes.
3. Stage 2 (Staging) shows as **Waiting for Promotion**.
4. Click **Promote to Staging** — patches are applied to staging-servers.
5. After testing, click **Promote to Production**.

### Viewing Pipeline Runs

Click a pipeline → **History** tab:
- Each run shows status per stage
- Timestamps for each promotion
- Which user approved each promotion
- Per-minion patch results

---

## Patch Schedules

Patch schedules automate recurring patching operations.

### Creating a Schedule

1. Go to **Schedules** in the sidebar.
2. Click **New Schedule**.
3. Configure:

```
Name:              Weekly Security Patches
Cron:              0 2 * * 0        (Sundays at 2am)
Target Groups:     [dev-servers, staging-servers]
Require Approval:  true
```

4. Click **Save**.

When the schedule fires:
- If **Require Approval** is false: patches are applied automatically.
- If **Require Approval** is true: the run is queued as **Pending Approval** and a notification is sent.

### Schedule Notifications

After a scheduled patch run completes, DokOps can automatically notify your team with a per-minion summary (patches applied, success/fail count, reboot status).

Enable notifications when creating or editing a schedule:

| Field | Description |
|-------|-------------|
| **Notification Types** | `slack`, `teams`, and/or `jira` — select one or more |
| **Slack Webhook URL** | Incoming webhook URL |
| **Teams Webhook URL** | Teams channel webhook URL |
| **Jira Project / Labels** | Project key and optional labels for the Jira ticket |
| **AI Beautify** | Check to have the AI rewrite the raw patch output into a human-readable summary before sending |

The raw notification message follows this structure:
```
Patch run completed for schedule "Weekly Security Patches"
Stage: prod-servers

nginx: 1.24.0 → 1.25.3  ✓
openssl: 3.0.2 → 3.0.9  ✓
curl: failed (exit 1)

Reboot: requested, pending
```

With **AI Beautify** enabled, the message is rewritten by the AI into concise prose before dispatch.

### Managing Schedules

From the Schedules page:
- **Pause** a schedule without deleting it (toggle off)
- **Edit** cron, target groups, approval settings, and notifications
- **Delete** to remove permanently

---

## Organisations and Multi-Tenancy

Organisations let you manage multiple independent fleets:

1. Go to **Organisations** in the sidebar.
2. Create an organisation (e.g., "Customer A Fleet", "Internal Servers").
3. Create groups within each organisation.
4. Pipelines and schedules are scoped to an organisation.

This is useful for MSPs managing patches for multiple clients.

---

## Example: Patch Workflow for Production

```
1. Monday: Trigger scan-all to get current compliance
   → Found 23 packages to update, 2 with Critical CVEs

2. Tuesday: Run pipeline 'Monthly Security Patches' (Stage 1: Dev)
   → Applied to 3 dev servers, all succeeded
   → Waited 24h for monitoring

3. Wednesday: Promote to Staging
   → Applied to 8 staging servers
   → One server failed: disk full → investigate and fix
   → Re-ran patch on that server → success

4. Thursday: Promote to Production (requires senior engineer approval)
   → Engineer reviews pipeline history and approves
   → Applied to 42 production servers
   → Compliance: 100% (was 61% before)
```

---

## Via API

```bash
# Get overall compliance
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patches/compliance

# Get CVE summary
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patches/by-cve

# Get patches for a specific minion
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patches/minions/{minion_id}/patches

# Apply patches to a group (God Mode required)
curl -X POST http://localhost:8000/api/v1/patches/groups/{group_id}/patches/apply \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-God-Mode: true"

# Create a pipeline
curl -X POST http://localhost:8000/api/v1/patches/organisations/{org_id}/pipelines \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Monthly Security Patches",
    "stages": [
      {"name": "dev", "group_id": "dev-grp-id", "auto_promote": true, "wait_hours": 24},
      {"name": "staging", "group_id": "staging-grp-id", "auto_promote": false},
      {"name": "production", "group_id": "prod-grp-id", "auto_promote": false}
    ]
  }'
```
