import { useEffect, useState } from "react";
import api from "../lib/api";
import { useToast } from "../context/ToastContext";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { Save, PlugZap, Database, KeyRound } from "lucide-react";


interface RagConfig {
    rag_enabled: string;
    rag_chroma_host: string;
    rag_chroma_port: string;
    rag_embedding_provider: string;
    rag_embedding_api_key: string;
    rag_embedding_model: string;
    rag_embedding_base_url: string;
}

interface CredentialRead {
    id: string;
    scope_type: "global" | "group" | "minion";
    scope_id: string | null;
    service_type: string;
    username: string;
    port: number | null;
    extra: string;
    created_at: string;
    updated_at: string;
}

interface MinionGroup {
    id: string;
    name: string;
    org_id: string;
}

interface MinionSummary {
    id: string;
    hostname: string;
}

const SERVICE_TYPES = [
    { value: "rabbitmq", label: "RabbitMQ" },
    { value: "redis", label: "Redis" },
    { value: "couchdb", label: "CouchDB" },
    { value: "mongodb", label: "MongoDB" },
    { value: "mysql", label: "MySQL" },
    { value: "postgres", label: "PostgreSQL" },
    { value: "mssql", label: "SQL Server (MSSQL)" },
];

const PASSWORD_ONLY_SERVICES = new Set(["redis"]);

const DEFAULT_FORM = {
    service_type: "rabbitmq",
    scope_type: "global" as "global" | "group" | "minion",
    scope_id: "",
    username: "",
    password: "",
    port: "",
    extra: "{}",
};

const SELECT_CLS = "flex h-9 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary";

function AlertWebhookSecrets() {
  const sources = ["alertmanager","grafana","datadog","pagerduty","opsgenie","elasticsearch","generic"];
  const [secrets, setSecrets] = useState<Record<string,string>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.get("/alerts/webhook-config").then((r) => setSecrets(r.data as Record<string,string>)).catch(() => {});
  }, []);

  const handleSave = async () => {
    await api.put("/alerts/webhook-config", secrets);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground mb-2">Webhook Secrets (per source)</p>
      <div className="space-y-2">
        {sources.map((src) => (
          <div key={src} className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-24">{src}</span>
            <input
              type="password"
              placeholder="Secret token / key"
              value={secrets[src] || ""}
              onChange={(e) => setSecrets((p) => ({ ...p, [src]: e.target.value }))}
              className="flex-1 bg-background border border-border rounded px-2 py-1 text-xs text-foreground"
            />
          </div>
        ))}
      </div>
      <Button size="sm" className="mt-2" onClick={handleSave}>
        {saved ? "Saved!" : "Save Secrets"}
      </Button>
    </div>
  );
}

function AlertNotificationSettings() {
  const [slackWebhook, setSlackWebhook] = useState("");
  const [teamsWebhook, setTeamsWebhook] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.get("/ai/config").then((r) => {
      const d = r.data as Record<string, string>;
      setSlackWebhook(d.alert_slack_webhook || "");
      setTeamsWebhook(d.alert_teams_webhook || "");
    }).catch(() => {});
  }, []);

  const handleSave = async () => {
    await api.post("/ai/config", { alert_slack_webhook: slackWebhook, alert_teams_webhook: teamsWebhook });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground mb-2">Notification Channels</p>
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground w-24">Slack webhook</span>
          <input
            type="text"
            value={slackWebhook}
            onChange={(e) => setSlackWebhook(e.target.value)}
            placeholder="https://hooks.slack.com/..."
            className="flex-1 bg-background border border-border rounded px-2 py-1 text-xs text-foreground"
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground w-24">Teams webhook</span>
          <input
            type="text"
            value={teamsWebhook}
            onChange={(e) => setTeamsWebhook(e.target.value)}
            placeholder="https://outlook.office.com/webhook/..."
            className="flex-1 bg-background border border-border rounded px-2 py-1 text-xs text-foreground"
          />
        </div>
      </div>
      <Button size="sm" className="mt-2" onClick={handleSave}>
        {saved ? "Saved!" : "Save Channels"}
      </Button>
    </div>
  );
}

function AlertRemediationPolicy() {
  const defaultPolicy = JSON.stringify(
    { CrashLoopBackOff: { action: "restart_pod", max_per_hour: 3 } },
    null, 2
  );
  const [policy, setPolicy] = useState(defaultPolicy);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.get("/alerts/policy").then((r) => {
      if (r.data && Object.keys(r.data as object).length > 0) {
        setPolicy(JSON.stringify(r.data, null, 2));
      }
    }).catch(() => {});
  }, []);

  const handleSave = async () => {
    setError("");
    try {
      const parsed = JSON.parse(policy);
      await api.put("/alerts/policy", parsed);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      setError("Invalid JSON");
    }
  };

  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground mb-1">Remediation Allowlist (JSON)</p>
      <p className="text-xs text-muted-foreground mb-2">
        Only alert names listed here will trigger auto-remediation.
      </p>
      <textarea
        rows={5}
        value={policy}
        onChange={(e) => setPolicy(e.target.value)}
        className="w-full bg-background border border-border rounded px-2 py-1 text-xs text-foreground font-mono"
      />
      {error && <p className="text-red-400 text-xs mt-1">{error}</p>}
      <Button size="sm" className="mt-1" onClick={handleSave}>
        {saved ? "Saved!" : "Save Policy"}
      </Button>
    </div>
  );
}

