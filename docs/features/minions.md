# Minions (Remote Agent Fleet)

Minions are lightweight Python agents that you deploy on bare-metal servers, VMs, or any machine outside Kubernetes. They connect back to DokOps over WebSocket and let you:

- Run shell commands remotely from the DokOps UI
- Track patch compliance (outdated packages) — Linux and **Windows**
- Execute bulk operations across a fleet
- Automatically discover and monitor middleware services (RabbitMQ, Redis, PostgreSQL, etc.)
- Run named diagnostic probes against those services using credentials from the secure credential store

---

## Deploying a Minion Agent

### Prerequisites
- **Linux:** Python 3.8+ on the target machine
- **Windows:** Python 3.8+ and PowerShell 5.1+
- Network access to the DokOps backend (outbound only — no inbound ports needed on the server)

### Install — Linux

Run the one-liner installer on the target machine. It detects your Python version, installs dependencies, downloads the agent, and registers it as a systemd service automatically:

```bash
curl http://YOUR-DOKOPS-URL:8000/minion/install.sh | bash -s -- \
  --url=http://YOUR-DOKOPS-URL:8000 \
  --token=YOUR_MINION_TOKEN
```

**Optional flags:**

| Flag | Description |
|------|-------------|
| `--url=` | DokOps backend URL (defaults to `http://localhost:8000`) |
| `--token=` | Minion auth token (generated in the DokOps UI — see [Registering a Minion](#registering-a-minion)) |
| `--org=` | Organisation name to auto-assign this minion to |
| `--env=` | Environment label (e.g., `prod`, `staging`) |

**What the installer does:**
1. Detects the best available Python 3.8+ binary
2. Installs `websockets` and `psutil` via pip
3. Downloads the agent to `/usr/local/bin/dokops-minion-agent.py`
4. Writes config to `/etc/dokops-minion/config.env`
5. Creates and enables `/etc/systemd/system/dokops-minion.service`
6. Starts the service immediately

Check the service status after install:

```bash
systemctl status dokops-minion
journalctl -u dokops-minion -f
```

### Install — Windows

Run the PowerShell installer from an elevated prompt:

```powershell
Invoke-WebRequest http://YOUR-DOKOPS-URL:8000/minion/install.ps1 -OutFile install.ps1
.\install.ps1 -Url http://YOUR-DOKOPS-URL:8000 -Token YOUR_MINION_TOKEN
```

**What the installer does:**
1. Downloads the agent to `C:\Program Files\DokOps\minion-agent.py`
2. Installs `websockets` and `psutil` via pip (can proxy through DokOps if PyPI is blocked — see [PyPI Proxy](#pypi-proxy-for-airgapped-windows))
3. Creates and starts a Windows Service (`DokOpsMinion`)
4. Writes config to `C:\ProgramData\DokOps\config.env`

Check the service:

```powershell
Get-Service DokOpsMinion
```

### Uninstall

**Linux:**
```bash
curl http://YOUR-DOKOPS-URL:8000/minion/uninstall.sh | bash
```

**Windows (elevated prompt):**
```powershell
Invoke-WebRequest http://YOUR-DOKOPS-URL:8000/minion/uninstall.ps1 -OutFile uninstall.ps1
.\uninstall.ps1
```

Both scripts stop and remove the service, the agent binary, and the config directory.

### PyPI Proxy for Air-Gapped Windows

If the Windows machine cannot reach PyPI directly, DokOps can act as a pip proxy:

```powershell
pip install websockets psutil `
  --index-url http://YOUR-DOKOPS-URL:8000/minion/simple/ `
  --trusted-host YOUR-DOKOPS-URL
```

DokOps proxies only `pypi.org` and `files.pythonhosted.org` — no other URLs are allowed.

---

## Registering a Minion

When the minion agent starts, it connects to DokOps and registers itself. The new minion appears in **Minions** with status **Pending** until an admin approves it.

1. Go to **Minions** in the sidebar.
2. Find the pending minion (identified by hostname).
3. Click **Approve** — the minion moves to **Active** status.
4. You can now send jobs to it.

> Unapproved minions cannot receive jobs. This prevents rogue agents from joining your fleet.

---

## Minion Status

| Status | Meaning |
|--------|---------|
| **Pending** | Registered but not yet approved by an admin |
| **Active** | Approved and connected |
| **Offline** | Last seen > 5 minutes ago (heartbeat missed) |

---

## Running Commands

### Single Minion

1. Go to **Minions** → click a minion name to open the detail page.
2. Click **Run Command**.
3. Type a shell command (e.g., `df -h`, `systemctl status nginx`).
4. Click **Execute** — output streams back in real time.

### Bulk Run (Multiple Minions)

1. Go to **Minions** → click **Bulk Run**.
2. Select the minions to target (individually or by group).
3. Enter the command.
4. Click **Execute on All** — each minion runs the command and streams results.

Results are shown per-minion with exit code, stdout, and stderr.

---

## Minion Detail Page

Click any minion to see:

**Overview**
- Hostname, IP address, OS
- Status, last seen, approved by, approval date
- Hardware grains: CPU model, RAM, disk, kernel version

**Job History**
- All commands run on this minion
- Status (pending/running/done/failed), exit code, actor
- Click any job to see full stdout/stderr output

**Patch Compliance**
- List of installed packages with their current version
- Latest available version
- CVE identifiers for packages with known vulnerabilities

**Discovered Services**
- Middleware services auto-detected on this minion (see [Service Discovery](#service-discovery))
- Service type, install type (native/Docker), port, container name
- Run diagnostic probes directly from this tab

---

## Patch Scanning

### Scan a Single Minion

1. Click the minion → click **Scan Patches**.
2. On Linux, the minion runs `apt list --upgradable` (Debian/Ubuntu) or `yum check-update` (RHEL/CentOS).
3. On Windows, the minion queries the **Windows Update Agent (WUA)** COM API to list pending updates with severity and bulletin IDs.

### Scan All Minions

From the Minions list, click **Scan All** — this triggers a patch scan on every active minion simultaneously.

### API

```bash
# Scan all minions
curl -X POST http://localhost:8000/api/v1/minions/patches/scan-all \
  -H "Authorization: Bearer $TOKEN"

# Scan one minion
curl -X POST http://localhost:8000/api/v1/minions/{id}/patches/scan \
  -H "Authorization: Bearer $TOKEN"
```

---

## Service Discovery

When a minion connects (or when you trigger a manual discovery), DokOps sends the minion a `discover_services` command. The minion runs three detection methods in parallel:

| Method | Command | Detects |
|--------|---------|---------|
| Port scan | `ss -tlnp` | Any listening service by port number |
| Systemd units | `systemctl list-units --state=running` | Named system services |
| Docker containers | `docker ps --format '{{json .}}'` | Containerized services (wins over native if same type) |

**Supported service types:** RabbitMQ, Redis, PostgreSQL, MySQL, MongoDB, Elasticsearch, Kafka, and more — mapped by well-known port numbers and unit names.

### Viewing Discovered Services

Open any minion's detail page → click the **Services** tab. Each row shows:
- Service type (e.g., `rabbitmq`)
- Install type (`native` or `docker`)
- Port and, for Docker, container name

### Manual Override

If a service is not auto-detected (non-standard port, unusual unit name), you can add it manually:

1. Click **Add Service** on the minion detail page.
2. Select service type, install type, and port.
3. Click **Save**.

Manual overrides can be deleted; auto-detected entries are refreshed on the next discovery sweep.

### API

```bash
# List services for a minion
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/{minion_id}/services

# Trigger a discovery sweep
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/minions/{minion_id}/services/discover

# Add a manual override
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"service_type":"rabbitmq","install_type":"native","port":5672}' \
  http://localhost:8000/api/v1/minions/{minion_id}/services
```

---

## Middleware Diagnostic Probes

Once a service is discovered, DokOps can run named diagnostic probes against it. Credentials are resolved automatically from the [Service Credential Store](#service-credential-store).

### Running a Probe

From the minion detail **Services** tab, click the **probe** button next to any service to choose and run a probe. Results stream back in real time.

You can also run probes from the AI chat: "Run a RabbitMQ queue depth probe on server-01". The AI calls the `run_service_probe` tool, which resolves credentials and dispatches the probe transparently.

### API

```bash
# Run a probe (dispatched via the minion command channel)
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command":"__probe__:rabbitmq:queue_depth"}' \
  http://localhost:8000/api/v1/minions/{minion_id}/run
```

---

## Service Credential Store

Credentials for middleware services (RabbitMQ, Redis, PostgreSQL, etc.) are stored encrypted and resolved automatically during probe execution and AI tool calls.

### Adding Credentials

1. Go to **Settings** → **Service Credentials**.
2. Click **Add Credential**.
3. Configure:

| Field | Description |
|-------|-------------|
| **Scope** | Apply to all minions (`global`), a group, or a specific minion |
| **Service Type** | `rabbitmq`, `redis`, `postgresql`, etc. |
| **Username** | Service username (optional for Redis) |
| **Password** | Stored with Fernet encryption |
| **Port** | Override the default port |

4. Click **Save**.

When a probe or AI tool runs, DokOps looks up the most specific credential in order: minion → group → global. Username is masked in the UI (`a***`); the password is never exposed.

### Credential Scoping

- **Global** — applies to all minions that have no more specific credential
- **Group** — applies to all minions in that group
- **Minion** — applies only to that specific minion

---

## Groups and Organisations

Minions can be organized into **Groups** within **Organisations** for multi-tenant patch management:

1. Go to **Organisations** in the sidebar.
2. Create an organisation (e.g., "Web Servers", "Database Fleet").
3. Create groups within the organisation (e.g., "Prod", "Staging").
4. Assign minions to groups.

Groups are used by the [Patch Pipeline](patching.md) feature to control which servers receive patches at each stage.

---

## Security

- The minion agent connects **outbound** to DokOps — no inbound ports need to be open on the server.
- **WebSocket authentication is mandatory.** The agent must present a valid token when opening the WebSocket connection; connections without a token or with an invalid token are rejected before the session is established.
- The token is a random secret generated per-minion. It is hashed (bcrypt) before storage — never stored in plaintext.
- All new minions start in **Pending** status. An admin must approve them before they can receive jobs.
- **Command allowlist:** Read-only commands (`df -h`, `systemctl status`, etc.) can be run in Normal Mode. Any command not on the safe allowlist requires God Mode — the UI enforces this before dispatching.
- God Mode is required for bulk destructive operations and arbitrary shell commands.
- All commands run under the user account that started the agent — scope that account's permissions appropriately.
- Middleware credentials are stored encrypted (Fernet) and are never logged or returned in plaintext via the API.

---

## Example: Roll Out a Config Change to All Web Servers

```bash
# Via AI Chat
User: "Update /etc/nginx/nginx.conf on all web-servers group minions
       to increase worker_connections to 4096"

AI: This requires God Mode and will run on 12 minions in the
    'web-servers' group. Do you want to proceed?

    [Action Card] Bulk Run on 12 minions:
    Command: sed -i 's/worker_connections 1024/worker_connections 4096/' /etc/nginx/nginx.conf && nginx -t && systemctl reload nginx

    [Requires God Mode approval]
```

Or directly via the UI:

1. Go to **Minions** → **Bulk Run**.
2. Filter by group: `web-servers`.
3. Enter: `sed -i 's/worker_connections 1024/worker_connections 4096/' /etc/nginx/nginx.conf && nginx -t && systemctl reload nginx`
4. Click **Execute** — results stream per-server.

---

## Blueprints

DokOps minions support declarative **blueprints** (similar to Salt/Uyuni states). A blueprint is YAML that describes desired system resources:

```yaml
resources:
  - id: nginx-pkg
    type: pkg          # pkg | service | file | cmd
    name: nginx
    ensure: present
  - id: nginx-svc
    type: service
    name: nginx
    ensure: running
    require: [nginx-pkg]
```

A minion's **blueprint** is the merge of all blueprints assigned to its organisation, its groups, and itself. Later, more-specific definitions win by `id`.

- **Dry-run** (`POST /api/v1/minions/{id}/blueprint/run` with `{"test": true}`) shows what *would* change — open to any user.
- **Apply** (`{"test": false}`) reconciles the minion and requires **God Mode**; it is audit-logged.

Blueprints live in the DB (UI editor / REST), and can be seeded from `backend/app/blueprints/{orgs,groups,minions}/...` on startup.
