# Authentication

DokOps supports two authentication methods: **local JWT login** (username/password) and **SSO/OAuth2** (Entra ID, Google Workspace, Authentik, AWS Cognito).

---

## Local Login

### Default Flow

1. Navigate to `http://localhost:3000`.
2. Enter username and password.
3. DokOps returns a JWT access token (8-day expiry by default).
4. The token is stored in browser localStorage and sent as `Authorization: Bearer <token>` on all API calls.

### Token Expiry

```env
ACCESS_TOKEN_EXPIRE_MINUTES=11520  # 8 days (default)
```

Change to a shorter value in production for tighter security:

```env
ACCESS_TOKEN_EXPIRE_MINUTES=480    # 8 hours
```

### Change Password

Logged-in users can change their password:
1. Click the profile icon → **Settings**.
2. Enter current password and new password.
3. Click **Save**.

Admins can reset any user's password from **Admin** → **Users**.

---

## SSO / OAuth2

DokOps supports four OAuth2/OIDC providers. All use the Authorization Code flow with PKCE-equivalent CSRF protection.

### General SSO Settings

```env
SSO_ENABLED=true              # Enable SSO login buttons on the login page
SSO_AUTO_PROVISION=true       # Auto-create DokOps accounts for new SSO users
SSO_ALLOWED_DOMAINS=          # Comma-separated allowed email domains (empty = all)
FRONTEND_URL=https://dokops.example.com
BACKEND_PUBLIC_URL=https://dokops.example.com
```

### Entra ID (Azure AD)

1. In Azure Portal: App registrations → New registration.
2. Set redirect URI: `https://dokops.example.com/api/v1/auth/sso/entra/callback`
3. Create a client secret.
4. Configure DokOps:

```env
ENTRA_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
ENTRA_CLIENT_SECRET=your-client-secret
ENTRA_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
ENTRA_ROLES_CLAIM=roles             # JWT claim containing user roles
ENTRA_ADMIN_ROLE=DokOps.Admin       # Value in roles claim that maps to admin
```

Users with the `DokOps.Admin` app role in Entra ID get the `admin` role in DokOps. All others get `viewer`.

### Google Workspace

1. In Google Cloud Console: Create OAuth2 client (Web application).
2. Set redirect URI: `https://dokops.example.com/api/v1/auth/sso/google/callback`
3. Configure DokOps:

```env
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
GOOGLE_ALLOWED_DOMAIN=example.com           # Restrict to your domain
GOOGLE_ADMIN_GROUP=dokops-admins@example.com  # Group for admin role
GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/sa.json  # For group membership lookup
```

### Authentik

1. In Authentik: Create OAuth2/OIDC Provider.
2. Set redirect URI: `https://dokops.example.com/api/v1/auth/sso/authentik/callback`
3. Configure DokOps:

```env
AUTHENTIK_CLIENT_ID=your-client-id
AUTHENTIK_CLIENT_SECRET=your-client-secret
AUTHENTIK_BASE_URL=https://authentik.example.com
AUTHENTIK_ROLES_CLAIM=groups
AUTHENTIK_ADMIN_ROLE=dokops-admins
```

### AWS Cognito

1. In AWS Console: Create User Pool app client.
2. Set callback URL: `https://dokops.example.com/api/v1/auth/sso/cognito/callback`
3. Configure DokOps:

```env
COGNITO_CLIENT_ID=your-client-id
COGNITO_CLIENT_SECRET=your-client-secret
COGNITO_USER_POOL_ID=us-east-1_xxxxxxxx
COGNITO_REGION=us-east-1
COGNITO_ROLES_CLAIM=custom:roles
COGNITO_ADMIN_ROLE=dokops-admins
```

---

## SSO Login Flow

1. User visits `http://dokops.example.com`.
2. Login page shows SSO provider buttons (e.g., "Sign in with Microsoft").
3. User clicks → redirected to identity provider.
4. After authentication, provider redirects back to DokOps callback URL.
5. DokOps:
   - Validates the authorization code and fetches tokens from the provider.
   - Extracts user info (email, name) and role claims.
   - If `SSO_AUTO_PROVISION=true` and the user doesn't exist: creates a new DokOps account.
   - If the user exists: updates their profile.
   - Issues a DokOps JWT and redirects to the dashboard.

---

## Auto-Provisioning

When `SSO_AUTO_PROVISION=true`, DokOps creates user accounts automatically on first SSO login. The user's role is determined by their claims:

- User has admin claim → `admin` role
- User doesn't have admin claim → `viewer` role (read-only)

With `SSO_ALLOWED_DOMAINS=example.com`, only users with `@example.com` email addresses are allowed in.

---

## Disabling Local Login

If you want SSO-only login (no username/password form):

```env
DOKOPS_SIGNUP_ENABLED=false
```

This hides the registration form. Ensure at least one admin account exists before setting this.

---

## API Authentication

All API endpoints (except `/api/v1/auth/login` and `/api/v1/auth/register`) require authentication. DokOps accepts the token via two mechanisms — it checks them in this order:

1. **httpOnly Cookie** — `access_token` cookie set by the SSO callback flow. This is the preferred method for browser-based access because the cookie is inaccessible to JavaScript.
2. **Authorization Header** — `Authorization: Bearer <token>` for API clients and scripts.

If neither is present the request is rejected with HTTP 401.

### Getting a Token (Username/Password)

```bash
curl -X POST http://localhost:8000/api/v1/auth/login/access-token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=yourpassword"

# Response
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer"
}
```

Store the token and use it for subsequent requests:

```bash
TOKEN=$(curl -s -X POST ... | jq -r .access_token)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/dashboard/stats
```

### Minion WebSocket Authentication

Minion agents authenticate using a token passed as a query parameter when opening the WebSocket connection:

```
ws://dokops.internal:8000/api/v1/minions/ws/{minion_id}?token=YOUR_TOKEN
```

The server validates the token before the WebSocket handshake completes. Connections without a token, or with an invalid/expired token, are closed immediately with code `1008 (Policy Violation)`. This prevents unauthenticated agents from registering in your fleet.

The token is validated against:
1. The global auto-accept key (configured in Settings → Minions)
2. The minion's own stored token hash (set during registration)
