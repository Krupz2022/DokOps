# Blueprints

DokOps **Blueprints** bring Salt/Uyuni-style **declarative configuration management** to your minion fleet (Linux + Windows). Instead of running one-off commands, you declare the *desired state* of a machine — packages installed, files present, services running — and let the minion reconcile itself to that state, idempotently, reporting exactly what changed.

A blueprint is a small YAML document. A minion's effective configuration (its **compiled blueprint**) is the merge of every blueprint assigned to its org, its groups, and itself.

> Find it under **Fleet → Blueprints** in the sidebar (authoring), and on each minion's **Blueprints** tab (preview / dry-run / apply).

---

## Concepts

| Term | Meaning |
|------|---------|
| **Blueprint** | A YAML document with a flat list of `resources`. |
| **Resource** | One declared piece of desired state (a package, file, service, or command), with a unique `id`. |
| **Source** | A named text blob (e.g. an `nginx.conf`) attached to a blueprint, written to disk by a `file` resource. |
| **Assignment** | Targets a blueprint at an **org**, a **group**, or a single **minion**. |
| **Compiled blueprint** | The merged set of resources that apply to one minion (org → group → minion, later wins). |
| **Dry-run** | Evaluate the blueprint and report what *would* change — no mutations. Open to any user. |
| **Apply** | Actually reconcile the minion. Requires **God Mode** and is audit-logged. |

---

## Blueprint structure

Every blueprint is YAML with a top-level `resources:` list. Each resource has a unique `id`, a `type`, type-specific fields, and optional requisites.

```yaml
resources:
  - id: nginx-pkg          # unique within the compiled blueprint
    type: pkg              # pkg | service | file | cmd
    name: nginx
    ensure: present
```

The `id` is how resources reference each other (in `require`/`watch`) and how the merge decides what overrides what — a later assignment that defines the same `id` **replaces** the earlier one.

---

## Resource types

### `pkg` — packages

Installs or removes a package using the minion's native package manager (Linux: `apt`/`dnf`; Windows: `winget`/`choco`).

```yaml
resources:
  # ensure installed
  - id: nginx
    type: pkg
    name: nginx
    ensure: present        # present | absent | latest

  # ensure removed
  - id: telnet-gone
    type: pkg
    name: telnet
    ensure: absent

  # ensure latest available version
  - id: openssl-latest
    type: pkg
    name: openssl
    ensure: latest
```

Windows example (winget package id):

```yaml
resources:
  - id: seven-zip
    type: pkg
    name: 7zip.7zip
    ensure: present
```

| Field | Required | Values |
|-------|----------|--------|
| `name` | yes | package name (or winget/choco id on Windows) |
| `ensure` | yes | `present`, `absent`, `latest` |

### `service` — services

Reconciles a service's run state and (optionally) whether it starts on boot. Linux: `systemctl`; Windows: `Get-Service`/`Set-Service`.

```yaml
resources:
  - id: nginx-running
    type: service
    name: nginx
    ensure: running        # running | stopped
    enabled: true          # optional: start on boot
```

```yaml
resources:
  - id: telnetd-off
    type: service
    name: telnet.socket
    ensure: stopped
    enabled: false
```

| Field | Required | Values |
|-------|----------|--------|
| `name` | yes | service unit / Windows service name |
| `ensure` | yes | `running`, `stopped` |
| `enabled` | no | `true` / `false` (omit to leave boot state untouched) |

### `file` — managed files

Writes file content from a **source** (a named blob attached to the blueprint). Content is compared first and only written if it differs (so it reports real changes).

```yaml
resources:
  - id: nginx-conf
    type: file
    path: /etc/nginx/nginx.conf
    source: nginx.conf       # name of an attached source (see "Sources")
    mode: "0644"             # Linux only; ignored on Windows
```

| Field | Required | Notes |
|-------|----------|-------|
| `path` | yes | absolute path on the minion |
| `source` | yes | name of a source attached to this blueprint |
| `mode` | no | octal string, Linux only |