function AlertSuppressionWindow() {
  const [minutes, setMinutes] = useState(5);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.get("/ai/config").then((r) => {
      const m = parseInt((r.data as Record<string, string>).alert_suppression_minutes || "5");
      if (!isNaN(m)) setMinutes(m);
    }).catch(() => {});
  }, []);

  const handleSave = async () => {
    await api.post("/ai/config", { alert_suppression_minutes: String(minutes) });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-muted-foreground">Dedup suppression window</span>
      <input
        type="number"
        min={1}
        max={60}
        value={minutes}
        onChange={(e) => setMinutes(Number(e.target.value))}
        className="w-16 bg-background border border-border rounded px-2 py-1 text-xs text-foreground"
      />
      <span className="text-xs text-muted-foreground">minutes</span>
      <Button size="sm" onClick={handleSave}>
        {saved ? "Saved!" : "Save"}
      </Button>
    </div>
  );
}

export default function Settings() {
    const { toast } = useToast();
    const [config, setConfig] = useState({
        ai_provider: "OPENAI",
        ai_api_key: "",
        ai_base_url: "",
        ai_model: "",
        ai_api_version: "",
        ai_fast_model: "",
        ai_fast_base_url: "",
        ai_fast_api_key: "",
        ctx_tool_budget: "",
        ctx_compaction_threshold: "",
        ctx_keep_recent: "",
    });
    const [ragConfig, setRagConfig] = useState<RagConfig>({
        rag_enabled: "false",
        rag_chroma_host: "localhost",
        rag_chroma_port: "8001",
        rag_embedding_provider: "local",
        rag_embedding_api_key: "",
        rag_embedding_model: "",
        rag_embedding_base_url: "",
    });
    const [loading, setLoading] = useState(false);
    const [testing, setTesting] = useState(false);
    const [savingRag, setSavingRag] = useState(false);
    const [testingRag, setTestingRag] = useState(false);
    const [ragTestStatus, setRagTestStatus] = useState<"idle" | "ok" | "error">("idle");
    const [ragTestMsg, setRagTestMsg] = useState("");

    const [compatConfig, setCompatConfig] = useState<{
        enabled: boolean;
        has_key: boolean;
        created_at: string | null;
    }>({ enabled: false, has_key: false, created_at: null });
    const [compatKey, setCompatKey] = useState<string | null>(null);
    const [compatKeyVisible, setCompatKeyVisible] = useState(false);
    const [togglingCompat, setTogglingCompat] = useState(false);
    const [generatingKey, setGeneratingKey] = useState(false);
    const [credentials, setCredentials] = useState<CredentialRead[]>([]);
    const [groups, setGroups] = useState<MinionGroup[]>([]);
    const [minions, setMinions] = useState<MinionSummary[]>([]);
    const [credForm, setCredForm] = useState(DEFAULT_FORM);
    const [editingCredId, setEditingCredId] = useState<string | null>(null);
    const [savingCred, setSavingCred] = useState(false);
    const [showCredPassword, setShowCredPassword] = useState(false);
    const [deletingCredId, setDeletingCredId] = useState<string | null>(null);
    const [registryEnabled, setRegistryEnabled] = useState(false);
    const [togglingRegistry, setTogglingRegistry] = useState(false);

    useEffect(() => {
        fetchConfig();
        fetchCompatConfig();
        fetchCredentials();
        fetchGroupsAndMinions();
        fetchRegistrySettings();
    }, []);

    const fetchConfig = async () => {
        try {
            const res = await api.get("/ai/config");
            if (res.data) {
                const d = res.data as Record<string, string>;
                setConfig(prev => ({ ...prev, ...d }));
                setRagConfig(prev => ({
                    ...prev,
                    ...(d.rag_enabled !== undefined && { rag_enabled: d.rag_enabled }),
                    ...(d.rag_chroma_host && { rag_chroma_host: d.rag_chroma_host }),
                    ...(d.rag_chroma_port && { rag_chroma_port: d.rag_chroma_port }),
                    ...(d.rag_embedding_provider && { rag_embedding_provider: d.rag_embedding_provider }),
                    ...(d.rag_embedding_model && { rag_embedding_model: d.rag_embedding_model }),
                    ...(d.rag_embedding_base_url && { rag_embedding_base_url: d.rag_embedding_base_url }),
                }));
            }
        } catch (err) {
            console.error("Failed to fetch config", err);
        }
    };

    const fetchCompatConfig = async () => {
        try {
            const res = await api.get("/system/openai-compat");
            setCompatConfig(res.data);
        } catch {
            // silently ignore
        }
    };

    const fetchCredentials = async () => {
        try {
            const res = await api.get("/service-credentials/");
            setCredentials(res.data);
        } catch (err) {
            console.error("Failed to fetch credentials", err);
        }
    };

    const fetchGroupsAndMinions = async () => {
        try {
            const [groupsRes, minionsRes] = await Promise.all([
                api.get("/organisations/groups"),
                api.get("/minions/"),
            ]);
            setGroups(groupsRes.data);
            setMinions(minionsRes.data);
        } catch (err) {
            console.error("Failed to fetch groups/minions", err);
        }
    };

    const handleChange = (field: string, value: string) => {
        setConfig(prev => ({ ...prev, [field]: value }));
    };

    const handleSave = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading(true);
        try {
            await api.post("/ai/config", config);
            toast("Settings saved successfully!", "success");
        } catch (err) {
            toast("Failed to save settings", "error");
        } finally {
            setLoading(false);
        }
    };

    const handleTest = async () => {
        setTesting(true);
        try {
            const res = await api.post("/ai/test", config);
            toast(`Success: ${res.data.message}`, "success");
        } catch (err: any) {
            const msg = err.response?.data?.detail || "Connection Failed";
            toast(`Error: ${msg}`, "error");
        } finally {
            setTesting(false);
        }
    };

    const handleRagChange = (field: keyof RagConfig, value: string) => {
        setRagConfig(prev => ({ ...prev, [field]: value }));
    };

    const handleSaveRag = async (e: React.FormEvent) => {
        e.preventDefault();
        setSavingRag(true);
        try {
            await api.post("/ai/config", ragConfig);
            toast("RAG settings saved!", "success");
        } catch (err) {
            toast("Failed to save RAG settings", "error");
        } finally {
            setSavingRag(false);
        }
    };


    const handleTestRag = async () => {
        setTestingRag(true);
        setRagTestStatus("idle");
        setRagTestMsg("");
        try {
            await api.post("/rag/test-connection");
            setRagTestStatus("ok");
            setRagTestMsg("Connected");
        } catch (err: any) {
            setRagTestStatus("error");
            setRagTestMsg(err.response?.data?.detail || "Connection failed");
        } finally {
            setTestingRag(false);
        }
    };

    const handleCompatToggle = async () => {
        setTogglingCompat(true);
        try {
            await api.patch("/system/openai-compat", { enabled: !compatConfig.enabled });
            setCompatConfig(prev => ({ ...prev, enabled: !prev.enabled }));
            toast(`OpenAI API ${!compatConfig.enabled ? "enabled" : "disabled"}`, "success");
        } catch {
            toast("Failed to update", "error");
        } finally {
            setTogglingCompat(false);
        }
    };

    const handleGenerateKey = async () => {
        setGeneratingKey(true);
        setCompatKey(null);
        try {
            const res = await api.post("/system/openai-compat/regenerate-key");
            setCompatKey(res.data.key);
            setCompatKeyVisible(true);
            await fetchCompatConfig();
            toast("New API key generated — copy it now", "success");
        } catch {
            toast("Failed to generate key", "error");
        } finally {
            setGeneratingKey(false);
        }
    };

    const fetchRegistrySettings = async () => {
        try {
            const res = await api.get("/registries/settings");
            setRegistryEnabled((res.data as { enabled: boolean }).enabled);
        } catch {
            // silently ignore
        }
    };

    const handleRegistryToggle = async () => {
        setTogglingRegistry(true);
        try {
            await api.post("/registries/settings", { enabled: !registryEnabled });
            setRegistryEnabled((prev) => !prev);
            toast(`Registry Lookup ${!registryEnabled ? "enabled" : "disabled"}`, "success");
        } catch {
            toast("Failed to update Registry Lookup setting", "error");
        } finally {
            setTogglingRegistry(false);
        }
    };

    const copyToClipboard = (text: string) => {
        navigator.clipboard.writeText(text);
        toast("Copied!", "success");
    };

    const handleSaveCred = async (e: React.FormEvent) => {
        e.preventDefault();
        if (credForm.extra) {
            try { JSON.parse(credForm.extra); } catch {
                toast("Extra config is not valid JSON", "error");
                return;
            }
        }
        setSavingCred(true);
        try {
            const payload = {
                service_type: credForm.service_type,
                scope_type: credForm.scope_type,
                scope_id: credForm.scope_type === "global" ? null : credForm.scope_id || null,
                username: credForm.username,
                password: credForm.password,
                port: credForm.port ? parseInt(credForm.port, 10) : null,
                extra: credForm.extra || "{}",
            };
            if (editingCredId) {
                await api.put(`/service-credentials/${editingCredId}`, payload);
                toast("Credential updated", "success");
            } else {
                await api.post("/service-credentials/", payload);
                toast("Credential added", "success");
            }
            setCredForm(DEFAULT_FORM);
            setEditingCredId(null);
            await fetchCredentials();
        } catch (err: any) {
            toast(err.response?.data?.detail || "Failed to save credential", "error");
        } finally {
            setSavingCred(false);
        }
    };

    const handleDeleteCred = async (id: string) => {
        setDeletingCredId(id);
        try {
            await api.delete(`/service-credentials/${id}`);
            toast("Credential deleted", "success");
            await fetchCredentials();
        } catch (err: any) {
            toast(err.response?.data?.detail || "Failed to delete credential", "error");
        } finally {
            setDeletingCredId(null);
        }
    };

    const handleEditCred = (cred: CredentialRead) => {
        setEditingCredId(cred.id);
        setCredForm({
            service_type: cred.service_type,
            scope_type: cred.scope_type,
            scope_id: cred.scope_id || "",
            username: cred.username,
            password: "",
            port: cred.port ? String(cred.port) : "",
            extra: cred.extra || "{}",
        });
        setShowCredPassword(false);
    };

    return (
        <div className="flex flex-col h-full">
            <div className="flex-shrink-0 px-6 py-4 flex items-center justify-between">
                <div>
                    <h1 className="text-xl font-bold text-foreground">Settings</h1>
                    <p className="text-sm text-muted-foreground mt-0.5">AI provider configuration</p>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto p-6">
            <div className="max-w-2xl mx-auto space-y-6">

                {/* AI Configuration */}
                <Card>
                    <CardHeader>
                        <CardTitle>AI Configuration</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <form onSubmit={handleSave} className="space-y-6">
                            <div className="space-y-2">
                                <label className="text-sm font-medium text-foreground">Provider</label>
                                <select
                                    className={SELECT_CLS}
                                    value={config.ai_provider}
                                    onChange={(e) => handleChange("ai_provider", e.target.value)}
                                >
                                    <option value="OPENAI">OpenAI</option>
                                    <option value="AZURE">Azure OpenAI</option>
                                    <option value="GEMINI">Google Gemini</option>
                                    <option value="CUSTOM">Custom / Ollama</option>
                                </select>
                            </div>

                            <div className="space-y-2">
                                <label className="text-sm font-medium text-foreground">
                                    Base URL {config.ai_provider === "CUSTOM" && "(Required for Ollama)"}
                                </label>
                                <Input
                                    placeholder={config.ai_provider === "CUSTOM" ? "http://host.docker.internal:11434/v1" : "https://api.openai.com/v1"}
                                    value={config.ai_base_url || ""}
                                    onChange={(e) => handleChange("ai_base_url", e.target.value)}
                                />
                                <p className="text-xs text-muted-foreground">
                                    {config.ai_provider === "CUSTOM"
                                        ? "For Docker, use http://host.docker.internal:11434/v1 instead of localhost."
                                        : "Required for Azure or Local LLMs."}
                                </p>
                            </div>

                            <div className="space-y-2">
                                <label className="text-sm font-medium text-foreground">
                                    API Key {config.ai_provider === "CUSTOM" && "(Optional)"}
                                </label>
                                <Input
                                    type="password"
                                    placeholder={config.ai_provider === "CUSTOM" ? "ollama" : "sk-..."}
                                    value={config.ai_api_key || ""}
                                    onChange={(e) => handleChange("ai_api_key", e.target.value)}
                                />
                            </div>

                            <div className="grid grid-cols-2 gap-4">
                                <div className="space-y-2">
                                    <label className="text-sm font-medium text-foreground">Model / Deployment</label>
                                    <Input
                                        placeholder="gpt-4o"
                                        value={config.ai_model || ""}
                                        onChange={(e) => handleChange("ai_model", e.target.value)}
                                    />
                                </div>
                                {config.ai_provider === "AZURE" && (
                                    <div className="space-y-2">
                                        <label className="text-sm font-medium text-foreground">API Version</label>
                                        <Input
                                            placeholder="2023-05-15"
                                            value={config.ai_api_version || ""}
                                            onChange={(e) => handleChange("ai_api_version", e.target.value)}
                                        />
                                    </div>
                                )}
                            </div>

                                {/* Fast Model (optional) */}
                                <div className="mt-4 border-t border-border pt-4">
                                    <p className="text-sm font-medium text-foreground mb-3">
                                        Fast Model <span className="text-muted-foreground font-normal">(optional — used for quick intent detection)</span>
                                    </p>
                                    <div className="grid grid-cols-1 gap-3">
                                        <div>
                                            <label className="block text-xs text-muted-foreground mb-1">Model Name</label>
                                            <Input
                                                placeholder={
                                                    config.ai_provider === "OPENAI" ? "gpt-4o-mini" :
                                                    config.ai_provider === "GEMINI" ? "gemini-2.0-flash" :
                                                    config.ai_provider === "AZURE" ? "gpt-4o-mini (deployment name)" :
                                                    "leave blank to disable tiering"
                                                }
                                                value={config.ai_fast_model || ""}
                                                onChange={(e) => handleChange("ai_fast_model", e.target.value)}
                                            />
                                        </div>
                                        <div>
                                            <label className="block text-xs text-muted-foreground mb-1">
                                                Endpoint URL <span className="text-muted-foreground/60">(blank = same as primary)</span>
                                            </label>
                                            <Input
                                                placeholder="Leave blank to use primary endpoint"
                                                value={config.ai_fast_base_url || ""}
                                                onChange={(e) => handleChange("ai_fast_base_url", e.target.value)}
                                            />
                                        </div>
                                        <div>
                                            <label className="block text-xs text-muted-foreground mb-1">
                                                API Key <span className="text-muted-foreground/60">(blank = same as primary)</span>
                                            </label>
                                            <Input
                                                type="password"
                                                placeholder="Leave blank to use primary API key"
                                                value={config.ai_fast_api_key || ""}
                                                onChange={(e) => handleChange("ai_fast_api_key", e.target.value)}
                                            />
                                        </div>
                                    </div>
                                </div>

                                {/* ── Context Window ─────────────────────────────── */}
                                <div className="pt-4 border-t border-border">
                                    <h3 className="text-sm font-medium text-foreground mb-3">Context Window</h3>
                                    <div className="grid grid-cols-3 gap-3">
                                        <div>
                                            <label className="text-xs text-muted-foreground block mb-1">
                                                Tool Result Budget (tokens)
                                            </label>
                                            <input
                                                type="number"
                                                min={500}
                                                max={16000}
                                                value={config.ctx_tool_budget || "3000"}
                                                onChange={(e) => handleChange("ctx_tool_budget", e.target.value)}
                                                className="w-full bg-background border border-border rounded px-2 py-1.5 text-sm text-foreground outline-none focus:border-primary"
                                            />
                                            <p className="text-xs text-muted-foreground mt-0.5">
                                                Max tokens per tool result before summarization
                                            </p>
                                        </div>
                                        <div>
                                            <label className="text-xs text-muted-foreground block mb-1">
                                                Compaction Threshold (%)
                                            </label>
                                            <input
                                                type="number"
                                                min={50}
                                                max={95}
                                                value={config.ctx_compaction_threshold || "70"}
                                                onChange={(e) => handleChange("ctx_compaction_threshold", e.target.value)}
                                                className="w-full bg-background border border-border rounded px-2 py-1.5 text-sm text-foreground outline-none focus:border-primary"
                                            />
                                            <p className="text-xs text-muted-foreground mt-0.5">
                                                Compact when conversation reaches this % of context window
                                            </p>
                                        </div>
                                        <div>
                                            <label className="text-xs text-muted-foreground block mb-1">
                                                Keep Recent Messages (pairs)
                                            </label>
                                            <input
                                                type="number"
                                                min={2}
                                                max={20}
                                                value={config.ctx_keep_recent || "6"}
                                                onChange={(e) => handleChange("ctx_keep_recent", e.target.value)}
                                                className="w-full bg-background border border-border rounded px-2 py-1.5 text-sm text-foreground outline-none focus:border-primary"
                                            />
                                            <p className="text-xs text-muted-foreground mt-0.5">
                                                Message pairs protected from compaction (1 pair = user + assistant)
                                            </p>
                                        </div>
                                    </div>
                                </div>

                            <div className="flex items-center justify-between pt-4 border-t border-border">
                                <Button type="button" variant="outline" onClick={handleTest} disabled={testing}>
                                    <PlugZap className="w-4 h-4 mr-2" />
                                    {testing ? "Testing..." : "Test Connection"}
                                </Button>
                                <Button type="submit" disabled={loading}>
                                    <Save className="w-4 h-4 mr-2" />
                                    {loading ? "Saving..." : "Save Settings"}
                                </Button>
                            </div>
                        </form>
                    </CardContent>
                </Card>

                {/* RAG / Knowledge Base */}
                <Card>
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                            <Database className="w-4 h-4" />
                            RAG / Knowledge Base
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <form onSubmit={handleSaveRag} className="space-y-5">
                            <div className="flex items-center gap-3">
                                <input
                                    type="checkbox"
                                    id="rag_enabled"
                                    checked={ragConfig.rag_enabled === "true"}
                                    onChange={(e) => handleRagChange("rag_enabled", e.target.checked ? "true" : "false")}
                                    className="w-4 h-4 rounded border-border text-primary focus:ring-primary"
                                />
                                <label htmlFor="rag_enabled" className="text-sm font-medium text-foreground">
                                    Enable RAG
                                </label>
                            </div>

                            {ragConfig.rag_enabled === "true" && (
                                <div className="space-y-4 pl-1 border-l-2 border-primary/20 ml-2">
                                    <div className="grid grid-cols-2 gap-4 pl-3">
                                        <div className="space-y-2">
                                            <label className="text-sm font-medium text-foreground">ChromaDB Host</label>
                                            <Input
                                                placeholder="localhost"
                                                value={ragConfig.rag_chroma_host}
                                                onChange={(e) => handleRagChange("rag_chroma_host", e.target.value)}
                                            />
                                        </div>
                                        <div className="space-y-2">
                                            <label className="text-sm font-medium text-foreground">ChromaDB Port</label>
                                            <Input
                                                placeholder="8001"
                                                value={ragConfig.rag_chroma_port}
                                                onChange={(e) => handleRagChange("rag_chroma_port", e.target.value)}
                                            />
                                        </div>
                                    </div>

                                    <div className="space-y-2 pl-3">
                                        <label className="text-sm font-medium text-foreground">Embedding Provider</label>
                                        <select
                                            className={SELECT_CLS}
                                            value={ragConfig.rag_embedding_provider}
                                            onChange={(e) => handleRagChange("rag_embedding_provider", e.target.value)}
                                        >
                                            <option value="local">Local (all-MiniLM-L6-v2, no cost)</option>
                                            <option value="openai">OpenAI (text-embedding-3-small)</option>
                                            <option value="azure">Azure OpenAI</option>
                                        </select>
                                    </div>

                                    {ragConfig.rag_embedding_provider !== "local" && (
                                        <div className="space-y-4 pl-3">
                                            <div className="space-y-2">
                                                <label className="text-sm font-medium text-foreground">Embedding API Key</label>
                                                <Input
                                                    type="password"
                                                    placeholder="sk-..."
                                                    value={ragConfig.rag_embedding_api_key}
                                                    onChange={(e) => handleRagChange("rag_embedding_api_key", e.target.value)}
                                                />
                                            </div>
                                            <div className="space-y-2">
                                                <label className="text-sm font-medium text-foreground">Embedding Model</label>
                                                <Input
                                                    placeholder={ragConfig.rag_embedding_provider === "openai" ? "text-embedding-3-small" : "deployment-name"}
                                                    value={ragConfig.rag_embedding_model}
                                                    onChange={(e) => handleRagChange("rag_embedding_model", e.target.value)}
                                                />
                                            </div>
                                            {ragConfig.rag_embedding_provider === "azure" && (
                                                <div className="space-y-2">
                                                    <label className="text-sm font-medium text-foreground">Embedding Base URL</label>
                                                    <Input
                                                        placeholder="https://your-resource.openai.azure.com/"
                                                        value={ragConfig.rag_embedding_base_url}
                                                        onChange={(e) => handleRagChange("rag_embedding_base_url", e.target.value)}
                                                    />
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    <div className="pl-3 pt-1">
                                        <Button type="button" variant="outline" onClick={handleTestRag} disabled={testingRag}>
                                            <PlugZap className="w-4 h-4 mr-2" />
                                            {testingRag ? "Testing..." : "Test Connection"}
                                        </Button>
                                        {ragTestStatus !== "idle" && (
                                            <span className={`ml-3 text-sm font-medium ${ragTestStatus === "ok" ? "text-emerald-400" : "text-destructive"}`}>
                                                {ragTestStatus === "ok" ? "✓" : "✗"} {ragTestMsg}
                                            </span>
                                        )}
                                    </div>
                                </div>
                            )}

                            <div className="flex justify-end pt-4 border-t border-border">
                                <Button type="submit" disabled={savingRag}>
                                    <Save className="w-4 h-4 mr-2" />
                                    {savingRag ? "Saving..." : "Save RAG Settings"}
                                </Button>
                            </div>
                        </form>
                    </CardContent>
                </Card>

                {/* OpenAI-Compatible API */}
                <Card>
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                            <PlugZap className="w-5 h-5 text-violet-400" />
                            OpenAI-Compatible API
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <p className="text-sm text-muted-foreground">
                            Expose a <code className="text-primary font-mono">/v1/chat/completions</code> endpoint so tools like Elastic,
                            n8n, or LangChain can use DokOps as an OpenAI-compatible backend with full Kubernetes agentic capabilities.
                        </p>

                        {/* Enable toggle */}
                        <div className="flex items-center justify-between">
                            <span className="text-sm text-foreground">Enable API</span>
                            <button
                                onClick={handleCompatToggle}
                                disabled={togglingCompat}
                                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                                    compatConfig.enabled ? "bg-violet-500" : "bg-muted-foreground/30"
                                }`}
                            >
                                <span
                                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                                        compatConfig.enabled ? "translate-x-6" : "translate-x-1"
                                    }`}
                                />
                            </button>
                        </div>

                        {/* Endpoint URL */}
                        {compatConfig.enabled && (
                            <div className="space-y-1">
                                <p className="text-xs text-muted-foreground">Base URL (paste into your OpenAI connector)</p>
                                <div className="flex items-center gap-2">
                                    <code className="flex-1 rounded-lg bg-muted border border-border px-3 py-2 text-sm text-primary font-mono break-all">
                                        {window.location.protocol}//{window.location.hostname}{window.location.port ? `:${window.location.port}` : ""}
                                    </code>
                                    <Button
                                        size="sm"
                                        variant="ghost"
                                        onClick={() => copyToClipboard(`${window.location.protocol}//${window.location.hostname}${window.location.port ? `:${window.location.port}` : ""}`)}
                                    >
                                        Copy
                                    </Button>
                                </div>
                                <p className="text-xs text-muted-foreground mt-1">
                                    Tip: add <code className="text-primary font-mono">cluster_id: your-context</code> to your system message to target a specific cluster.
                                </p>
                            </div>
                        )}

                        {/* API Key */}
                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-sm text-foreground">API Key</p>
                                    {compatConfig.has_key && compatConfig.created_at && (
                                        <p className="text-xs text-muted-foreground">
                                            Last generated: {new Date(compatConfig.created_at).toLocaleDateString()}
                                        </p>
                                    )}
                                </div>
                                <Button size="sm" onClick={handleGenerateKey} disabled={generatingKey}>
                                    {generatingKey ? "Generating..." : compatConfig.has_key ? "Regenerate Key" : "Generate Key"}
                                </Button>
                            </div>

                            {/* One-time key reveal */}
                            {compatKey && (
                                <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 space-y-2">
                                    <p className="text-xs text-amber-400 font-medium">
                                        Copy this key now — it will not be shown again.
                                    </p>
                                    <div className="flex items-center gap-2">
                                        <code className="flex-1 rounded-lg bg-muted border border-border px-3 py-2 text-sm text-emerald-400 font-mono break-all">
                                            {compatKeyVisible ? compatKey : "sk-dokops-••••••••••••••••••••••••••••••••"}
                                        </code>
                                        <Button size="sm" variant="ghost" onClick={() => setCompatKeyVisible(v => !v)}>
                                            {compatKeyVisible ? "Hide" : "Show"}
                                        </Button>
                                        <Button size="sm" variant="ghost" onClick={() => copyToClipboard(compatKey)}>
                                            Copy
                                        </Button>
                                    </div>
                                </div>
                            )}

                            {!compatKey && compatConfig.has_key && (
                                <p className="text-xs text-muted-foreground">
                                    A key is configured. Regenerate to get a new one (this invalidates the old key).
                                </p>
                            )}
                        </div>
                    </CardContent>
                </Card>

                {/* Registry Lookup */}
                <Card>
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                            <Database className="w-4 h-4" />
                            Registry Lookup
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <p className="text-sm text-muted-foreground">
                            When enabled, the agent can query container registries to find correct image
                            references during <code className="text-primary font-mono">ImagePullBackOff</code> errors.
                            Configure registries in{" "}
                            <a href="/integrations" className="text-primary underline">
                                Integrations → Container Registries
                            </a>.
                        </p>
                        <div className="flex items-center justify-between">
                            <span className="text-sm text-foreground">Enable Registry Lookup</span>
                            <button
                                onClick={handleRegistryToggle}
                                disabled={togglingRegistry}
                                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                                    registryEnabled ? "bg-primary" : "bg-muted-foreground/30"
                                }`}
                            >
                                <span
                                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                                        registryEnabled ? "translate-x-6" : "translate-x-1"
                                    }`}
                                />
                            </button>
                        </div>
                    </CardContent>
                </Card>

                {/* Service Credentials */}
                <Card>
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                            <KeyRound className="w-4 h-4" />
                            Service Credentials
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-6">
                        <p className="text-sm text-muted-foreground">
                            Configure credentials for on-prem middleware services. Scoped credentials override broader ones (Minion &gt; Group &gt; Global).
                        </p>

                        {/* Add / Edit form */}
                        <form onSubmit={handleSaveCred} className="space-y-4 rounded-lg border border-border p-4 bg-muted/20">
                            <p className="text-sm font-medium text-foreground">
                                {editingCredId ? "Edit Credential" : "Add Credential"}
                            </p>

                            <div className="grid grid-cols-2 gap-3">
                                <div className="space-y-1">
                                    <label className="text-xs font-medium text-muted-foreground">Service</label>
                                    <select
                                        className={SELECT_CLS}
                                        value={credForm.service_type}
                                        onChange={(e) => setCredForm(prev => ({ ...prev, service_type: e.target.value }))}
                                    >
                                        {SERVICE_TYPES.map(s => (
                                            <option key={s.value} value={s.value}>{s.label}</option>
                                        ))}
                                    </select>
                                </div>

                                <div className="space-y-1">
                                    <label className="text-xs font-medium text-muted-foreground">Scope</label>
                                    <select
                                        className={SELECT_CLS}
                                        value={credForm.scope_type}
                                        onChange={(e) => setCredForm(prev => ({ ...prev, scope_type: e.target.value as "global" | "group" | "minion", scope_id: "" }))}
                                    >
                                        <option value="global">Global</option>
                                        <option value="group">By Group</option>
                                        <option value="minion">By Minion</option>
                                    </select>
                                </div>
                            </div>

                            {credForm.scope_type === "group" && (
                                <div className="space-y-1">
                                    <label className="text-xs font-medium text-muted-foreground">Group</label>
                                    <select
                                        className={SELECT_CLS}
                                        value={credForm.scope_id}
                                        onChange={(e) => setCredForm(prev => ({ ...prev, scope_id: e.target.value }))}
                                        required
                                    >
                                        <option value="">Select group…</option>
                                        {groups.map(g => (
                                            <option key={g.id} value={g.id}>{g.name}</option>
                                        ))}
                                    </select>
                                </div>
                            )}

                            {credForm.scope_type === "minion" && (
                                <div className="space-y-1">
                                    <label className="text-xs font-medium text-muted-foreground">Minion</label>
                                    <select
                                        className={SELECT_CLS}
                                        value={credForm.scope_id}
                                        onChange={(e) => setCredForm(prev => ({ ...prev, scope_id: e.target.value }))}
                                        required
                                    >
                                        <option value="">Select minion…</option>
                                        {minions.map(m => (
                                            <option key={m.id} value={m.id}>{m.hostname} ({m.id})</option>
                                        ))}
                                    </select>
                                </div>
                            )}

                            <div className="grid grid-cols-2 gap-3">
                                <div className="space-y-1">
                                    <label className="text-xs font-medium text-muted-foreground">
                                        Username
                                        {PASSWORD_ONLY_SERVICES.has(credForm.service_type) && (
                                            <span className="ml-1 text-muted-foreground/60 font-normal">(not used for {SERVICE_TYPES.find(s => s.value === credForm.service_type)?.label})</span>
                                        )}
                                    </label>
                                    <Input
                                        placeholder={PASSWORD_ONLY_SERVICES.has(credForm.service_type) ? "n/a" : "admin"}
                                        value={credForm.username}
                                        onChange={(e) => setCredForm(prev => ({ ...prev, username: e.target.value }))}
                                        disabled={PASSWORD_ONLY_SERVICES.has(credForm.service_type)}
                                        className={PASSWORD_ONLY_SERVICES.has(credForm.service_type) ? "opacity-40 cursor-not-allowed" : ""}
                                    />
                                </div>
                                <div className="space-y-1">
                                    <label className="text-xs font-medium text-muted-foreground">
                                        Password {editingCredId && <span className="text-muted-foreground/60">(leave blank to keep existing)</span>}
                                    </label>
                                    <div className="relative">
                                        <Input
                                            type={showCredPassword ? "text" : "password"}
                                            placeholder={editingCredId ? "••••••••" : "password"}
                                            value={credForm.password}
                                            onChange={(e) => setCredForm(prev => ({ ...prev, password: e.target.value }))}
                                            required={!editingCredId}
                                            className="pr-16"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => setShowCredPassword(v => !v)}
                                            className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground hover:text-foreground"
                                        >
                                            {showCredPassword ? "Hide" : "Show"}
                                        </button>
                                    </div>
                                </div>
                            </div>

                            <div className="space-y-1">
                                <label className="text-xs font-medium text-muted-foreground">Port Override <span className="text-muted-foreground/60">(optional)</span></label>
                                <Input
                                    type="number"
                                    placeholder="Leave blank to use service default"
                                    value={credForm.port}
                                    onChange={(e) => setCredForm(prev => ({ ...prev, port: e.target.value }))}
                                    className="max-w-[200px]"
                                />
                            </div>

                            <div className="flex items-center gap-3 pt-2 border-t border-border">
                                <Button type="submit" disabled={savingCred}>
                                    <Save className="w-4 h-4 mr-2" />
                                    {savingCred ? "Saving..." : editingCredId ? "Update" : "Add Credential"}
                                </Button>
                                {editingCredId && (
                                    <Button
                                        type="button"
                                        variant="outline"
                                        onClick={() => { setEditingCredId(null); setCredForm(DEFAULT_FORM); setShowCredPassword(false); }}
                                    >
                                        Cancel
                                    </Button>
                                )}
                            </div>
                        </form>

                        {/* Credential list */}
                        {credentials.length === 0 ? (
                            <p className="text-sm text-muted-foreground text-center py-4">
                                No credentials configured yet.
                            </p>
                        ) : (
                            <div className="space-y-2">
                                {credentials.map(cred => {
                                    const serviceLabel = SERVICE_TYPES.find(s => s.value === cred.service_type)?.label ?? cred.service_type;
                                    const scopeLabel = cred.scope_type === "global"
                                        ? "Global"
                                        : cred.scope_type === "group"
                                            ? `Group: ${groups.find(g => g.id === cred.scope_id)?.name ?? cred.scope_id}`
                                            : `Minion: ${minions.find(m => m.id === cred.scope_id)?.hostname ?? cred.scope_id}`;
                                    return (
                                        <div
                                            key={cred.id}
                                            className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3 hover:border-border/70 transition-colors"
                                        >
                                            <div className="flex items-center gap-3">
                                                <span className="text-sm font-medium text-foreground">{serviceLabel}</span>
                                                <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">{scopeLabel}</span>
                                                <span className="text-sm text-muted-foreground">{cred.username}</span>
                                                <span className="text-sm text-muted-foreground font-mono tracking-widest">••••••</span>
                                            </div>
                                            <div className="flex items-center gap-2">
                                                <Button size="sm" variant="outline" onClick={() => handleEditCred(cred)}>Edit</Button>
                                                <Button size="sm" variant="ghost" onClick={() => handleDeleteCred(cred.id)} disabled={deletingCredId === cred.id} className="text-destructive hover:text-destructive hover:bg-destructive/10">{deletingCredId === cred.id ? "Deleting..." : "Delete"}</Button>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Alert Response</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-6">
                    <div>
                      <p className="text-xs text-muted-foreground mb-2">
                        Webhook URLs — copy into your monitoring systems:
                      </p>
                      {["alertmanager","grafana","datadog","pagerduty","opsgenie","elasticsearch","generic"].map((src) => (
                        <div key={src} className="flex items-center gap-2 mb-1">
                          <span className="text-xs text-muted-foreground w-24">{src}</span>
                          <code className="text-xs bg-muted border border-border px-2 py-0.5 rounded text-foreground font-mono select-all">
                            {window.location.origin}/api/v1/alerts/webhook/{src}
                          </code>
                        </div>
                      ))}
                    </div>
                    <AlertWebhookSecrets />
                    <AlertNotificationSettings />
                    <AlertRemediationPolicy />
                    <AlertSuppressionWindow />
                  </CardContent>
                </Card>

            </div>
            </div>
        </div>
    );
}
