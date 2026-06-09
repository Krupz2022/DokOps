import {
    Shield, Terminal, Zap, Server, Lock, Bot, Monitor,
    Bell, GitBranch, Package, Database, Network, Users,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";

const PILLARS = [
    {
        icon: <Bot className="w-5 h-5 text-blue-400" />,
        title: "Autonomous AI Agent Loop",
        body: "Send a plain-English request and the AI recursively calls real Kubernetes tools — get_pod_logs, describe_deployment, get_events — until it reaches a root cause. Every step streams to the UI in real time via SSE.",
    },
    {
        icon: <Network className="w-5 h-5 text-indigo-400" />,
        title: "Multi-Cluster Management",
        body: "Register multiple AKS, EKS, GKE, or generic clusters. Bearer token, client-cert, and in-cluster auth modes supported. All K8s operations scope to the active cluster — switch with one click.",
    },
    {
        icon: <Bell className="w-5 h-5 text-red-400" />,
        title: "Autonomous Alert Response",
        body: "Ingest webhooks from Alertmanager, Grafana, Datadog, PagerDuty, OpsGenie, Elasticsearch, and generic sources. Per-source HMAC validation, automatic evidence collection, AI RCA, Jira ticket creation, Slack/Teams notification, and optional pod restart — all without human intervention.",
    },
    {
        icon: <Monitor className="w-5 h-5 text-teal-400" />,
        title: "Minion Fleet",
        body: "Lightweight Python agents for Linux and Windows bare-metal/VMs. Token-authenticated WebSocket connection, automatic middleware service discovery (RabbitMQ, Redis, PostgreSQL, Kafka…), real-time command streaming, and OS patch management.",
    },
    {
        icon: <Zap className="w-5 h-5 text-amber-400" />,
        title: "Autonomous Agents",
        body: "Goal-driven AI workers that choose their own tool sequence from a 28-tool catalog. Human approval gate pauses execution before any destructive action. Tool calls, results, and approval prompts stream to the browser in real time.",
    },
    {
        icon: <GitBranch className="w-5 h-5 text-lime-400" />,
        title: "Workflows & Automation",
        body: "Scripted multi-step pipelines with Slack, Teams, Jira, ArgoCD, Jenkins, and SMTP connectors. Manual, scheduled, and webhook triggers. Full execution history with per-step logs.",
    },
    {
        icon: <Package className="w-5 h-5 text-emerald-400" />,
        title: "Patch Management",
        body: "End-to-end OS patching across Linux and Windows minions. Multi-stage promotion pipelines (dev → staging → prod), recurring maintenance schedules, per-device compliance views with severity sorting.",
    },
    {
        icon: <Database className="w-5 h-5 text-yellow-400" />,
        title: "Knowledge Base (RAG)",
        body: "Ingest runbooks, SOPs, and architecture docs (PDF, Markdown, URLs, Confluence). ChromaDB vector store with local or remote embedding. AI retrieves relevant chunks as context before every answer.",
    },
    {
        icon: <Terminal className="w-5 h-5 text-orange-400" />,
        title: "Observability Integrations",
        body: "Connect Prometheus, Grafana, Elasticsearch/OpenSearch, Loki, and Datadog. The AI queries these sources automatically during incident triage — no manual switching between tools.",
    },
    {
        icon: <Shield className="w-5 h-5 text-blue-500" />,
        title: "God Mode & Audit Trail",
        body: "All write operations require God Mode plus explicit confirmation. Every destructive action — K8s mutation, minion command, agent approval — is recorded in an immutable audit log with actor, timestamp, and outcome.",
    },
    {
        icon: <Lock className="w-5 h-5 text-purple-400" />,
        title: "Security Hardening",
        body: "Startup rejects weak AUTH_SECRET_KEY values. SSRF protection blocks private IPs and cloud metadata endpoints. Fernet encryption for stored credentials. AI responses scanned and secrets redacted before display. Per-source HMAC validation on all alert webhooks.",
    },
    {
        icon: <Users className="w-5 h-5 text-blue-300" />,
        title: "SSO / OAuth2",
        body: "Four identity providers out of the box: Microsoft Entra ID, Google Workspace, Authentik, and AWS Cognito. Group/role claims map automatically to admin or viewer RBAC. JWT cookie auth for seamless browser sessions.",
    },
];

export default function Info() {
    return (
        <div className="flex-1 overflow-y-auto">
            <div className="container mx-auto px-4 py-12">
                <div className="max-w-5xl mx-auto space-y-12">

                    {/* Hero */}
                    <div className="text-center space-y-3">
                        <h1 className="text-4xl font-extrabold tracking-tight lg:text-5xl bg-gradient-to-r from-blue-600 to-cyan-500 bg-clip-text text-transparent">
                            DokOps Platform
                        </h1>
                        <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
                            A production-grade Kubernetes DevOps platform with an AI agent loop, autonomous alert response, remote fleet management, and a full-featured Web UI.
                        </p>
                    </div>

                    {/* Feature pillars */}
                    <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-5">
                        {PILLARS.map((p) => (
                            <Card key={p.title} className="hover:border-primary/40 transition-colors">
                                <CardHeader>
                                    <CardTitle className="flex items-center gap-2 text-base">
                                        {p.icon}
                                        {p.title}
                                    </CardTitle>
                                </CardHeader>
                                <CardContent className="text-sm text-muted-foreground leading-relaxed">
                                    {p.body}
                                </CardContent>
                            </Card>
                        ))}
                    </div>

                    {/* System info */}
                    <div className="p-6 rounded-lg bg-muted/50 border border-border">
                        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                            <Server className="w-5 h-5" />
                            System Information
                        </h3>
                        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-3 text-sm">
                            <dt className="text-muted-foreground">Version</dt>
                            <dd className="font-mono">1.1.0</dd>

                            <dt className="text-muted-foreground">Backend</dt>
                            <dd className="font-mono">Python 3.10 · FastAPI</dd>

                            <dt className="text-muted-foreground">Frontend</dt>
                            <dd className="font-mono">React 19 · TypeScript</dd>

                            <dt className="text-muted-foreground">AI Providers</dt>
                            <dd className="font-mono">OpenAI · Azure · Gemini</dd>

                            <dt className="text-muted-foreground">Developer</dt>
                            <dd>Krupz</dd>

                            <dt className="text-muted-foreground">License</dt>
                            <dd>Apache 2.0</dd>
                        </dl>
                    </div>

                </div>
            </div>
        </div>
    );
}
