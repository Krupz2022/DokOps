import { useState } from "react";
import { CheckCircle2, XCircle, Loader2, Plug, PlugZap, ChevronDown } from "lucide-react";
import api from "../lib/api";
import { useToast } from "../context/ToastContext";
import { cn } from "../lib/utils";

import prometheusLogo    from "../assets/logos/prometheus.svg";
import lokiLogo          from "../assets/logos/loki.png";
import grafanaLogo       from "../assets/logos/grafana.svg";
import elasticsearchLogo from "../assets/logos/elasticsearch.svg";
import datadogLogo       from "../assets/logos/datadog.svg";

const BACKEND_LOGOS: Record<string, string> = {
  prometheus:    prometheusLogo,
  loki:          lokiLogo,
  grafana:       grafanaLogo,
  elasticsearch: elasticsearchLogo,
  datadog:       datadogLogo,
};

type Backend = "prometheus" | "loki" | "grafana" | "elasticsearch" | "datadog";

interface Integration {
  id: number;
  backend: Backend;
  display_name: string;
  base_url: string;
  auth_type: string;
  is_active: boolean;
  health_status: string | null;
}

interface ConnectForm {
  display_name: string;
  base_url: string;
  auth_type: "none" | "bearer" | "basic" | "api_key";
  token?: string;
  username?: string;
  password?: string;
  api_key?: string;
  header_name?: string;
}

const BACKEND_META: Record<Backend, { label: string; placeholder: string; description: string }> = {
  prometheus:    { label: "Prometheus",     placeholder: "http://prometheus:9090",      description: "Metrics & alerting" },
  loki:          { label: "Loki",           placeholder: "http://loki:3100",            description: "Log aggregation" },
  grafana:       { label: "Grafana",        placeholder: "http://grafana:3000",         description: "Dashboards & viz" },
  elasticsearch: { label: "Elasticsearch", placeholder: "http://elasticsearch:9200",   description: "Search & analytics" },
  datadog:       { label: "Datadog",        placeholder: "https://api.datadoghq.com",   description: "APM & monitoring" },
};

const EMPTY_FORM: ConnectForm = { display_name: "", base_url: "", auth_type: "none" };

const BACKEND_AUTH_DEFAULTS: Record<Backend, Partial<ConnectForm>> = {
  prometheus:    { auth_type: "none" },
  loki:          { auth_type: "none" },
  grafana:       { auth_type: "bearer" },
  elasticsearch: { auth_type: "api_key", header_name: "Authorization" },
  datadog:       { auth_type: "api_key", header_name: "DD-API-KEY" },
};

const BACKEND_AUTH_ORDER: Record<Backend, Array<{ value: ConnectForm["auth_type"]; label: string }>> = {
  prometheus: [
    { value: "none",    label: "None (recommended)" },
    { value: "bearer",  label: "Bearer Token" },
    { value: "basic",   label: "Basic Auth" },
  ],
  loki: [
    { value: "none",    label: "None (recommended)" },
    { value: "basic",   label: "Basic Auth" },
    { value: "bearer",  label: "Bearer Token" },
  ],
  grafana: [
    { value: "bearer",  label: "Bearer Token (recommended)" },
    { value: "basic",   label: "Basic Auth" },
    { value: "none",    label: "None" },
  ],
  elasticsearch: [
    { value: "api_key", label: "API Key (recommended)" },
    { value: "basic",   label: "Basic Auth" },
    { value: "bearer",  label: "Bearer Token" },
    { value: "none",    label: "None" },
  ],
  datadog: [
    { value: "api_key", label: "API Key (recommended)" },
    { value: "none",    label: "None" },
  ],
};

type HintMap = Partial<Record<ConnectForm["auth_type"], Partial<Record<string, string>>>>;
const BACKEND_FIELD_HINTS: Record<Backend, HintMap> = {
  prometheus: {
    bearer: { token: "Grafana Cloud Prometheus: use an API token with Metrics Viewer scope." },
    basic:  { username: "Grafana Cloud: your numeric org ID.", password: "Grafana Cloud: an API token with Metrics Viewer scope." },
  },
  loki: {
    basic: { username: "Grafana Cloud: your numeric org ID (e.g. 123456).", password: "Grafana Cloud: an API token with Logs Viewer scope." },
  },
  grafana: {
    bearer: { token: "Create in Grafana → Administration → Service Accounts → Add token. Token starts with glsa_." },
    basic:  { username: "Grafana username (default: admin).", password: "Grafana password or an API token used as password." },
  },
  elasticsearch: {
    api_key: {
      header_name: "Always Authorization for Elasticsearch API keys.",
      api_key: "Elastic Cloud: copy the Encoded key from Kibana → Stack Mgmt → API Keys, then paste as: ApiKey <encoded-key>",
    },
    basic: {
      username: "Elasticsearch username (default: elastic).",
      password: "The password set during cluster setup or via Kibana user management.",
    },
  },
  datadog: {
    api_key: {
      header_name: "Always DD-API-KEY for Datadog.",
      api_key: "32-char hex key from Datadog → Organization Settings → API Keys.",
    },
  },
};

