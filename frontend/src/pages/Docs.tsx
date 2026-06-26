import { useState } from "react";
import {
    Book, Server, Terminal, Shield, Database, Settings, Copy, Check,
    AlertTriangle, ChevronDown, ChevronRight, Bot, GitBranch, Layers,
    Activity, Bell, Cloud, Plug, Monitor, Key, Users, FileText,
    Network, Zap, Package, BarChart3, Radio,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";

type Tab = "general" | "features" | "deployment" | "env-vars";

// ── Copy helper ──────────────────────────────────────────────────────────────

const MINIMAL_ENV = `# ── Security (REQUIRED — generate with: openssl rand -hex 32) ───────
AUTH_SECRET_KEY=change-me-min-32-chars-random-string
ENCRYPTION_KEY=change-me-min-32-chars-random-string

# ── Tier 1: Bootstrap (required for automated deploy) ───────────────
DOKOPS_ADMIN_USERNAME=admin
DOKOPS_ADMIN_PASSWORD=changeme123!
DOKOPS_AI_PROVIDER=OPENAI
DOKOPS_AI_API_KEY=sk-...
DOKOPS_AI_MODEL=gpt-4o

# ── Optional: lock down signups after first deploy ───────────────────
DOKOPS_SIGNUP_ENABLED=false

# ── Optional: force re-seed on restart (CI/CD only — use with care) ──
# DOKOPS_FORCE_SEED=true`;

function CopyButton({ text }: { text: string }) {
    const [copied, setCopied] = useState(false);
    const handleCopy = () => {
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };
    return (
        <button onClick={handleCopy} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
            {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
            {copied ? "Copied" : "Copy"}
        </button>
    );
}

// ── Env-var table helpers ────────────────────────────────────────────────────

interface EnvVar { name: string; type: string; description: string; example: string; }
interface TierSectionProps { title: string; subtitle: string; vars: EnvVar[]; defaultOpen?: boolean; }

function TierSection({ title, subtitle, vars, defaultOpen = false }: TierSectionProps) {
    const [open, setOpen] = useState(defaultOpen);
    return (
        <Card>
            <button className="w-full text-left" onClick={() => setOpen(!open)}>
                <CardHeader>
                    <div className="flex items-center justify-between w-full">
                        <CardTitle>{title}</CardTitle>
                        <div className="flex items-center gap-2">
                            <span className="text-xs font-normal text-muted-foreground">{subtitle}</span>
                            {open ? <ChevronDown className="w-4 h-4 text-muted-foreground" /> : <ChevronRight className="w-4 h-4 text-muted-foreground" />}
                        </div>
                    </div>
                </CardHeader>
            </button>
            {open && (
                <CardContent>
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm text-left">
                            <thead className="text-xs uppercase bg-muted/50">
                                <tr>
                                    <th className="px-4 py-3 rounded-l-lg">Variable</th>
                                    <th className="px-4 py-3">Type</th>
                                    <th className="px-4 py-3">Description</th>
                                    <th className="px-4 py-3 rounded-r-lg">Example</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border">
                                {vars.map((v) => (
                                    <tr key={v.name}>
                                        <td className="px-4 py-3 font-mono text-xs text-blue-400">{v.name}</td>
                                        <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{v.type}</td>
                                        <td className="px-4 py-3 text-muted-foreground text-xs">{v.description}</td>
                                        <td className="px-4 py-3 font-mono text-xs text-green-400">{v.example}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </CardContent>
            )}
        </Card>
    );
}

// ── Env var datasets ─────────────────────────────────────────────────────────

const TIER1_VARS: EnvVar[] = [
    { name: "DOKOPS_ADMIN_USERNAME", type: "string", description: "First superuser username. Auto-creates admin on startup if no users exist.", example: "admin" },
    { name: "DOKOPS_ADMIN_PASSWORD", type: "string", description: "First superuser password. Use a strong value in production.", example: "changeme123!" },
    { name: "DOKOPS_AI_PROVIDER", type: "string", description: "AI backend to use. One of: OPENAI, AZURE, GEMINI, CUSTOM.", example: "OPENAI" },
    { name: "DOKOPS_AI_API_KEY", type: "string", description: "API key for the selected AI provider.", example: "sk-..." },
    { name: "DOKOPS_AI_MODEL", type: "string", description: "Model or deployment name.", example: "gpt-4o" },
    { name: "DOKOPS_FORCE_SEED", type: "bool", description: "If true, env vars overwrite existing DB values on every restart. CI/CD use only.", example: "false" },
];

const TIER2_VARS: EnvVar[] = [
    { name: "DOKOPS_AI_BASE_URL", type: "string", description: "Base URL for AI provider. Required for AZURE and CUSTOM (Ollama) providers.", example: "https://my-resource.openai.azure.com/" },
    { name: "DOKOPS_AI_API_VERSION", type: "string", description: "Azure-specific API version string.", example: "2023-05-15" },
    { name: "DOKOPS_RAG_ENABLED", type: "bool", description: "Enable the RAG / Knowledge Base feature.", example: "true" },
    { name: "DOKOPS_RAG_CHROMA_HOST", type: "string", description: "ChromaDB server hostname.", example: "chroma-svc" },
    { name: "DOKOPS_RAG_CHROMA_PORT", type: "string", description: "ChromaDB server port.", example: "8001" },
    { name: "DOKOPS_SIGNUP_ENABLED", type: "bool", description: "Allow public user self-registration. Set false to lock down after first deploy.", example: "false" },
    { name: "DOKOPS_SIGNUP_DEFAULT_ROLE", type: "string", description: "Default role for new signups. One of: user, admin.", example: "user" },
];

const TIER3_VARS: EnvVar[] = [
    { name: "DOKOPS_RAG_EMBEDDING_PROVIDER", type: "string", description: "Embedding backend. One of: local, openai, azure.", example: "openai" },
    { name: "DOKOPS_RAG_EMBEDDING_API_KEY", type: "string", description: "API key for non-local embedding provider.", example: "sk-embed-..." },
    { name: "DOKOPS_RAG_EMBEDDING_MODEL", type: "string", description: "Embedding model name.", example: "text-embedding-3-small" },
    { name: "DOKOPS_RAG_EMBEDDING_BASE_URL", type: "string", description: "Base URL for Azure embedding endpoint.", example: "https://my-resource.openai.azure.com/" },
];

const SSO_GENERAL_VARS: EnvVar[] = [
    { name: "SSO_ENABLED", type: "bool", description: "Master switch. Enables SSO login buttons, hides signup and setup wizard.", example: "true" },
    { name: "SSO_AUTO_PROVISION", type: "bool", description: "Auto-create User row on first SSO login.", example: "true" },
    { name: "SSO_ALLOWED_DOMAINS", type: "string", description: "Optional comma-separated domain allowlist.", example: "company.com" },
    { name: "FRONTEND_URL", type: "string", description: "Public frontend URL — used to build OAuth redirect URIs.", example: "https://dokops.company.com" },
    { name: "BACKEND_PUBLIC_URL", type: "string", description: "Public backend URL — used to build OAuth callback URIs.", example: "https://dokops.company.com" },
];

const SSO_ENTRA_VARS: EnvVar[] = [
    { name: "ENTRA_CLIENT_ID", type: "string", description: "Application (client) ID from Azure App Registration.", example: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" },
    { name: "ENTRA_CLIENT_SECRET", type: "string", description: "Client secret from Certificates & Secrets.", example: "your-client-secret" },
    { name: "ENTRA_TENANT_ID", type: "string", description: "Directory (tenant) ID.", example: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" },
    { name: "ENTRA_ROLES_CLAIM", type: "string", description: "JWT claim key containing role values.", example: "roles" },
    { name: "ENTRA_ADMIN_ROLE", type: "string", description: "Claim value that grants Admin role.", example: "Admin" },
];

const SSO_GOOGLE_VARS: EnvVar[] = [
    { name: "GOOGLE_CLIENT_ID", type: "string", description: "OAuth2 Client ID.", example: "12345-abc.apps.googleusercontent.com" },
    { name: "GOOGLE_CLIENT_SECRET", type: "string", description: "OAuth2 Client Secret.", example: "GOCSPX-..." },
    { name: "GOOGLE_ALLOWED_DOMAIN", type: "string", description: "Workspace domain to restrict login to.", example: "company.com" },
    { name: "GOOGLE_ADMIN_GROUP", type: "string", description: "Google Group name whose members get Admin role.", example: "dokops-admins" },
    { name: "GOOGLE_SERVICE_ACCOUNT_JSON", type: "string", description: "Path to service account JSON with Directory API access.", example: "/run/secrets/google-sa.json" },
];

const SSO_AUTHENTIK_VARS: EnvVar[] = [
    { name: "AUTHENTIK_CLIENT_ID", type: "string", description: "OAuth2 Client ID from Authentik application.", example: "your-client-id" },
    { name: "AUTHENTIK_CLIENT_SECRET", type: "string", description: "OAuth2 Client Secret.", example: "your-client-secret" },
    { name: "AUTHENTIK_BASE_URL", type: "string", description: "Your Authentik instance URL.", example: "https://auth.company.com" },
    { name: "AUTHENTIK_ROLES_CLAIM", type: "string", description: "JWT claim key for roles.", example: "roles" },
    { name: "AUTHENTIK_ADMIN_ROLE", type: "string", description: "Claim value that grants Admin role.", example: "Admin" },
];

const SSO_COGNITO_VARS: EnvVar[] = [
    { name: "COGNITO_CLIENT_ID", type: "string", description: "App client ID from Cognito User Pool.", example: "your-cognito-client-id" },
    { name: "COGNITO_CLIENT_SECRET", type: "string", description: "App client secret.", example: "your-cognito-client-secret" },
    { name: "COGNITO_USER_POOL_ID", type: "string", description: "User Pool ID.", example: "us-east-1_xxxxxxx" },
    { name: "COGNITO_REGION", type: "string", description: "AWS region.", example: "us-east-1" },
    { name: "COGNITO_ROLES_CLAIM", type: "string", description: "JWT claim key for groups.", example: "cognito:groups" },
    { name: "COGNITO_ADMIN_ROLE", type: "string", description: "Group name that grants Admin role.", example: "Admin" },
];

// ── Feature card data ────────────────────────────────────────────────────────

interface Feature {
    icon: React.ReactNode;
    title: string;
    description: string;
    bullets: string[];
    badge?: string;
    badgeColor?: string;
}

const FEATURES: Feature[] = [
    {
        icon: <Bot className="w-5 h-5 text-blue-400" />,
        title: "AI Chat",
        description: "Natural-language Kubernetes troubleshooting powered by a recursive function-calling loop.",
        bullets: [
            "Accepts plain-English requests (\"Why is my pod crashing?\")",
            "Recursively calls K8s tools until root cause is found",
            "Streams intermediate steps and final answers via SSE",
            "Full conversation history with token usage tracking",
        ],
    },
    {
        icon: <Layers className="w-5 h-5 text-cyan-400" />,
        title: "Kubernetes Resources",
        description: "Browse, inspect, and manage every resource in your clusters from a single UI.",
        bullets: [
            "Pods, Deployments, Services, Ingresses, Nodes",
            "ConfigMaps, Secrets (keys only — values never exposed)",
            "PVCs, StorageClasses, NetworkPolicies",
            "Scale, restart, patch env vars, get YAML — God Mode required for writes",
        ],
    },
    {
        icon: <Network className="w-5 h-5 text-indigo-400" />,
        title: "Multi-Cluster Management",
        description: "Register and switch between multiple Kubernetes clusters from the UI.",
        bullets: [
            "Supports AKS, EKS, GKE, and generic kubeconfig clusters",
            "Bearer token, client-cert, and in-cluster auth modes",
            "Cluster health verified on registration",
            "All K8s operations scoped to the active cluster",
        ],
    },
    {
        icon: <GitBranch className="w-5 h-5 text-violet-400" />,
        title: "Cluster Topology",
        description: "Interactive force-directed graph mapping the live dependency chain across your cluster.",
        bullets: [
            "Pods → Services → Ingresses → ConfigMaps → PVCs → Nodes",
            "Blast Radius tool: AI identifies affected resources before a change",
            "Background topology service pre-builds the graph to reduce AI latency",
            "Clickable nodes with inline resource details",
        ],
    },
    {
        icon: <Activity className="w-5 h-5 text-green-400" />,
        title: "Diagnostics & Runbooks",
        description: "Automated health checks across eight diagnostic categories with AI-guided triage.",
        bullets: [
            "Checks: container state, probes, networking, storage, RBAC, scheduling, security context, resource limits",
            "Built-in runbooks: CrashLoopBackOff, OOMKilled, Pod Pending, Service Unreachable, High CPU/Memory",
            "AI automatically selects and executes the right runbook",
            "Findings ranked by severity with remediation hints",
        ],
    },
    {
        icon: <Database className="w-5 h-5 text-yellow-400" />,
        title: "Knowledge Base (RAG)",
        description: "Give the AI long-term memory by ingesting your runbooks, SOPs, and architecture docs.",
        bullets: [
            "Ingest files (PDF, MD, TXT), URLs, or bulk-ingest runbooks",
            "Confluence sync — full spaces or individual pages",
            "ChromaDB vector store with configurable embedding provider (local / OpenAI / Azure)",
            "AI retrieves relevant chunks as context before every answer",
        ],
    },
    {
        icon: <BarChart3 className="w-5 h-5 text-orange-400" />,
        title: "Observability Integrations",
        description: "Connect your monitoring stack so the AI can query metrics and logs during incident triage.",
        bullets: [
            "Prometheus — PromQL metric queries",
            "Grafana — dashboard and panel data",
            "Elasticsearch / OpenSearch — KQL log search",
            "Loki — LogQL log queries",
            "Datadog — metrics and logs API",
        ],
    },
    {
        icon: <Bell className="w-5 h-5 text-red-400" />,
        title: "Autonomous Alert Response",
        badge: "New",
        badgeColor: "bg-red-500/20 text-red-400",
        description: "Receive alerts and respond autonomously — evidence first, remediation second.",
        bullets: [
            "Inbound webhooks: Alertmanager, Grafana, Datadog, PagerDuty, OpsGenie, Elasticsearch, Generic",
            "Per-source HMAC validation — unsigned webhooks rejected before processing",
            "Pipeline: collect evidence → AI RCA → Jira ticket → Slack/Teams notification → optional pod restart",
            "Deduplication within a configurable suppression window",
            "Alert Incidents page: full lifecycle (pending → collecting → rca_running → notified → remediated → closed)",
        ],
    },
    {
        icon: <Cloud className="w-5 h-5 text-sky-400" />,
        title: "Azure Integration",
        description: "Connect an Azure subscription to surface cost anomalies and optimization opportunities.",
        bullets: [
            "Client credentials stored Fernet-encrypted",
            "Azure Cost Management queries via AI tool",
            "Advisor cost recommendations surfaced automatically during triage",
            "Configurable from Settings → Azure",
        ],
    },
    {
        icon: <Plug className="w-5 h-5 text-pink-400" />,
        title: "MCP Servers",
        description: "Register external Model Context Protocol servers and let the AI discover their tools dynamically.",
        bullets: [
            "Register any MCP-compatible server by URL",
            "AI discovers and calls external tools at runtime",
            "DokOps itself also exposes an MCP-compatible endpoint",
            "Tool catalog updated without restart",
        ],
    },
    {
        icon: <Monitor className="w-5 h-5 text-teal-400" />,
        title: "Minions — Remote Agent Fleet",
        badge: "Linux + Windows",
        badgeColor: "bg-teal-500/20 text-teal-400",
        description: "Lightweight Python agents for managing bare-metal servers and VMs alongside your clusters.",
        bullets: [
            "Token-authenticated WebSocket connection — no inbound firewall rules needed",
            "Auto-discovers middleware services (RabbitMQ, Redis, PostgreSQL, MySQL, MongoDB, Kafka, etc.)",
            "Run commands, stream stdout/stderr in real time",
            "Organise into Organisations and Minion Groups for bulk operations",
            "Windows: installs as a native Windows Service; air-gap pip proxy included",
        ],
    },
    {
        icon: <Zap className="w-5 h-5 text-amber-400" />,
        title: "Autonomous Agents",
        badge: "New",
        badgeColor: "bg-amber-500/20 text-amber-400",
        description: "Goal-driven AI workers that choose their own tool sequence and pause for human approval on destructive steps.",
        bullets: [
            "28-tool catalog: K8s read/write, Slack/Teams notifications, minion probes",
            "\"Discover Tools\" — AI pre-selects which tools a goal needs",
            "Approval gate: pauses before any destructive action (restart, scale, drain)",
            "SSE streaming: tool calls, results, and approval prompts appear in real time",
            "Trigger types: manual, cron, webhook",
        ],
    },
    {
        icon: <GitBranch className="w-5 h-5 text-lime-400" />,
        title: "Workflow Builder",
        description: "Scripted multi-step automation pipelines with connectors to your DevOps toolchain.",
        bullets: [
            "Step types: K8s action, AI analysis, HTTP request, conditional logic",
            "Connectors: Slack, Teams, Jira, ArgoCD, Jenkins, email (SMTP), generic HTTP",
            "Triggers: manual, scheduled (cron), webhook",
            "Full execution history with per-step logs",
        ],
    },
    {
        icon: <Layers className="w-5 h-5 text-cyan-400" />,
        title: "Blueprints",
        badge: "New",
        badgeColor: "bg-cyan-500/20 text-cyan-400",
        description: "Declarative desired-state config for the fleet — declare packages, files, and services; dry-run the diff; apply with God Mode.",
        bullets: [
            "Resource types: pkg, service, file, cmd — idempotent, Linux + Windows",
            "Requisites: require (ordering) and watch (restart a service on config change)",
            "Assign to global / org / group / minion; merged global → org → group → minion (later wins)",
            "Dry-run shows what would change (open); apply requires God Mode + audit",
            "Author in the UI or seed from backend/app/blueprints/ on startup",
        ],
    },
    {
        icon: <Package className="w-5 h-5 text-emerald-400" />,
        title: "Patch Management",
        description: "End-to-end OS patching for Linux and Windows minions with multi-stage promotion pipelines.",
        bullets: [
            "Per-device patch compliance view with severity sorting",
            "Patch Pipelines: multi-stage promotion (dev → staging → prod)",
            "Patch Schedules: recurring maintenance windows with timezone + auto-promote",
            "Windows Update Agent (WUA) integration for native Windows patching",
        ],
    },
    {
        icon: <Terminal className="w-5 h-5 text-gray-400" />,
        title: "CLI Tools",
        description: "Register parameterized shell commands and run them from the UI with env var injection.",
        bullets: [
            "Commands defined in YAML toolsets",
            "OS env + UI-managed env vars merged at execution time",
            "Full execution log visible per run",
            "God Mode required for commands flagged as destructive",
        ],
    },
    {
        icon: <Key className="w-5 h-5 text-purple-400" />,
        title: "Service Credential Store",
        description: "Encrypted credential storage for middleware services, scoped per-minion, per-group, or globally.",
        bullets: [
            "Fernet encryption at rest — username masked in API responses",
            "Most-specific scope wins at lookup (minion > group > global)",
            "Used automatically by AI probe tools — no manual credential passing",
            "Managed from Settings → Service Credentials",
        ],
    },
    {
        icon: <Users className="w-5 h-5 text-blue-300" />,
        title: "SSO / OAuth2",
        description: "Four identity providers with automatic role mapping from group/claim to DokOps RBAC.",
        bullets: [
            "Microsoft Entra ID (Azure AD)",
            "Google Workspace (with Directory API group lookup)",
            "Authentik (self-hosted OIDC)",
            "AWS Cognito",
        ],
    },
    {
        icon: <Shield className="w-5 h-5 text-rose-400" />,
        title: "Security & Audit",
        description: "Layered security controls from startup validation to immutable mutation logs.",
        bullets: [
            "Startup rejects known-weak AUTH_SECRET_KEY values",
            "SSRF protection blocks private IPs and cloud metadata endpoints",
            "God Mode: explicit toggle + confirmation required for all destructive actions",
            "Immutable mutation audit log with actor, timestamp, resource, and outcome",
            "AI response sanitization — secrets and tokens redacted before display",
        ],
    },
    {
        icon: <Radio className="w-5 h-5 text-fuchsia-400" />,
        title: "OpenAI-Compatible API",
        description: "Drop-in /v1/chat/completions endpoint so external tools can use DokOps as an AI backend.",
        bullets: [
            "Compatible with LangChain, Continue.dev, n8n, and any OpenAI SDK client",
            "Full K8s tool access built in — external clients get agentic capabilities for free",
            "API key managed in Settings → OpenAI-Compatible API",
            "Streaming responses supported",
        ],
    },
];

// ── Feature card component ───────────────────────────────────────────────────

function FeatureCard({ feature }: { feature: Feature }) {
    return (
        <div className="rounded-xl border border-border bg-card p-5 flex flex-col gap-3 hover:border-primary/40 transition-colors">
            <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                    <div className="p-1.5 rounded-lg bg-muted">{feature.icon}</div>
                    <h3 className="font-semibold text-foreground text-sm">{feature.title}</h3>
                </div>
                {feature.badge && (
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full shrink-0 ${feature.badgeColor}`}>
                        {feature.badge}
                    </span>
                )}
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">{feature.description}</p>
            <ul className="space-y-1.5 mt-auto">
                {feature.bullets.map((b, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-muted-foreground">
                        <span className="mt-1.5 w-1 h-1 rounded-full bg-primary/60 shrink-0" />
                        {b}
                    </li>
                ))}
            </ul>
        </div>
    );
}

// ── Main component ───────────────────────────────────────────────────────────

export default function Docs() {
    const [activeTab, setActiveTab] = useState<Tab>("general");

    const tabClass = (tab: Tab) =>
        `px-4 py-2 text-sm font-medium rounded-md transition-all ${activeTab === tab ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground"}`;

    const headings: Record<Tab, { title: string; subtitle: string }> = {
        "general":    { title: "Platform Documentation",  subtitle: "Everything you need to know about the DokOps architecture." },
        "features":   { title: "Features",                subtitle: "A complete map of every capability DokOps ships with." },
        "deployment": { title: "Deployment Guide",        subtitle: "Run it locally, on Docker, or inside Kubernetes." },
        "env-vars":   { title: "Environment Variables",   subtitle: "Configure DokOps at deploy time — no UI required." },
    };

    return (
        <div className="flex-1 overflow-y-auto p-6">
            <div className="flex items-center justify-between mb-8">
                <div className="flex bg-muted p-1 rounded-lg gap-1">
                    <button onClick={() => setActiveTab("general")}    className={tabClass("general")}>General Info</button>
                    <button onClick={() => setActiveTab("features")}   className={tabClass("features")}>Features</button>
                    <button onClick={() => setActiveTab("deployment")} className={tabClass("deployment")}>Deployment Guide</button>
                    <button onClick={() => setActiveTab("env-vars")}   className={tabClass("env-vars")}>Environment Variables</button>
                </div>
            </div>

            <div className="max-w-6xl mx-auto space-y-8 animate-in fade-in duration-500">
                <div className="text-center space-y-4 mb-12">
                    <h1 className="text-4xl font-extrabold tracking-tight lg:text-5xl">{headings[activeTab].title}</h1>
                    <p className="text-xl text-muted-foreground">{headings[activeTab].subtitle}</p>
                </div>

                {/* ── General Info ── */}
                {activeTab === "general" && (
                    <div className="space-y-8 max-w-4xl mx-auto">
                        <Card>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <Book className="w-5 h-5 text-blue-500" /> Introduction
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="space-y-4">
                                <p className="text-muted-foreground">
                                    DokOps is a production-grade Kubernetes DevOps Platform with an AI agent loop, MCP server integration, and a full-featured Web UI. It acts as an autonomous DevOps assistant: AI agents get safe, structured access to your Kubernetes clusters and on-premise infrastructure while humans retain full control via role-based access and an explicit approval gate for destructive actions.
                                </p>
                                <div className="grid md:grid-cols-2 gap-4 mt-4">
                                    <div className="p-4 bg-muted/50 rounded-lg border">
                                        <h3 className="font-semibold mb-2">Backend Stack</h3>
                                        <ul className="list-disc list-inside text-sm text-muted-foreground space-y-1">
                                            <li>Python 3.10+ (FastAPI, fully async)</li>
                                            <li>SQLModel + SQLAlchemy (SQLite / PostgreSQL)</li>
                                            <li>kubernetes-asyncio client</li>
                                            <li>ChromaDB for vector search (RAG)</li>
                                            <li>OpenAI, Azure OpenAI, Google GenAI</li>
                                        </ul>
                                    </div>
                                    <div className="p-4 bg-muted/50 rounded-lg border">
                                        <h3 className="font-semibold mb-2">Frontend Stack</h3>
                                        <ul className="list-disc list-inside text-sm text-muted-foreground space-y-1">
                                            <li>React 19 + Vite</li>
                                            <li>TypeScript (strict, no <code>any</code>)</li>
                                            <li>TailwindCSS v4 — glassmorphism dark-mode</li>
                                            <li>Lucide React icons</li>
                                            <li>Native EventSource for SSE streaming</li>
                                        </ul>
                                    </div>
                                </div>
                            </CardContent>
                        </Card>

                        <Card>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <Shield className="w-5 h-5 text-purple-500" /> Normal Mode vs God Mode
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="space-y-3">
                                <p className="text-muted-foreground text-sm">The system operates in two distinct modes to ensure safety during AI-driven operations.</p>
                                <ul className="space-y-3">
                                    <li className="flex items-start gap-3">
                                        <div className="mt-1.5 w-2 h-2 rounded-full bg-green-500 shrink-0" />
                                        <div>
                                            <strong className="block text-foreground">Normal Mode (Default)</strong>
                                            <span className="text-muted-foreground text-sm">Read-only access. Browse resources, run AI diagnostics, and view metrics. No changes to the cluster are possible.</span>
                                        </div>
                                    </li>
                                    <li className="flex items-start gap-3">
                                        <div className="mt-1.5 w-2 h-2 rounded-full bg-red-500 shrink-0" />
                                        <div>
                                            <strong className="block text-foreground">God Mode</strong>
                                            <span className="text-muted-foreground text-sm">Unlocks write operations (scale, delete, patch, restart). Every action is logged in the immutable audit trail and requires explicit confirmation. Required to approve destructive Agent actions.</span>
                                        </div>
                                    </li>
                                </ul>
                            </CardContent>
                        </Card>

                        <Card>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <FileText className="w-5 h-5 text-yellow-500" /> Key Security Controls
                                </CardTitle>
                            </CardHeader>
                            <CardContent>
                                <div className="overflow-x-auto">
                                    <table className="w-full text-sm text-left">
                                        <thead className="text-xs uppercase bg-muted/50">
                                            <tr>
                                                <th className="px-4 py-3 rounded-l-lg">Control</th>
                                                <th className="px-4 py-3 rounded-r-lg">Description</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-border text-muted-foreground text-xs">
                                            <tr><td className="px-4 py-3 font-medium text-foreground">Startup validation</td><td className="px-4 py-3">Server refuses to start if AUTH_SECRET_KEY is a known-weak value</td></tr>
                                            <tr><td className="px-4 py-3 font-medium text-foreground">SSRF protection</td><td className="px-4 py-3">All user-supplied URLs validated — blocks private IPs, RFC-1918, 169.254.x.x</td></tr>
                                            <tr><td className="px-4 py-3 font-medium text-foreground">Secret sanitization</td><td className="px-4 py-3">All AI responses scanned; secrets and tokens redacted before display</td></tr>
                                            <tr><td className="px-4 py-3 font-medium text-foreground">Fernet encryption</td><td className="px-4 py-3">Cluster tokens, credentials, and OAuth secrets encrypted at rest</td></tr>
                                            <tr><td className="px-4 py-3 font-medium text-foreground">Minion token auth</td><td className="px-4 py-3">WebSocket connections rejected before session if token missing or invalid</td></tr>
                                            <tr><td className="px-4 py-3 font-medium text-foreground">Webhook HMAC</td><td className="px-4 py-3">Per-source signatures validated before any alert payload is processed</td></tr>
                                        </tbody>
                                    </table>
                                </div>
                            </CardContent>
                        </Card>
                    </div>
                )}

                {/* ── Features ── */}
                {activeTab === "features" && (
                    <div className="space-y-6">
                        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                            {FEATURES.map((f) => (
                                <FeatureCard key={f.title} feature={f} />
                            ))}
                        </div>
                        <p className="text-center text-xs text-muted-foreground pt-4">
                            {FEATURES.length} features · See the <code>docs/</code> folder for full reference documentation on each feature.
                        </p>
                    </div>
                )}

                {/* ── Deployment Guide ── */}
                {activeTab === "deployment" && (
                    <div className="space-y-8 max-w-4xl mx-auto">
                        <Card>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <Terminal className="w-5 h-5 text-green-500" /> Local Development
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="space-y-4">
                                <p className="text-sm text-muted-foreground">Run backend and frontend separately for hot-reload development.</p>
                                <div className="bg-black/90 text-white p-4 rounded-lg font-mono text-xs overflow-x-auto">
                                    <div className="text-muted-foreground mb-2"># Terminal 1 — Backend</div>
                                    <pre>{`cd backend\npip install -r requirements.txt\nuvicorn app.main:app --reload --port 8000`}</pre>
                                    <div className="text-muted-foreground mt-4 mb-2"># Terminal 2 — Frontend</div>
                                    <pre>{`cd frontend\nnpm install\nnpm run dev\n# UI available at http://localhost:5173`}</pre>
                                </div>
                                <div className="p-3 border-l-4 border-blue-500 bg-blue-500/10 rounded-r-lg text-sm text-muted-foreground">
                                    If no <code>~/.kube/config</code> is found, the backend starts in <strong className="text-foreground">Mock Mode</strong> — all K8s tools return realistic fake data so you can develop without a cluster.
                                </div>
                            </CardContent>
                        </Card>

                        <Card>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <Terminal className="w-5 h-5 text-orange-500" /> Docker Compose
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="space-y-4">
                                <p className="text-sm text-muted-foreground">Starts backend, frontend, and ChromaDB together. Best for single-server deployments.</p>
                                <div className="bg-black/90 text-white p-4 rounded-lg font-mono text-xs overflow-x-auto">
                                    <pre>{`docker compose -f deployment/docker-compose.yml up -d`}</pre>
                                </div>
                            </CardContent>
                        </Card>

                        <Card>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <Server className="w-5 h-5 text-blue-500" /> Kubernetes (Helm)
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="space-y-4">
                                <p className="text-sm text-muted-foreground">Production deployment via Helm chart. Deploys 4 services: backend, frontend, ChromaDB, and PostgreSQL.</p>
                                <div className="bg-black/90 text-white p-4 rounded-lg font-mono text-xs overflow-x-auto">
                                    <pre>{`helm install dokops ./deployment/helm/dokops \\\n  --set backend.env.AUTH_SECRET_KEY=changeme \\\n  --set backend.env.OPENAI_API_KEY=sk-...`}</pre>
                                </div>
                                <div className="p-4 border-l-4 border-blue-500 bg-blue-500/10 rounded-r-lg">
                                    <h4 className="font-bold flex items-center gap-2 mb-1 text-sm">
                                        <Book className="w-4 h-4" /> In-cluster service account
                                    </h4>
                                    <p className="text-sm text-muted-foreground">
                                        Set <code className="text-blue-400">K8S_IN_CLUSTER_CONFIG=true</code> when running inside a pod. The Helm chart configures the required RBAC automatically.
                                    </p>
                                </div>
                            </CardContent>
                        </Card>

                        <Card>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <Monitor className="w-5 h-5 text-teal-500" /> Minion Installation
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="space-y-4">
                                <div className="space-y-2">
                                    <h3 className="font-semibold text-sm">Linux (systemd)</h3>
                                    <div className="bg-black/90 text-white p-3 rounded-lg font-mono text-xs overflow-x-auto">
                                        <pre>{`curl http://<dokops-host>/minion/install.sh | bash -s -- \\\n  --url=http://<dokops-host> \\\n  --token=<registration-token>`}</pre>
                                    </div>
                                </div>
                                <div className="space-y-2">
                                    <h3 className="font-semibold text-sm">Windows (elevated PowerShell)</h3>
                                    <div className="bg-black/90 text-white p-3 rounded-lg font-mono text-xs overflow-x-auto">
                                        <pre>{`Invoke-WebRequest http://<dokops-host>/minion/install.ps1 -OutFile install.ps1\n.\\install.ps1 -Url http://<dokops-host> -Token <registration-token>`}</pre>
                                    </div>
                                </div>
                            </CardContent>
                        </Card>
                    </div>
                )}

                {/* ── Environment Variables ── */}
                {activeTab === "env-vars" && (
                    <div className="space-y-6 max-w-4xl mx-auto">
                        <Card>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <Settings className="w-5 h-5 text-green-500" /> Minimal Production .env
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="space-y-3">
                                <p className="text-sm text-muted-foreground">
                                    Copy this into a <code>.env</code> file (or Helm <code>values.yaml</code> / K8s Secret) to deploy DokOps with zero manual UI steps.
                                    All values seed the database on first startup and are freely editable in the UI afterwards.
                                </p>
                                <div className="bg-black/90 text-white p-4 rounded-lg font-mono text-xs overflow-x-auto relative">
                                    <div className="flex justify-between items-center mb-3 text-muted-foreground">
                                        <span>.env</span>
                                        <CopyButton text={MINIMAL_ENV} />
                                    </div>
                                    <pre>{MINIMAL_ENV}</pre>
                                </div>
                            </CardContent>
                        </Card>

                        <div className="p-4 border-l-4 border-yellow-500 bg-yellow-500/10 rounded-r-lg flex gap-3">
                            <AlertTriangle className="w-5 h-5 text-yellow-500 mt-0.5 shrink-0" />
                            <div>
                                <h4 className="font-bold text-yellow-500 mb-1">DOKOPS_FORCE_SEED Warning</h4>
                                <p className="text-sm text-muted-foreground">
                                    Setting <code className="text-yellow-400">DOKOPS_FORCE_SEED=true</code> causes all env var values to <strong>overwrite</strong> the database on every container restart — including any changes made via the UI.
                                    Only use this in CI/CD pipelines where you need a guaranteed known state.
                                </p>
                            </div>
                        </div>

                        <TierSection title="Tier 1 — Bootstrap" subtitle="Set these for a fully automated first deploy" vars={TIER1_VARS} defaultOpen={true} />
                        <TierSection title="Tier 2 — Common Configuration" subtitle="AI provider details, RAG, signup policy" vars={TIER2_VARS} />
                        <TierSection title="Tier 3 — Optional Tuning" subtitle="Embedding provider details" vars={TIER3_VARS} />
                        <TierSection title="SSO — General" subtitle="Master switch and shared settings" vars={SSO_GENERAL_VARS} />
                        <TierSection title="SSO — Microsoft Entra ID" subtitle="Azure AD / Entra OIDC" vars={SSO_ENTRA_VARS} />
                        <TierSection title="SSO — Google Workspace" subtitle="Google OIDC + Directory API group lookup" vars={SSO_GOOGLE_VARS} />
                        <TierSection title="SSO — Authentik" subtitle="Self-hosted OIDC provider" vars={SSO_AUTHENTIK_VARS} />
                        <TierSection title="SSO — AWS Cognito" subtitle="Amazon Cognito User Pools OIDC" vars={SSO_COGNITO_VARS} />
                    </div>
                )}
            </div>
        </div>
    );
}
