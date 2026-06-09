# Container Registry Lookup

When an AI agent encounters an `ImagePullBackOff` error, it can independently search public and private container registries to verify image names, tags, and availability — without a general web search. This keeps the agent's tool access scoped and auditable.

---

## How It Works

The `RegistryService` queries registries using the [OCI Distribution Spec](https://github.com/opencontainers/distribution-spec) API. It checks:

1. **Built-in public registries** — always available when the feature is enabled:
   - Docker Hub (`hub.docker.com`)
   - GitHub Container Registry (`ghcr.io`)
   - Quay.io (`quay.io`)
   - Kubernetes registry (`registry.k8s.io`)

2. **User-configured private registries** — any OCI-compatible private registry you add (Azure Container Registry, AWS ECR, GCR, Harbor, Nexus, etc.)

The agent calls `search_container_image` with a query string (e.g. `nginx:1.27` or `mycompany/api-service`) and gets back a list of matching images with available tags.

---

## Enabling Registry Lookup

1. Go to **Settings**.
2. Find the **Registry Lookup** card.
3. Toggle **Enable Registry Lookup** on.

When disabled, calling `search_container_image` returns a clear error message — the tool is never silently ignored.

---

## Adding Private Registries

1. Go to **Integrations → Container Registries**.
2. Click **Add Registry**.
3. Fill in:

| Field | Description |
|-------|-------------|
| **Name** | Display name (e.g. "Production ACR") |
| **URL** | Registry hostname (e.g. `mycompany.azurecr.io`) |
| **Username** | Registry username (optional for public registries) |
| **Password / Token** | Registry password or access token (stored Fernet-encrypted) |

4. Click **Save**.

Credentials are Fernet-encrypted at rest. The username is masked in the UI (`a***`).

---

## Agent Tools

Two read-only tools are added to the agent tool catalog when registry lookup is enabled:

### `search_container_image`

Searches all configured registries for an image name or image:tag reference.

**Input:**
```json
{"query": "nginx:1.25"}
```

**Output:**
```json
{
  "results": [
    {
      "registry": "Docker Hub",
      "image": "library/nginx",
      "tags": ["1.25.0", "1.25.1", "1.25.2", "1.25.3"],
      "latest_tag": "1.25.3"
    }
  ]
}
```

If the exact tag is not found but similar tags exist, the agent can suggest the nearest available version.

### `fetch_url`

Fetches a URL from a hard-coded allowlist of trusted documentation and release-note sources (registry API endpoints, official Kubernetes docs). This is intentionally narrow — it is not a general web search tool.

---

## Example: ImagePullBackOff Diagnosis

When the AI detects `ImagePullBackOff`:

```
AI: The pod is failing to pull image "mycompany.azurecr.io/api-service:v2.1.4".
    Let me check if this image exists...

[tool call: search_container_image {"query": "api-service:v2.1.4"}]

Result: Image not found in mycompany.azurecr.io.
        Available tags: v2.1.0, v2.1.1, v2.1.2, v2.1.3

AI: The image tag v2.1.4 does not exist in your ACR. The latest available tag is v2.1.3.
    Either the build pipeline has not pushed this tag yet, or there was a typo in the deployment manifest.
    Recommendation: check your CI pipeline or update the image tag to v2.1.3.
```

---

## Via API

```bash
# List configured registries
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/registries

# Add a private registry
curl -X POST http://localhost:8000/api/v1/registries \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Production ACR",
    "url": "mycompany.azurecr.io",
    "username": "service-principal-id",
    "password": "service-principal-secret"
  }'

# Get/set the registry_lookup_enabled setting
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/registries/settings

curl -X PUT http://localhost:8000/api/v1/registries/settings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"registry_lookup_enabled": true}'
```
