# DokOps Documentation

DokOps is a production-grade Kubernetes DevOps platform that combines an AI-powered chat interface, full Kubernetes resource management, observability integrations, remote agent fleet management, automated patching, and workflow automation — all behind a secure, role-based web UI.

---

## Quick Navigation

### Getting Started
| Guide | Description |
|-------|-------------|
| [Installation](getting-started/installation.md) | Docker Compose, Helm, or local development setup |
| [First Run & Setup](getting-started/first-run.md) | Create admin account, configure AI provider |
| [Quickstart](getting-started/quickstart.md) | Be productive in 5 minutes |

### Core Features
| Feature | Description |
|---------|-------------|
| [AI Chat](features/ai-chat.md) | Natural language Kubernetes troubleshooting |
| [Kubernetes Resources](features/kubernetes-resources.md) | Browse, inspect, and manage K8s resources |
| [Multi-Cluster Management](features/multi-cluster.md) | Connect and switch between multiple clusters |
| [Cluster Topology](features/topology.md) | Interactive dependency graph visualization |
| [Diagnostics & Runbooks](features/diagnostics-runbooks.md) | Automated health checks and triage guides |
| [Knowledge Base (RAG)](features/knowledge-base.md) | Upload docs to give AI context |
| [Knowledge Sources](features/knowledge-sources.md) | Connect existing external stores (Azure AI Search, Qdrant, Pinecone, Weaviate, OpenSearch, Chroma) |
| [Observability & Alert Response](features/observability.md) | Prometheus, Grafana, Elastic, Loki, Datadog + autonomous alert ingestion |
| [Azure Integration](features/azure-integration.md) | Cost management, resource discovery, anomaly detection |
| [MCP Servers](features/mcp-servers.md) | Connect external MCP tool servers |
| [Minions (Remote Agents)](features/minions.md) | Manage Linux & Windows bare-metal/VM fleets, middleware discovery |
| [Workflow Builder & Agents](features/workflows.md) | Scripted pipelines + goal-driven AI agents with approval gates |
| [CLI Tools](features/cli-tools.md) | Run and manage CLI tools from the UI |
| [Patch Management](features/patching.md) | Multi-stage pipelines, Linux & Windows compliance, per-device views, schedule notifications |
| [Vault](features/vault.md) | Cluster-scoped middleware credentials + `$VAULT:` token resolution |
| [Container Registry Lookup](features/registry-lookup.md) | OCI registry querying for ImagePullBackOff diagnosis |
| [AI Token Analytics](features/analytics.md) | Track provider token usage per surface with charts |
| [God Mode](features/god-mode.md) | Authorized destructive operations with audit trail |

### Security
| Guide | Description |
|-------|-------------|
| [Authentication](security/authentication.md) | JWT login, SSO/OAuth2 (Entra ID, Google, Authentik, Cognito) |
| [Roles & Permissions](security/roles-permissions.md) | Admin vs. Viewer, God Mode enforcement |
| [Secrets Management](security/secrets.md) | Encryption at rest, secret redaction in AI responses |

### Administration
| Guide | Description |
|-------|-------------|
| [Configuration Reference](administration/configuration.md) | All environment variables |
| [User Management](administration/user-management.md) | Create users, SSO auto-provisioning |
| [Audit Logs](administration/audit-logs.md) | Mutation log, filtering, compliance |

### API & Deployment
| Guide | Description |
|-------|-------------|
| [API Overview](api-reference/overview.md) | Authentication, base URLs, error codes |
| [OpenAI-Compatible Endpoint](api-reference/openai-compatible.md) | Drop-in LLM proxy for external tools |
| [Docker Compose](deployment/docker-compose.md) | Local and single-server deployment |
| [Helm Charts](deployment/helm.md) | Production Kubernetes deployment |
| [Production Checklist](deployment/production.md) | Secrets, TLS, database, scaling |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser                              │
│              React 19 + TypeScript + TailwindCSS            │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS / SSE / WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│                    FastAPI Backend                          │
│  JWT/Cookie Auth │ AI Service │ K8s Client │ Workflow Engine │
│  Agent Executor  │ Alert Pipeline │ Service Discovery       │
│  RAG/ChromaDB    │ Topology │ Minion Fleet │ Audit          │
│  Vault Resolver  │ Registry Lookup │ Token Analytics        │
└──────┬───────────┬───────────┬─────────────┬───────────────┘
       │           │           │             │
  Kubernetes   AI Provider  ChromaDB    SQLite/PostgreSQL
  (asyncio)  (OpenAI/Azure   (Vector      (State DB)
              /Gemini)        Store)
       │
  Minion Fleet (Linux + Windows)
  WebSocket ← token-authenticated
  Service Discovery │ Middleware Probes │ Patch Scans
```

---

## Key Concepts

**Normal Mode** — Read-only Kubernetes access. Any user can browse resources, run AI diagnostics, and view metrics. No changes to the cluster are possible.

**God Mode** — Unlocks write operations (scale, delete, patch, restart). Every action is logged in the immutable audit trail and requires explicit user confirmation. Disabled by default. Required to approve destructive Agent actions.

**AI Agent Loop** — When you send a message in the AI Chat, the backend runs a function-calling loop: the AI calls real Kubernetes tools (`get_pod_logs`, `describe_deployment`, etc.), accumulates context, and streams back a structured response with reasoning, actions taken, and recommendations.

**Agents** — Goal-driven automation. You define a goal in plain English and which tools the agent is allowed to use. The AI autonomously decides the sequence of tool calls, pauses for human approval on destructive actions, and streams real-time progress via SSE.

**Minions** — Lightweight Python agents deployed on Linux or Windows bare-metal/VMs. They connect to DokOps with a token over WebSocket, receive jobs, and auto-discover middleware services running on the host.

**Alert Incidents** — When an alert fires from Alertmanager, Grafana, Datadog, or other sources, DokOps collects evidence, runs AI RCA, notifies Slack/Teams/Jira, and optionally remediates — all autonomously, tracked in the Alert Incidents page.

**Service Credential Store** — Encrypted credential storage for middleware services (RabbitMQ, Redis, PostgreSQL, etc.) scoped to individual minions, groups, or globally. Used automatically by AI probe tools — no manual credential passing required.

**Vault** — Cluster-scoped extension of the credential store. Use `$VAULT:service:field` tokens in any toolset command and the executor resolves them from the store at runtime. The Vault page shows credential coverage per cluster.

**Container Registry Lookup** — When an agent encounters `ImagePullBackOff`, it can call `search_container_image` to query public registries (Docker Hub, GHCR, Quay.io, registry.k8s.io) and any user-configured private registries without a general web search.

**AI Token Analytics** — Every AI call (chat, agent, workflow, alert, RAG, notification) writes its real input/output token counts to an `AITokenUsage` table. The Analytics page charts usage trends and top consumers so you can understand cost and optimize prompts.
