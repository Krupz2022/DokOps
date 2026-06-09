# User Management

DokOps user management lives under **Admin** → **Users** (admin-only).

---

## Creating a User

### Via UI

1. Click **Admin** in the sidebar.
2. Click the **Users** tab.
3. Click **Create User**.
4. Fill in:
   - **Username** — must be unique
   - **Password** — minimum 8 characters
   - **Role** — `admin` or `viewer`
5. Click **Save**.
6. Share the credentials with the new user. They should change the password immediately.

### Via API

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "alice",
    "password": "temporarypassword",
    "role": "viewer"
  }'
```

---

## Viewing Users

**Admin** → **Users** shows all users with:
- Username
- Role (admin/viewer)
- Account type (local or SSO provider)
- Last login timestamp
- Status (active/inactive)

---

## Changing a User's Role

1. Click the user's row in the Users table.
2. Change the **Role** dropdown.
3. Click **Save**.

The change takes effect on the user's next login (their existing JWT remains valid until expiry).

---

## Resetting a Password

1. Click the user's row → click **Reset Password**.
2. Enter and confirm the new password.
3. Click **Save**.

The user's existing tokens are **not** invalidated — they remain valid until natural expiry. If you need immediate logout, reduce `ACCESS_TOKEN_EXPIRE_MINUTES` temporarily.

---

## Deleting a User

1. Click the user's row → click **Delete**.
2. Confirm the deletion.

Deleted users' audit log entries are preserved (audit logs are immutable).

---

## SSO Users

Users who log in via SSO (Entra ID, Google, etc.) have their account automatically created on first login when `SSO_AUTO_PROVISION=true`.

SSO user accounts show:
- **Provider** — the SSO provider (entra, google, authentik, cognito)
- **External ID** — the user's identifier in the provider
- **Email** — from the provider's claims

You can change an SSO user's role in DokOps regardless of their SSO claims (the DokOps role takes precedence over the claim-mapped role on next login — unless the claim mapping overrides on re-login, depending on provider config).

---

## Self-Registration

When `DOKOPS_SIGNUP_ENABLED=true`, users can register at the `/register` page. New users get the role defined by `DOKOPS_SIGNUP_DEFAULT_ROLE` (default: `viewer`).

An admin can later promote self-registered users to `admin` if needed.

To disable self-registration:

```env
DOKOPS_SIGNUP_ENABLED=false
```

---

## Profile Settings (Self-Service)

Any logged-in user can update their own profile:

1. Click the profile icon → **Settings**.
2. Change password (requires current password).
3. Toggle dark/light theme.

---

## Example: Onboarding a New SRE Team

```bash
# Create a viewer account for each SRE (they can diagnose but not change)
for name in alice bob charlie; do
  curl -X POST http://localhost:8000/api/v1/auth/register \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"username\": \"$name\", \"password\": \"Welcome1!\", \"role\": \"viewer\"}"
done

# Promote the lead SRE to admin
curl -X PATCH http://localhost:8000/api/v1/users/alice \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "admin"}'
```

Or if using SSO (Entra ID):
1. Add `alice@company.com` to the `DokOps.Admin` app role in Azure AD.
2. Alice logs in via SSO → automatically gets `admin` role.
3. Bob and Charlie have no app role → automatically get `viewer` role.
