// frontend/src/pages/AlertIncidents.tsx
import React, { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  RefreshCw,
  XCircle,
} from "lucide-react";
import api from "../lib/api";
import jiraLogo from "../assets/logos/jira.svg";

interface AlertIncident {
  id: number;
  alert_name: string;
  source: string;
  severity: string;
  namespace: string | null;
  pod_name: string | null;
  status: string;
  rca_report: string | null;
  evidence: string | null;
  jira_ticket_key: string | null;
  jira_ticket_url: string | null;
  notification_sent_at: string | null;
  remediation_action: string | null;
  remediation_outcome: string | null;
  created_at: string;
  resolved_at: string | null;
}

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  pending:     { label: "Pending",      color: "bg-muted text-muted-foreground" },
  collecting:  { label: "Collecting",   color: "bg-blue-600 text-blue-100" },
  rca_running: { label: "RCA Running",  color: "bg-yellow-500 text-yellow-900" },
  notified:    { label: "Notified",     color: "bg-green-600 text-green-100" },
  remediated:  { label: "Remediated",   color: "bg-purple-600 text-purple-100" },
  closed:      { label: "Closed",       color: "bg-secondary text-secondary-foreground" },
};

interface JiraAlertConfig {
  instance_type: "cloud" | "server_basic" | "server_pat";
  base_url: string;
  email: string;
  username: string;
  api_token: string;
  project_key: string;
}

const DEFAULT_JIRA_CONFIG: JiraAlertConfig = {
  instance_type: "cloud",
  base_url: "",
  email: "",
  username: "",
  api_token: "",
  project_key: "",
};

const SEVERITY_CONFIG: Record<string, { color: string; icon: React.ReactNode }> = {
  critical: { color: "text-red-400",    icon: <XCircle className="w-4 h-4" /> },
  warning:  { color: "text-yellow-400", icon: <AlertTriangle className="w-4 h-4" /> },
  info:     { color: "text-blue-400",   icon: <CheckCircle className="w-4 h-4" /> },
};

function RcaSummary({ rcaReport }: { rcaReport: string | null }) {
  if (!rcaReport) return <p className="text-muted-foreground text-sm">No RCA report yet.</p>;
  try {
    const steps = JSON.parse(rcaReport) as Array<{ type: string; message: string }>;
    const result = steps.find((s) => s.type === "result");
    if (result) return <p className="text-sm text-foreground whitespace-pre-wrap">{result.message}</p>;
    return <p className="text-muted-foreground text-sm">RCA in progress…</p>;
  } catch {
    return <p className="text-sm text-foreground whitespace-pre-wrap">{rcaReport.slice(0, 400)}</p>;
  }
}

function EvidencePanel({ evidence }: { evidence: string | null }) {
  if (!evidence) return null;
  try {
    const ev = JSON.parse(evidence) as Record<string, string>;
    return (
      <div className="space-y-2">
        {ev.logs && (
          <details>
            <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground">Logs</summary>
            <pre className="text-xs bg-background p-2 rounded mt-1 overflow-x-auto max-h-40 text-foreground border border-border">
              {ev.logs.slice(-1500)}
            </pre>
          </details>
        )}
        {ev.events && (
          <details>
            <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground">Events</summary>
            <pre className="text-xs bg-background p-2 rounded mt-1 overflow-x-auto max-h-40 text-foreground border border-border">
              {ev.events.slice(0, 1000)}
            </pre>
          </details>
        )}
      </div>
    );
  } catch {
    return null;
  }
}

