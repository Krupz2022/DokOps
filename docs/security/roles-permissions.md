# Roles & Permissions

DokOps has two user roles and a session-level God Mode toggle. Together they control what each user can see and do.

---

## User Roles

| Role | Description |
|------|-------------|
| **admin** | Full access. Can enable God Mode, manage users, view audit logs, change system settings. |
| **viewer** | Read-only access. Can use AI chat (read-only queries), browse resources, view topology. Cannot make changes. |

Roles are assigned at account creation and can be changed by admins from **Admin** → **Users**.

### What Viewers Can Do

- View Dashboard stats
- Browse all Kubernetes resources (pods, deployments, services, etc.)
- View pod logs and events
- Use AI Chat (read-only queries only — the AI will not call write tools)
- View Topology graph
- View Runbooks and Knowledge Base
- View Observability metrics
- View Minion status and job history (but not run jobs)
- View Workflow history (but not trigger runs)
- View Audit Log

### What Only Admins Can Do

- Enable/disable God Mode
- Manage users (create, delete, change roles, reset passwords)
- Configure AI provider
- Manage SSO settings
- View and configure Toolsets and CLI tools
- Register MCP servers
- Configure Observability integrations
- Connect Azure integration
- Approve/reject Minions
- Create and edit Workflows
- Create Patch Pipelines and Schedules
- Add/remove clusters

---

## God Mode

God Mode is a **session-level** toggle, separate from the role system. It must be enabled explicitly per session and resets on logout.

Only `admin` role users can enable God Mode.

See the [God Mode documentation](../features/god-mode.md) for the full list of operations that require God Mode.

---

## API-Level Enforcement

All permission checks happen at the API layer, not just the UI:

```python
# Example: scale_deployment requires admin + god_mode
@router.post("/deployments/{name}/scale")
async def scale_deployment(
    current_user: User = Depends(get_current_admin_user),  # admin only
    god_mode: bool = Depends(require_god_mode),             # god mode active
    ...
):
    ...
```

Even if someone bypasses the UI, API calls return `403 Forbidden` without the correct role and God Mode state.

---

## First Admin Account

The first admin is created either:

1. **Via the Setup Wizard** — on first visit to DokOps.
2. **Via environment variables** — `DOKOPS_ADMIN_USERNAME` + `DOKOPS_ADMIN_PASSWORD` (inserted on startup if no users exist).

Only one account is created this way. Additional admins are created through the UI (**Admin** → **Users** → **Create User**).

---

## Self-Registration

If `DOKOPS_SIGNUP_ENABLED=true`, anyone can register at `/register`. New self-registered users get:

```env
DOKOPS_SIGNUP_DEFAULT_ROLE=viewer  # new signups get viewer role
```

Change to `admin` if you want self-registered users to be admins (not recommended for production).

Disable self-registration:

```env
DOKOPS_SIGNUP_ENABLED=false
```

---

## SSO Role Mapping

When using SSO, roles are mapped from identity provider claims:

```
Entra ID app role "DokOps.Admin"  → admin
Entra ID no matching role         → viewer

Google group "dokops-admins"      → admin
Google no matching group          → viewer
```

Role mapping is configured per-provider. See [Authentication](authentication.md) for details.

---

## Role Changes

When an admin changes a user's role:
- The change takes effect on the user's **next login** (existing JWT tokens remain valid until expiry).
- To force immediate effect: the user must log out and log back in.
- Or reduce `ACCESS_TOKEN_EXPIRE_MINUTES` to a short value.

---

## Example: Giving a Teammate Viewer Access

```bash
# Via API
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "teammate",
    "password": "temporary-password",
    "role": "viewer"
  }'

# User logs in and can browse but not modify anything
```

Via UI:
1. **Admin** → **Users** → **Create User**
2. Set role to `viewer`
3. Share credentials — the user can view everything but cannot make changes
