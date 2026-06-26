# DokOps REST API Reference

Welcome! This is the complete reference for the **DokOps backend API**. It is written so that **anyone can follow it** — whether you are a seasoned developer or have never touched an API before.

> **What is an API?** (in plain terms) An API ("Application Programming Interface") is a way for one program to talk to another program over the network, instead of a human clicking buttons in a web page. DokOps has a friendly web dashboard, but everything the dashboard does, it does by sending small messages to this API. This reference documents every one of those messages so you (or your own scripts/tools) can do the same things automatically.

---

## 5-Minute Absolute-Beginner Getting Started

You only need three things to make your first API call: **the address**, **a token (your "key")**, and **a tool to send the request**.

### Step 1 — Know the address (the "base URL")

Every request goes to a base address. On a typical local install this is:

```
http://localhost:8000/api/v1
```

So an endpoint written as `GET /api/v1/k8s/namespaces` means: send a request to
`http://localhost:8000/api/v1/k8s/namespaces`.

(See the full list of environments in [`overview.md`](./overview.md#base-url).)

### Step 2 — Get a token (log in)

Almost every endpoint requires you to prove who you are with a **token** (a long random-looking string). You get one by logging in with your username and password.

**With curl** (a command-line tool installed on most computers):

```bash
curl -X POST http://localhost:8000/api/v1/login/access-token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=YOUR_PASSWORD"
```

The reply contains your token:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "username": "admin",
  "is_superuser": true,
  "role": "admin"
}
```

Copy the long `access_token` value — that is your key for the next step.

> **Tip — save it to a variable** so you don't have to paste it every time:
> ```bash
> TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/login/access-token \
>   -d "username=admin&password=YOUR_PASSWORD" \
>   | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
> ```

### Step 3 — Make your first real call

Now include the token in an `Authorization` header on any request:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/k8s/namespaces
```

You should get back a list of Kubernetes namespaces (in plain terms: the "folders" your cluster uses to separate apps). Congratulations — you've used the API!

### Prefer not to type commands? Two no-code options

**Option A — Swagger UI (built in, nothing to install).**
Open `http://localhost:8000/docs` in your browser. This is an interactive, clickable version of this whole API.
1. Click the green **Authorize** button (top right).
2. Paste your token (just the token, the page adds "Bearer" for you) and click **Authorize**.
3. Expand any endpoint, click **Try it out**, fill in the fields, and click **Execute**. You'll see the exact request and the live response.

**Option B — Postman or Insomnia (free apps).**
1. Create a new request, set the method (GET/POST/etc.) and paste the full URL.
2. Under the **Authorization** tab choose **Bearer Token** and paste your token.
3. For POST/PUT requests, put the JSON body under the **Body → raw → JSON** tab.
4. Click **Send**.

---

## How to read each endpoint page

Every endpoint in this reference is documented with the same seven parts:

1. **What this does** — one or two plain-English sentences.
2. **Method + path** — e.g. `GET /api/v1/k8s/namespaces/{namespace}/pods`.
3. **Auth required?** — whether you need a token, and whether you need extra powers (see below).
4. **Parameters & body** — tables describing every input.
5. **curl example** — copy, paste, change the values.
6. **Example response** — what comes back, with the important fields explained.
7. **Common errors** — what each error number means and how to fix it.

### Three permission levels you'll see

| Label | Plain meaning |
|-------|---------------|
| **Token (any logged-in user)** | Just log in. Anyone with an account can call it. |
| **Admin / Superuser** | Your account must be an administrator. |
| **God Mode** | A *temporary* extra-powerful switch that an admin turns on for their own session before doing something dangerous (deleting things, changing live infrastructure). Turn it on with `POST /api/v1/system/mode`. (in plain terms: a "are you really sure?" master switch.) |

---

## Table of Contents — every endpoint group

| Group | What it's for | Page |
|-------|---------------|------|
| Login & Registration | Get a token, register, log out | [endpoints/login.md](./endpoints/login.md) |
| Users | Manage user accounts and roles | [endpoints/users.md](./endpoints/users.md) |
| System | Status, first-run setup, God Mode, settings | [endpoints/system.md](./endpoints/system.md) |
| Dashboard | Cluster stats and node metrics | [endpoints/dashboard.md](./endpoints/dashboard.md) |
| Audit | History of changes made through DokOps | [endpoints/audit.md](./endpoints/audit.md) |
| Kubernetes | Look at and control your cluster (pods, deployments…) | [endpoints/kubernetes.md](./endpoints/kubernetes.md) |
| AI | Ask the AI to diagnose problems, run runbooks | [endpoints/ai.md](./endpoints/ai.md) |
| Chat | Persistent AI chat conversations | [endpoints/chat.md](./endpoints/chat.md) |
| Clusters | Add/connect/import Kubernetes clusters | [endpoints/clusters.md](./endpoints/clusters.md) |
| Tools | AI toolsets and their environment variables | [endpoints/tools.md](./endpoints/tools.md) |
| Operations | Approve/reject risky pending AI actions | [endpoints/operations.md](./endpoints/operations.md) |
| RAG (Knowledge Base) | Upload docs the AI can learn from | [endpoints/rag.md](./endpoints/rag.md) |
| Integrations (Azure) | Connect Azure for cost/monitoring data | [endpoints/integrations.md](./endpoints/integrations.md) |
| Integrations (Observability) | Connect Prometheus, Loki, Grafana, etc. | [endpoints/integrations-obs.md](./endpoints/integrations-obs.md) |
| MCP | Connect external MCP tool servers | [endpoints/mcp.md](./endpoints/mcp.md) |
| CLI Tools | Detect/install command-line tools on the server | [endpoints/cli-tools.md](./endpoints/cli-tools.md) |
| Topology | Live dependency graph of your cluster | [endpoints/topology.md](./endpoints/topology.md) |
| SSO | Single sign-on (Google/Azure/Okta) login flow | [endpoints/sso.md](./endpoints/sso.md) |
| Workflows | Build and run automation workflows & AI agents | [endpoints/workflows.md](./endpoints/workflows.md) |
| Activation | License activation | [endpoints/activation.md](./endpoints/activation.md) |
| Minions | Manage remote agents on your servers | [endpoints/minions.md](./endpoints/minions.md) |
| Organisations | Group your minions into orgs and groups | [endpoints/organisations.md](./endpoints/organisations.md) |
| Patching | OS patch compliance, pipelines and schedules | [endpoints/patching.md](./endpoints/patching.md) |
| Service Credentials | Store passwords minions use to reach services | [endpoints/service-credentials.md](./endpoints/service-credentials.md) |
| Alerts | Incoming alerts, incidents and auto-RCA | [endpoints/alerts.md](./endpoints/alerts.md) |
| Vault | Credential coverage report | [endpoints/vault.md](./endpoints/vault.md) |
| Registries | Connect Docker image registries | [endpoints/registries.md](./endpoints/registries.md) |
| Analytics | AI token usage analytics | [endpoints/analytics.md](./endpoints/analytics.md) |
| Knowledge Sources | External knowledge connectors | [endpoints/knowledge-sources.md](./endpoints/knowledge-sources.md) |
| Blueprints | Reusable install/config bundles for minions | [endpoints/blueprints.md](./endpoints/blueprints.md) |
| Keys | Enrollment keys for new minions | [endpoints/keys.md](./endpoints/keys.md) |
| OpenAI-Compatible | Use DokOps as a drop-in OpenAI API | [endpoints/openai-compatible.md](./endpoints/openai-compatible.md) |
| Minion Bootstrap | Files & PyPI proxy used when installing a minion | [endpoints/minion-bootstrap.md](./endpoints/minion-bootstrap.md) |

> **See also:** [`overview.md`](./overview.md) for the shared base-URL table, HTTP status codes, pagination rules, and Server-Sent-Events (streaming) notes. The machine-readable [`openapi.json`](./openapi.json) can be imported into Postman, Insomnia, or any OpenAPI tool to auto-generate a full request collection.

---

## A note on streaming (real-time) endpoints

A few endpoints **stream** their answer back to you piece by piece instead of all at once. These use a technology called **Server-Sent Events (SSE)**. With `curl`, add the `-N` flag so output isn't buffered. Streaming endpoints are clearly marked on each page. They include:

- `POST /api/v1/ai/diagnose/stream`, `POST /api/v1/ai/global/stream`, `POST /api/v1/ai/analyze/batch`
- `POST /api/v1/chat/conversations/{id}/message`
- `GET /api/v1/topology/stream`
- `GET /api/v1/minions/blueprint/runs/{run_id}/stream`
- `GET /api/v1/workflows/runs/{run_id}/stream`
- `POST /v1/chat/completions` (when `"stream": true`)

Because a browser's streaming connection can't send an `Authorization` header, some streaming endpoints take the token as a `token` (or `ticket`) **query parameter** instead. This is noted on each one.

---

## Counts

This reference documents **262 listed API operations** across 32 groups, plus the **9 unlisted minion-bootstrap routes** (file downloads + a PyPI proxy). That's the complete surface of the DokOps backend as generated directly from the live FastAPI app.