export default function AlertIncidents() {
  const [incidents, setIncidents] = useState<AlertIncident[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [statusFilter, setStatusFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [jiraConfig, setJiraConfig] = useState<JiraAlertConfig>(DEFAULT_JIRA_CONFIG);
  const [jiraConfigOpen, setJiraConfigOpen] = useState(false);
  const [savingJira, setSavingJira] = useState(false);
  const [testingJira, setTestingJira] = useState(false);
  const [jiraSaved, setJiraSaved] = useState(false);
  const [jiraTestResult, setJiraTestResult] = useState<{ ok: boolean; detail: string } | null>(null);

  const fetchIncidents = () => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (statusFilter) params.status = statusFilter;
    if (severityFilter) params.severity = severityFilter;
    api
      .get("/alerts/incidents", { params })
      .then((res) => setIncidents(res.data as AlertIncident[]))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(fetchIncidents, [statusFilter, severityFilter]);
  useEffect(() => { loadJiraConfig(); }, []);

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const resolveIncident = async (id: number) => {
    if (!window.confirm("Mark this incident as closed?")) return;
    try {
      await api.post(`/alerts/incidents/${id}/resolve`);
      fetchIncidents();
    } catch {
      alert("Failed to resolve — superuser required.");
    }
  };

  const loadJiraConfig = async () => {
    try {
      const res = await api.get("/alerts/jira-config");
      if (res.data && res.data.base_url) {
        setJiraConfig({
          instance_type: res.data.instance_type ?? "cloud",
          base_url: res.data.base_url ?? "",
          email: res.data.email ?? "",
          username: res.data.username ?? "",
          api_token: res.data.api_token ?? "",
          project_key: res.data.project_key ?? "",
        });
      }
    } catch {
      // Not configured yet — keep defaults
    }
  };

  const handleSaveJiraConfig = async () => {
    setSavingJira(true);
    setJiraSaved(false);
    try {
      await api.put("/alerts/jira-config", {
        ...jiraConfig,
        api_token: jiraConfig.api_token === "••••••" ? "" : jiraConfig.api_token,
      });
      setJiraSaved(true);
      setTimeout(() => setJiraSaved(false), 3000);
    } catch (err: any) {
      alert(`Save failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setSavingJira(false);
    }
  };

  const handleTestJira = async () => {
    setTestingJira(true);
    setJiraTestResult(null);
    try {
      // Always save current form state first — test reads from DB
      await api.put("/alerts/jira-config", {
        ...jiraConfig,
        api_token: jiraConfig.api_token === "••••••" ? "" : jiraConfig.api_token,
      });
      setJiraSaved(true);
      await api.post("/alerts/jira-test");
      setJiraTestResult({ ok: true, detail: "Connected" });
    } catch (err: any) {
      setJiraTestResult({ ok: false, detail: err.response?.data?.detail || err.message });
    } finally {
      setTestingJira(false);
    }
  };

  const sevCfg = (s: string) => SEVERITY_CONFIG[s] ?? SEVERITY_CONFIG.info;
  const statCfg = (s: string) => STATUS_CONFIG[s] ?? { label: s, color: "bg-secondary text-secondary-foreground" };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-foreground">Alert Incidents</h1>
        <button
          onClick={fetchIncidents}
          className="flex items-center gap-2 px-3 py-1.5 rounded bg-secondary hover:bg-muted text-sm text-secondary-foreground border border-border"
        >
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-3">
        <div className="relative">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="appearance-none bg-card border border-border rounded px-3 py-1.5 pr-8 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">All statuses</option>
            {Object.entries(STATUS_CONFIG).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>
          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
        </div>
        <div className="relative">
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="appearance-none bg-card border border-border rounded px-3 py-1.5 pr-8 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">All severities</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
        </div>
      </div>

      {/* Jira Configuration */}
      <div className="rounded-lg border border-border bg-card">
        <button
          onClick={() => setJiraConfigOpen((v) => !v)}
          className="w-full flex items-center justify-between px-4 py-3 text-left"
        >
          <span className="text-sm font-medium text-foreground flex items-center gap-2">
            <img src={jiraLogo} alt="Jira" className="w-4 h-4" />
            Jira Configuration
            {jiraConfig.base_url && (
              <span className="text-xs text-muted-foreground font-normal">({jiraConfig.base_url})</span>
            )}
          </span>
          {jiraConfigOpen ? (
            <ChevronDown className="w-4 h-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="w-4 h-4 text-muted-foreground" />
          )}
        </button>
        {jiraConfigOpen && (
          <div className="border-t border-border px-4 pb-4 pt-3 space-y-3">
            {/* Instance type */}
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Instance Type</label>
              <div className="flex gap-2">
                {(["cloud", "server_basic", "server_pat"] as const).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setJiraConfig((p) => ({ ...p, instance_type: t }))}
                    className={`px-2 py-1 text-xs rounded border transition-colors ${
                      jiraConfig.instance_type === t
                        ? "border-primary bg-primary/10 text-primary font-medium"
                        : "border-border text-muted-foreground hover:border-primary/50"
                    }`}
                  >
                    {t === "cloud" ? "Cloud" : t === "server_basic" ? "Server (Basic)" : "Server (PAT)"}
                  </button>
                ))}
              </div>
            </div>
            {/* Fields grid */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-muted-foreground block mb-0.5">Base URL</label>
                <input
                  value={jiraConfig.base_url}
                  onChange={(e) => setJiraConfig((p) => ({ ...p, base_url: e.target.value }))}
                  placeholder="https://acme.atlassian.net"
                  className="w-full bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-0.5">Project Key</label>
                <input
                  value={jiraConfig.project_key}
                  onChange={(e) => setJiraConfig((p) => ({ ...p, project_key: e.target.value }))}
                  placeholder="OPS"
                  className="w-full bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
                />
              </div>
              {jiraConfig.instance_type === "cloud" && (
                <div>
                  <label className="text-xs text-muted-foreground block mb-0.5">Email</label>
                  <input
                    value={jiraConfig.email}
                    onChange={(e) => setJiraConfig((p) => ({ ...p, email: e.target.value }))}
                    placeholder="ops@acme.com"
                    className="w-full bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
                  />
                </div>
              )}
              {jiraConfig.instance_type === "server_basic" && (
                <div>
                  <label className="text-xs text-muted-foreground block mb-0.5">Username</label>
                  <input
                    value={jiraConfig.username}
                    onChange={(e) => setJiraConfig((p) => ({ ...p, username: e.target.value }))}
                    placeholder="jirauser"
                    className="w-full bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
                  />
                </div>
              )}
              <div className={jiraConfig.instance_type === "server_pat" ? "col-span-2" : ""}>
                <label className="text-xs text-muted-foreground block mb-0.5">
                  {jiraConfig.instance_type === "cloud"
                    ? "API Token"
                    : jiraConfig.instance_type === "server_basic"
                    ? "Password"
                    : "Personal Access Token"}
                </label>
                <input
                  type="password"
                  value={jiraConfig.api_token}
                  onChange={(e) => setJiraConfig((p) => ({ ...p, api_token: e.target.value }))}
                  placeholder="••••••••"
                  className="w-full bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
                />
              </div>
            </div>
            {/* Actions */}
            <div className="flex items-center gap-3 pt-1">
              <button
                onClick={handleTestJira}
                disabled={testingJira}
                className="px-3 py-1.5 text-xs rounded border border-border bg-secondary hover:bg-muted text-secondary-foreground transition-colors disabled:opacity-50"
              >
                {testingJira ? "Testing…" : "Test Connection"}
              </button>
              <button
                onClick={handleSaveJiraConfig}
                disabled={savingJira}
                className="px-3 py-1.5 text-xs rounded bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {savingJira ? "Saving…" : "Save"}
              </button>
              {jiraSaved && <span className="text-xs text-green-500">✓ Saved</span>}
              {jiraTestResult && (
                <span className={`text-xs font-medium ${jiraTestResult.ok ? "text-green-500" : "text-red-500"}`}>
                  {jiraTestResult.ok ? "✓ Connected" : `✗ ${jiraTestResult.detail}`}
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {loading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : incidents.length === 0 ? (
        <p className="text-muted-foreground text-sm">No incidents found.</p>
      ) : (
        <div className="space-y-2">
          {incidents.map((inc) => {
            const sc = sevCfg(inc.severity);
            const st = statCfg(inc.status);
            const isOpen = expanded.has(inc.id);
            return (
              <div key={inc.id} className="rounded-lg border border-border bg-card">
                {/* Row header */}
                <button
                  onClick={() => toggleExpand(inc.id)}
                  className="w-full flex items-center gap-3 px-4 py-3 text-left"
                >
                  <span className={sc.color}>{sc.icon}</span>
                  <span className="font-medium text-foreground flex-1 text-sm">{inc.alert_name}</span>
                  <span className="text-xs text-muted-foreground">{inc.source}</span>
                  <span className="text-xs text-muted-foreground">
                    {inc.namespace ? `${inc.namespace}/${inc.pod_name ?? "—"}` : "—"}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${st.color}`}>
                    {st.label}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {new Date(inc.created_at).toLocaleString()}
                  </span>
                  {inc.jira_ticket_url && (
                    <a
                      href={inc.jira_ticket_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="text-blue-400 hover:text-blue-300"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  )}
                  {isOpen ? (
                    <ChevronDown className="w-4 h-4 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-muted-foreground" />
                  )}
                </button>

                {/* Expanded detail */}
                {isOpen && (
                  <div className="px-4 pb-4 space-y-4 border-t border-border pt-3">
                    <div>
                      <h3 className="text-xs font-semibold text-muted-foreground uppercase mb-1">AI Root Cause Analysis</h3>
                      <RcaSummary rcaReport={inc.rca_report} />
                    </div>
                    <div>
                      <h3 className="text-xs font-semibold text-muted-foreground uppercase mb-1">Evidence</h3>
                      <EvidencePanel evidence={inc.evidence} />
                    </div>
                    {inc.remediation_action && (
                      <div>
                        <h3 className="text-xs font-semibold text-muted-foreground uppercase mb-1">Auto-Remediation</h3>
                        <p className="text-sm text-foreground">
                          Action: <code className="bg-muted px-1 rounded">{inc.remediation_action}</code>
                          {" "}— {inc.remediation_outcome}
                        </p>
                      </div>
                    )}
                    {inc.status !== "closed" && (
                      <button
                        onClick={() => resolveIncident(inc.id)}
                        className="px-3 py-1.5 bg-secondary hover:bg-muted rounded text-xs text-secondary-foreground border border-border"
                      >
                        Mark Resolved
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