You attach the actual file content under the blueprint's **Sources** section (UI) or a sibling `files/` directory (seeding) — see [Sources](#sources).

### `cmd` — commands (escape hatch)

Runs an arbitrary command. Make it idempotent with a guard: `unless` (skip if the probe **succeeds**) or `onlyif` (run only if the probe **succeeds**).

```yaml
resources:
  # only create the marker if it doesn't already exist
  - id: init-marker
    type: cmd
    name: touch /var/lib/myapp/initialized
    unless: test -f /var/lib/myapp/initialized

  # only run the migration when the app is present
  - id: db-migrate
    type: cmd
    name: /opt/myapp/bin/migrate
    onlyif: test -x /opt/myapp/bin/migrate
```

| Field | Required | Notes |
|-------|----------|-------|
| `name` | yes | the command to run |
| `unless` | no | probe command; if it exits 0, the resource is **skipped** (already satisfied) |
| `onlyif` | no | probe command; the main command runs only if it exits 0 |

> Reach for typed resources (`pkg`/`service`/`file`) first — they report precise changes. Use `cmd` only when nothing else fits.

---

## Requisites: ordering and reactions

Two requisites control order and reactions. Both reference other resources by their `id`.

- **`require`** — run after the listed resources; if a required resource **failed**, this one is skipped.
- **`watch`** — run after the listed resources, **and** react if any of them reported changes. For a `service`, "react" means **restart**.

```yaml
resources:
  - id: nginx-pkg
    type: pkg
    name: nginx
    ensure: present

  - id: nginx-conf
    type: file
    path: /etc/nginx/nginx.conf
    source: nginx.conf

  - id: nginx-svc
    type: service
    name: nginx
    ensure: running
    enabled: true
    require: [nginx-pkg]     # don't start the service unless the package installed
    watch:   [nginx-conf]    # restart nginx whenever the config changes
```

Resources run in dependency order regardless of how they're listed in the file. A cycle, or a `require`/`watch` pointing at an unknown id, is reported as an error.

---

## Sources

A `file` resource's `source` is a **named text blob** stored with the blueprint (not a path on the DokOps server). On apply, the content is shipped to the minion and written to the resource's `path`.