interface Props {
  backend: Backend;
  existing: Integration | undefined;
  onRefresh: () => void;
}

const inputCls = "w-full text-sm bg-background border border-border rounded-lg px-3 py-2 text-foreground outline-none focus:border-primary placeholder:text-muted-foreground/50";

export default function IntegrationObservability({ backend, existing, onRefresh }: Props) {
  const { toast } = useToast();
  const meta = BACKEND_META[backend];
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<ConnectForm>({ ...EMPTY_FORM, display_name: meta.label });
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);

  const buildCredentials = () => {
    if (form.auth_type === "bearer") return { token: form.token };
    if (form.auth_type === "basic") return { username: form.username, password: form.password };
    if (form.auth_type === "api_key") return { api_key: form.api_key, header_name: form.header_name };
    return undefined;
  };

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.post("/integrations/obs/connect", {
        backend,
        display_name: form.display_name,
        base_url: form.base_url,
        auth_type: form.auth_type,
        credentials: buildCredentials(),
      });
      toast(`${meta.label} connected`, "success");
      setShowForm(false);
      onRefresh();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      toast(typeof detail === "string" ? detail : "Connection failed", "error");
    } finally {
      setLoading(false);
    }
  };

  const handleTest = async () => {
    if (!existing) return;
    setTesting(true);
    try {
      const res = await api.post(`/integrations/obs/${existing.id}/test`);
      toast(res.data.ok ? "Connection OK" : `Test failed: ${res.data.message}`, res.data.ok ? "success" : "error");
      onRefresh();
    } finally {
      setTesting(false);
    }
  };

  const handleDisconnect = async () => {
    if (!existing) return;
    await api.delete(`/integrations/obs/${existing.id}`);
    toast(`${meta.label} disconnected`, "info");
    onRefresh();
  };

  const hint = (field: string) => {
    const text = BACKEND_FIELD_HINTS[backend]?.[form.auth_type]?.[field];
    return text ? <p className="text-xs text-muted-foreground mt-1">{text}</p> : null;
  };

  const openForm = () => {
    setForm({ ...EMPTY_FORM, display_name: meta.label, ...BACKEND_AUTH_DEFAULTS[backend] });
    setShowForm(true);
  };

  return (
    <>
      {/* Card — matches Azure card style */}
      <div className={cn(
        "rounded-xl border border-border p-5 flex flex-col gap-4",
        "bg-card dark:glass",
        "dark:hover:shadow-[0_4px_24px_hsl(0_0%_0%_/_0.4),0_0_0_1px_hsl(191_89%_55%_/_0.08)]",
        "transition-shadow duration-200"
      )}>
        {/* Header */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-muted border border-border flex items-center justify-center flex-shrink-0">
            <img src={BACKEND_LOGOS[backend]} alt={meta.label} className="w-6 h-6 object-contain" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5">
              <h3 className="font-semibold text-foreground text-sm">{meta.label}</h3>
              {existing && (
                existing.is_active
                  ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0" style={{ filter: "drop-shadow(0 0 4px rgb(52 211 153 / 0.6))" }} />
                  : <XCircle className="w-3.5 h-3.5 text-destructive flex-shrink-0" />
              )}
            </div>
            <p className="text-xs text-muted-foreground font-mono">{meta.description}</p>
          </div>
        </div>

        {/* Connected state */}
        {existing?.is_active && (
          <p className="text-xs text-emerald-500 dark:text-emerald-400 font-mono font-medium flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 dot-pulse" style={{ boxShadow: "0 0 5px rgb(52 211 153 / 0.7)" }} />
            connected · {existing.base_url}
          </p>
        )}

        {/* Actions */}
        {existing ? (
          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => openForm()}
              className={cn(
                "flex-1 text-sm text-center py-2 px-3 rounded-lg transition-all font-medium",
                "bg-primary/10 text-primary border border-primary/20",
                "hover:bg-primary/20 hover:border-primary/30"
              )}
            >
              Reconfigure
            </button>
            <button
              onClick={handleTest}
              disabled={testing}
              className="px-3 py-2 rounded-lg text-sm text-muted-foreground bg-muted hover:bg-muted/70 transition-colors"
            >
              {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : "Test"}
            </button>
            <button
              onClick={handleDisconnect}
              className="px-3 py-2 rounded-lg text-sm text-destructive bg-destructive/10 hover:bg-destructive/20 transition-colors"
            >
              Disconnect
            </button>
          </div>
        ) : (
          <button
            onClick={openForm}
            className={cn(
              "w-full text-sm text-center py-2 px-3 rounded-lg transition-all font-medium",
              "bg-primary text-primary-foreground hover:bg-primary/90",
              "dark:shadow-[0_0_16px_hsl(191_89%_55%_/_0.3)] dark:hover:shadow-[0_0_24px_hsl(191_89%_55%_/_0.45)]"
            )}
          >
            <span className="flex items-center justify-center gap-1.5">
              <PlugZap className="w-4 h-4" /> Connect
            </span>
          </button>
        )}
      </div>

      {/* Connection modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className={cn(
            "rounded-xl shadow-2xl border border-border p-6 max-w-md w-full mx-4",
            "bg-card dark:glass dark:shadow-[0_0_60px_hsl(0_0%_0%_/_0.6),0_0_0_1px_hsl(191_89%_55%_/_0.08)]"
          )}>
            <div className="flex items-center gap-3 mb-5">
              <div className="w-9 h-9 rounded-lg bg-muted border border-border flex items-center justify-center flex-shrink-0">
                <img src={BACKEND_LOGOS[backend]} alt={meta.label} className="w-5 h-5 object-contain" />
              </div>
              <h2 className="font-semibold text-foreground">Connect {meta.label}</h2>
            </div>

            <form onSubmit={handleConnect} className="space-y-3.5">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block font-mono">Display Name</label>
                  <input className={inputCls} value={form.display_name} onChange={e => setForm(f => ({ ...f, display_name: e.target.value }))} required />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block font-mono">Base URL</label>
                  <input className={inputCls} placeholder={meta.placeholder} value={form.base_url} onChange={e => setForm(f => ({ ...f, base_url: e.target.value }))} required />
                </div>
              </div>

              <div>
                <label className="text-xs text-muted-foreground mb-1 block font-mono">Auth Type</label>
                <div className="relative">
                  <select
                    className={cn(inputCls, "appearance-none pr-8")}
                    value={form.auth_type}
                    onChange={e => {
                      const auth_type = e.target.value as ConnectForm["auth_type"];
                      setForm(f => ({
                        ...EMPTY_FORM,
                        display_name: f.display_name,
                        base_url: f.base_url,
                        auth_type,
                        ...BACKEND_AUTH_DEFAULTS[backend],
                      }));
                    }}
                  >
                    {BACKEND_AUTH_ORDER[backend].map(({ value, label }) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                </div>
              </div>

              {form.auth_type === "bearer" && (
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block font-mono">Token</label>
                  <input type="password" className={inputCls} value={form.token || ""} onChange={e => setForm(f => ({ ...f, token: e.target.value }))} required />
                  {hint("token")}
                </div>
              )}
              {form.auth_type === "basic" && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block font-mono">Username</label>
                    <input className={inputCls} value={form.username || ""} onChange={e => setForm(f => ({ ...f, username: e.target.value }))} required />
                    {hint("username")}
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block font-mono">Password</label>
                    <input type="password" className={inputCls} value={form.password || ""} onChange={e => setForm(f => ({ ...f, password: e.target.value }))} required />
                    {hint("password")}
                  </div>
                </div>
              )}
              {form.auth_type === "api_key" && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block font-mono">Header Name</label>
                    <input className={inputCls} placeholder="X-API-Key" value={form.header_name || ""} onChange={e => setForm(f => ({ ...f, header_name: e.target.value }))} required />
                    {hint("header_name")}
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block font-mono">API Key</label>
                    <input type="password" className={inputCls} value={form.api_key || ""} onChange={e => setForm(f => ({ ...f, api_key: e.target.value }))} required />
                    {hint("api_key")}
                  </div>
                </div>
              )}

              <div className="flex gap-3 justify-end pt-1">
                <button
                  type="button"
                  onClick={() => setShowForm(false)}
                  className="px-4 py-2 rounded-lg text-sm text-muted-foreground hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className={cn(
                    "px-4 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2",
                    "bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50",
                    "dark:shadow-[0_0_14px_hsl(191_89%_55%_/_0.3)] dark:hover:shadow-[0_0_20px_hsl(191_89%_55%_/_0.45)]"
                  )}
                >
                  {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {loading ? "Connecting…" : <><Plug className="h-3.5 w-3.5" /> Connect</>}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