- **In the UI:** open a blueprint → **Sources** → add a source named e.g. `nginx.conf` and paste its content.
- **When seeding from disk:** put the file in a sibling `files/` directory (see [Seeding](#seeding-from-disk)).

```yaml
# blueprint
resources:
  - id: nginx-conf
    type: file
    path: /etc/nginx/nginx.conf
    source: nginx.conf      # ← resolves to the source named "nginx.conf"
```

```nginx
# source "nginx.conf"
worker_processes auto;
events { worker_connections 1024; }
http {
  server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
  }
}
```

### Binary sources

Sources can be **binary** (zips, archives, any file), not just text. In the UI, use **Upload file** in a blueprint's Sources; when seeding, just drop the file in the scope's `files/` folder — a non-text file is auto-detected and stored as binary. A `file` resource references it the same way:

```yaml
resources:
  - id: bundle
    type: file
    path: /opt/ansible-bundle.zip
    source: ansible-bundle.zip      # raw binary, shipped intact
```

Binary sources ≤ 1 MB ship inline with the run; larger ones are downloaded by the agent from DokOps on demand (integrity-checked by sha256). Max source size is 50 MB. This only *ships* the file — extracting an archive is still a `cmd` step (e.g. `unzip`/`tar`).

---

## Assignments & multi-tenancy

A blueprint does nothing until it's **assigned**. Assign it at one of four scopes:

| Scope | Targets |
|-------|---------|
| `global` | **every** minion in the fleet (the shared base layer) |
| `org` | every minion in the organisation |
| `group` | every minion in that group |
| `minion` | one specific minion |

A minion's **compiled blueprint** merges everything assigned at `global`, then its org, then its groups, then itself — **later wins by `id`**. `global` is the bottom layer: a resource you put there applies everywhere, and any org/group/minion assignment with the same `id` overrides it. This is how you keep one common base and override per-tenant.

### Worked multi-tenant example

Map **customer → org**, **branch → group**, **box → minion**. Give every customer a shared base, and let a branch override just the file that differs:

```yaml
# assigned at org "acme" — the common config
resources:
  - id: nginx-pkg
    type: pkg
    name: nginx
    ensure: present
  - id: nginx-conf
    type: file
    path: /etc/nginx/nginx.conf
    source: nginx.conf        # acme's default
  - id: nginx-svc
    type: service
    name: nginx
    ensure: running
    require: [nginx-pkg]
    watch: [nginx-conf]
```

```yaml
# assigned at group "acme / branch-mumbai" — overrides ONLY the config
resources:
  - id: nginx-conf            # same id ⇒ replaces acme's version for this branch
    type: file
    path: /etc/nginx/nginx.conf
    source: nginx.conf        # mumbai's own content
```

A Mumbai minion's compiled blueprint = `nginx-pkg` + `nginx-svc` (from acme) + `nginx-conf` (from Mumbai). No per-customer code — the hierarchy does the segregation.

---

## Running a blueprint

Open a minion → **Blueprints** tab.

1. **Preview** shows the compiled resources and bundled sources for that minion.
2. **Dry-run** evaluates everything and shows a per-resource diff — *what would change* — without touching the machine. Open to any signed-in user.
3. **Apply** reconciles the minion for real. The button is disabled unless **God Mode** is active; applying prompts for confirmation and writes an audit-log entry.
4. **Run history** lists past runs (dry-run / apply, status, time, actor); click one to see its results.

### Result semantics

Each resource returns a tri-state result:

| Result | Meaning | UI |
|--------|---------|----|
| `true` | success — applied, or already in the desired state | green ("ok" / "changed") |
| `null` | dry-run: this resource **would** change | amber ("would change") |
| `false` | failed, or skipped because a `require` failed | red ("failed") |

Each result also carries `changes` (old → new) and a `comment`.

---

## Authoring

1. **Fleet → Blueprints** → **New blueprint**.
2. Give it a name and write the `resources:` YAML.
3. **Save**, then add any **Sources** the `file` resources reference.
4. Add **Assignments** (org / group / minion).
5. Go to a target minion's **Blueprints** tab → **Dry-run** → review → **Apply** (God Mode).

The authoring page is superuser-only. Reading a compiled blueprint and dry-running are open to any signed-in user; applying requires God Mode.

---

## Seeding from disk

Blueprints can be defined as files and loaded into the database on startup — useful for GitOps-style authoring or shipping defaults. On boot, DokOps imports everything under `backend/app/blueprints/`, where the **path encodes the scope**:

```
backend/app/blueprints/
  common/<name>.yaml                  + files/<source>     → assigned to ALL minions (base layer)
  orgs/<org>/<name>.yaml              + files/<source>     → assigned to that org
  groups/<org>/<group>/<name>.yaml    + files/<source>     → assigned to that group
  minions/<minion-id>/<name>.yaml     + files/<source>     → assigned to that minion
```

Example:

```
backend/app/blueprints/
  common/baseline.yaml
  common/files/ansible-bundle.zip
  orgs/acme/web.yaml
  orgs/acme/files/nginx.conf
  groups/acme/branch-mumbai/web.yaml
  groups/acme/branch-mumbai/files/nginx.conf
```

Seeding is idempotent (re-running updates by name, never duplicates). Unknown org/group names are skipped and logged — DokOps never auto-creates them. A seed failure logs a warning and never blocks startup.

---

## API reference

All paths are under `/api/v1`. Reads require a signed-in user; blueprint writes require superuser; **apply requires God Mode**.

```
# Authoring
GET    /blueprints                          # list blueprints
POST   /blueprints                          # create  {name, yaml_body}
GET    /blueprints/{id}                      # get one
PUT    /blueprints/{id}                       # update {name, yaml_body}
DELETE /blueprints/{id}                       # delete (cascades sources + assignments)

GET    /blueprints/{id}/sources               # list sources
PUT    /blueprints/{id}/sources/{name}        # upsert a source {content}

GET    /blueprints/{id}/assignments           # list assignments
POST   /blueprints/{id}/assignments           # add    {scope_type, scope_id}
DELETE /blueprints/assignments/{id}           # remove

# Running (per minion)
GET    /minions/{id}/blueprint                # compiled preview {resources, sources}
POST   /minions/{id}/blueprint/run            # {test: true|false} -> {run_id, test}
GET    /minions/{id}/blueprint/runs           # run history
GET    /minions/blueprint/runs/{run_id}        # one run + its results
```

`POST .../blueprint/run` is synchronous: it dispatches to the minion and, by the time it returns `{run_id}`, the results are stored — fetch them with `GET /minions/blueprint/runs/{run_id}`. `test: false` (apply) requires God Mode and returns `403` otherwise.

Example — dry-run via curl:

```bash
# preview what would change on a minion (no mutations)
RUN=$(curl -s -X POST "$DOKOPS/api/v1/minions/web-01/blueprint/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"test": true}' | jq -r .run_id)

curl -s "$DOKOPS/api/v1/minions/blueprint/runs/$RUN" \
  -H "Authorization: Bearer $TOKEN" | jq '.results'
```

---

## Full example

A complete web-server blueprint — package, managed config, running service that restarts on config change, plus a one-time guard command:

```yaml
resources:
  - id: nginx-pkg
    type: pkg
    name: nginx
    ensure: present

  - id: nginx-conf
    type: file
    path: /etc/nginx/nginx.conf
    source: nginx.conf
    mode: "0644"

  - id: index-page
    type: file
    path: /usr/share/nginx/html/index.html
    source: index.html

  - id: nginx-svc
    type: service
    name: nginx
    ensure: running
    enabled: true
    require: [nginx-pkg]
    watch:   [nginx-conf]

  - id: firewall-open-80
    type: cmd
    name: ufw allow 80/tcp
    unless: ufw status | grep -q '80/tcp'
```

Attach two sources to this blueprint — `nginx.conf` and `index.html` — assign it (org/group/minion), then dry-run and apply from the minion's Blueprints tab.

---

## Limits (v1)

Not yet supported — planned for later phases:

- Templating / per-scope variables (every blueprint ships whole files)
- Extra requisites (`onchanges`, `onfail`, `prereq`)
- Scheduled auto-apply / drift enforcement
- Git-repo sync (beyond the startup seed)
- Windows registry resources
- Source deletion

---

## Activation keys (bootstrap on onboard)

Create an **activation key** under **Fleet → Keys**: give it a name, optionally a target group, attach a set of blueprints, and toggle **Run on attach**. Creating it shows a one-time **key value** plus an install command.

Install a machine with that key — enrollment auth is still `-Token`; `-Key` is a separate provisioning selector:

```powershell
... install.ps1 ... -Token '<enrollment key>' -Key '<activation key value>'
```

On first enrollment with `-Key`, the minion joins the key's group and — if **Run on attach** is enabled — applies the key's blueprints **once** (visible in the minion's blueprint run history, streamed live). Reconnects don't re-run it (guarded by a per-minion `bootstrapped` flag). A machine onboarded **without** `-Key` gets nothing extra.

> `-Key` is *not* an auth credential — a missing or wrong `-Key` never affects enrollment, it just means no bootstrap. Auto-apply on enroll is authorized by an admin having created the key, attached blueprints, and enabled run-on-attach; each bootstrap is audit-logged as `enroll:<key>`.

---

## Related

- [Minions (Remote Agents)](minions.md) — the agent fleet blueprints run on
- [Patch Management](patching.md) — compliance, pipelines, schedules for the same fleet
- [God Mode](god-mode.md) — required to apply blueprints
- [Roles & Permissions](../security/roles-permissions.md)
