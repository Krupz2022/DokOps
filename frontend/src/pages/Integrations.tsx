import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Cloud, Loader2, CheckCircle2, XCircle, Eye, EyeOff, Search, Package, ChevronDown, ChevronRight } from "lucide-react";
import api from "../lib/api";
import { useToast } from "../context/ToastContext";
import { cn } from "../lib/utils";
import IntegrationObservability from "./IntegrationObservability";

interface AzureStatus {
  connected: boolean;
  tenant_id: string | null;
}

interface ConnectForm {
  tenant_id: string;
  subscription_id: string;
  client_id: string;
  client_secret: string;
  resource_group: string;
  aks_cluster_name: string;
}

const EMPTY_FORM: ConnectForm = {
  tenant_id: "",
  subscription_id: "",
  client_id: "",
  client_secret: "",
  resource_group: "",
  aks_cluster_name: "",
};

interface RegistryConnection {
  id: string;
  name: string;
  url: string;
  username: string | null;
  added_by: string | null;
  created_at: string;
}

interface AddRegistryForm {
  name: string;
  url: string;
  username: string;
  password: string;
}

const BUILT_IN_REGISTRIES = [
  { name: "Docker Hub",           url: "hub.docker.com",  note: "Public, no auth" },
  { name: "GitHub Container Reg", url: "ghcr.io",          note: "Public, no auth" },
  { name: "Quay.io",              url: "quay.io",          note: "Public, no auth" },
  { name: "Kubernetes Registry",  url: "registry.k8s.io", note: "Public, no auth" },
];

const EMPTY_REGISTRY_FORM: AddRegistryForm = {
  name: "", url: "", username: "", password: "",
};

export default function Integrations() {
  const navigate = useNavigate();
  const { toast } = useToast();

  const [azureStatus, setAzureStatus] = useState<AzureStatus | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState<ConnectForm>(EMPTY_FORM);
  const [connecting, setConnecting] = useState(false);
  const [showSecret, setShowSecret] = useState(false);
  const [obsIntegrations, setObsIntegrations] = useState<any[]>([]);
  const [registries, setRegistries] = useState<RegistryConnection[]>([]);
  const [loadingRegistries, setLoadingRegistries] = useState(true);
  const [showAddRegistry, setShowAddRegistry] = useState(false);
  const [registryForm, setRegistryForm] = useState<AddRegistryForm>(EMPTY_REGISTRY_FORM);
  const [addingRegistry, setAddingRegistry] = useState(false);
  const [testingRegistry, setTestingRegistry] = useState<string | null>(null);
  const [showRegistryPw, setShowRegistryPw] = useState(false);

  // Browse modal state
  const [browseRegistry, setBrowseRegistry] = useState<RegistryConnection | null>(null);
  const [catalogRepos, setCatalogRepos] = useState<string[]>([]);
  const [catalogMessage, setCatalogMessage] = useState<string | null>(null);
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const [expandedRepo, setExpandedRepo] = useState<string | null>(null);
  const [repoTags, setRepoTags] = useState<Record<string, string[]>>({});
  const [checkImage, setCheckImage] = useState("");
  const [checkResult, setCheckResult] = useState<{ exists: boolean; image?: string; digest?: string | null; error?: string } | null>(null);
  const [checkingImage, setCheckingImage] = useState(false);

  const fetchObsIntegrations = async () => {
    try {
      const res = await api.get("/integrations/obs/");
      setObsIntegrations(res.data);
    } catch {
      setObsIntegrations([]);
    }
  };

  const fetchRegistries = async () => {
    setLoadingRegistries(true);
    try {
      const res = await api.get("/registries/");
      setRegistries(res.data as RegistryConnection[]);
    } catch {
      setRegistries([]);
    } finally {
      setLoadingRegistries(false);
    }
  };

  useEffect(() => { fetchStatus(); fetchObsIntegrations(); fetchRegistries(); }, []);

  const fetchStatus = async () => {
    setLoadingStatus(true);
    try {
      const res = await api.get("/integrations/azure/status");
      setAzureStatus({ connected: res.data.connected, tenant_id: res.data.tenant_id });
    } catch {
      setAzureStatus({ connected: false, tenant_id: null });
    } finally {
      setLoadingStatus(false);
    }
  };

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    setConnecting(true);
    try {
      await api.post("/integrations/azure/connect", form);
      toast("Azure connected successfully", "success");
      setShowModal(false);
      setForm(EMPTY_FORM);
      navigate("/integrations/azure");
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      const msg = Array.isArray(detail)
        ? detail.map((e: any) => e.msg ?? e).join(", ")
        : typeof detail === "string" ? detail : "Connection failed";
      toast(msg, "error");
    } finally {
      setConnecting(false);
    }
  };

  const handleAddRegistry = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddingRegistry(true);
    try {
      await api.post("/registries/", {
        name: registryForm.name,
        url: registryForm.url,
        username: registryForm.username || undefined,
        password: registryForm.password || undefined,
      });
      toast("Registry added", "success");
      setShowAddRegistry(false);
      setRegistryForm(EMPTY_REGISTRY_FORM);
      fetchRegistries();
    } catch (err: any) {
      toast(err.response?.data?.detail ?? "Failed to add registry", "error");
    } finally {
      setAddingRegistry(false);
    }
  };

  const handleDeleteRegistry = async (id: string) => {
    try {
      await api.delete(`/registries/${id}`);
      toast("Registry removed", "success");
      fetchRegistries();
    } catch {
      toast("Failed to remove registry", "error");
    }
  };

  const handleTestRegistry = async (id: string) => {
    setTestingRegistry(id);
    try {
      const res = await api.post(`/registries/${id}/test`);
      const data = res.data as { ok: boolean; message: string };
      toast(data.ok ? `Connected: ${data.message}` : `Failed: ${data.message}`, data.ok ? "success" : "error");
    } catch {
      toast("Test failed", "error");
    } finally {
      setTestingRegistry(null);
    }
  };

  const openBrowse = (reg: RegistryConnection) => {
    setBrowseRegistry(reg);
    setCatalogRepos([]);
    setCatalogMessage(null);
    setExpandedRepo(null);
    setRepoTags({});
    setCheckImage("");
    setCheckResult(null);
  };

  const closeBrowse = () => {
    setBrowseRegistry(null);
  };

  const handleLoadCatalog = async () => {
    if (!browseRegistry) return;
    setLoadingCatalog(true);
    setCatalogMessage(null);
    try {
      const res = await api.get(`/registries/${browseRegistry.id}/catalog`);
      const data = res.data as { repositories: string[]; message: string | null };
      setCatalogRepos(data.repositories);
      setCatalogMessage(data.message ?? null);
    } catch {
      toast("Failed to load catalog", "error");
    } finally {
      setLoadingCatalog(false);
    }
  };

  const handleToggleRepo = (repo: string) => {
    setExpandedRepo((prev) => (prev === repo ? null : repo));
    setRepoTags((prev) => ({ ...prev, [repo]: prev[repo] ?? [] }));
  };

  const handleCheckImage = async () => {
    if (!browseRegistry || !checkImage.trim()) return;
    setCheckingImage(true);
    setCheckResult(null);
    try {
      const res = await api.post(`/registries/${browseRegistry.id}/check-image`, { image: checkImage.trim() });
      setCheckResult(res.data as { exists: boolean; image: string; digest: string | null });
    } catch (err: any) {
      toast(err.response?.data?.detail ?? "Check failed", "error");
    } finally {
      setCheckingImage(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Page header */}
      <div className="flex-shrink-0 px-6 py-4 border-b border-border/60">
        <h1 className="text-base font-semibold text-foreground tracking-tight">Integrations</h1>
        <p className="text-xs text-muted-foreground font-mono mt-0.5">
          Connect external services to unlock additional features
        </p>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 max-w-4xl">

          {/* Azure card */}
          <div className={cn(
            "rounded-xl border border-border p-5 flex flex-col gap-4",
            "bg-card dark:glass",
            "dark:hover:shadow-[0_4px_24px_hsl(0_0%_0%_/_0.4),0_0_0_1px_hsl(191_89%_55%_/_0.08)]",
            "transition-shadow duration-200"
          )}>
            <div className="flex items-center gap-3">
              {/* Azure icon */}
              <div className="w-10 h-10 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center flex-shrink-0">
                <Cloud className="h-5 w-5 text-primary" />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="font-semibold text-foreground text-sm">Azure</h3>
                <p className="text-xs text-muted-foreground font-mono">Cost, Monitor, Advisor</p>
              </div>
              {!loadingStatus && (
                azureStatus?.connected
                  ? <CheckCircle2 className="h-4 w-4 text-emerald-500 flex-shrink-0" style={{ filter: "drop-shadow(0 0 4px rgb(52 211 153 / 0.6))" }} />
                  : <XCircle className="h-4 w-4 text-muted-foreground/30 flex-shrink-0" />
              )}
            </div>

            {loadingStatus ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono">
                <Loader2 className="h-3 w-3 animate-spin" />
                checking status…
              </div>
            ) : azureStatus?.connected ? (
              <div className="space-y-2">
                <p className="text-xs text-emerald-500 dark:text-emerald-400 font-mono font-medium flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 dot-pulse" style={{ boxShadow: "0 0 5px rgb(52 211 153 / 0.7)" }} />
                  connected
                </p>
                <button
                  onClick={() => navigate("/integrations/azure")}
                  className={cn(
                    "w-full text-sm text-center py-2 px-3 rounded-lg transition-all font-medium",
                    "bg-primary/10 text-primary border border-primary/20",
                    "hover:bg-primary/20 hover:border-primary/30",
                    "dark:shadow-[0_0_12px_hsl(191_89%_55%_/_0.1)] dark:hover:shadow-[0_0_18px_hsl(191_89%_55%_/_0.2)]"
                  )}
                >
                  Manage →
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowModal(true)}
                className={cn(
                  "w-full text-sm text-center py-2 px-3 rounded-lg transition-all font-medium",
                  "bg-primary text-primary-foreground hover:bg-primary/90",
                  "dark:shadow-[0_0_16px_hsl(191_89%_55%_/_0.3)] dark:hover:shadow-[0_0_24px_hsl(191_89%_55%_/_0.45)]"
                )}
              >
                Connect
              </button>
            )}
          </div>

          {/* Future providers placeholder */}
          <div className="rounded-xl border border-dashed border-border/60 bg-secondary/20 p-5 flex items-center justify-center">
            <p className="text-xs text-muted-foreground/50 font-mono">more integrations coming soon</p>
          </div>
        </div>

        {/* Observability Integrations */}
        <div className="mt-8 max-w-4xl">
          <h2 className="text-base font-semibold text-foreground tracking-tight">Observability Backends</h2>
          <p className="text-xs text-muted-foreground font-mono mt-0.5 mb-4">Connect observability tools so the AI can query metrics, logs, and traces during investigations.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {(["prometheus", "loki", "grafana", "elasticsearch", "datadog"] as const).map(backend => (
              <IntegrationObservability
                key={backend}
                backend={backend}
                existing={obsIntegrations.find(i => i.backend === backend)}
                onRefresh={fetchObsIntegrations}
              />
            ))}
          </div>
        </div>

        {/* Container Registries */}
        <div className="mt-8 max-w-4xl">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-lg font-semibold text-foreground">Container Registries</h2>
              <p className="text-sm text-muted-foreground mt-1">
                Built-in public registries are always available. Add private registries (ACR, ECR, Harbor) here.
                Enable Registry Lookup in{" "}
                <a href="/settings" className="text-primary underline">Settings</a>.
              </p>
            </div>
            <button
              onClick={() => setShowAddRegistry(true)}
              className="flex items-center gap-2 px-3 py-1.5 bg-primary text-primary-foreground rounded-lg text-sm hover:bg-primary/90 transition-colors"
            >
              + Add Registry
            </button>
          </div>

          <div className="rounded-lg border border-border overflow-hidden">
            {/* Built-in registries */}
            {BUILT_IN_REGISTRIES.map((r) => (
              <div key={r.url} className="flex items-center justify-between px-4 py-3 border-b border-border last:border-0 bg-muted/20">
                <div>
                  <span className="text-sm font-medium text-foreground">{r.name}</span>
                  <span className="ml-3 text-xs text-muted-foreground font-mono">{r.url}</span>
                </div>
                <span className="text-xs text-muted-foreground bg-secondary/40 px-2 py-0.5 rounded">
                  built-in · {r.note}
                </span>
              </div>
            ))}

            {/* User-configured registries */}
            {loadingRegistries ? (
              <div className="px-4 py-3 text-sm text-muted-foreground">Loading…</div>
            ) : registries.length === 0 ? (
              <div className="px-4 py-3 text-sm text-muted-foreground italic">
                No private registries configured yet.
              </div>
            ) : (
              registries.map((r) => (
                <div key={r.id} className="flex items-center justify-between px-4 py-3 border-t border-border">
                  <div>
                    <span className="text-sm font-medium text-foreground">{r.name}</span>
                    <span className="ml-3 text-xs text-muted-foreground font-mono">{r.url}</span>
                    {r.username && (
                      <span className="ml-2 text-xs text-muted-foreground">({r.username})</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => openBrowse(r)}
                      className="text-xs px-2 py-1 rounded border border-primary/40 text-primary hover:bg-primary/10 transition-colors flex items-center gap-1"
                    >
                      <Search className="w-3 h-3" /> Browse
                    </button>
                    <button
                      onClick={() => handleTestRegistry(r.id)}
                      disabled={testingRegistry === r.id}
                      className="text-xs px-2 py-1 rounded border border-border text-foreground hover:bg-secondary/40 transition-colors disabled:opacity-50"
                    >
                      {testingRegistry === r.id ? "Testing…" : "Test"}
                    </button>
                    <button
                      onClick={() => handleDeleteRegistry(r.id)}
                      className="text-xs px-2 py-1 rounded border border-destructive/50 text-destructive hover:bg-destructive/10 transition-colors"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Browse Registry Modal */}
        {browseRegistry && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
            <div className="bg-background border border-border rounded-xl p-6 w-full max-w-lg shadow-xl flex flex-col gap-4 max-h-[85vh] overflow-y-auto">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Package className="w-4 h-4 text-primary" />
                  <h3 className="text-base font-semibold text-foreground">{browseRegistry.name}</h3>
                  <span className="text-xs text-muted-foreground font-mono">{browseRegistry.url}</span>
                </div>
                <button onClick={closeBrowse} className="text-muted-foreground hover:text-foreground text-lg leading-none">&times;</button>
              </div>

              {/* Image Check */}
              <div>
                <p className="text-xs text-muted-foreground mb-2 font-medium uppercase tracking-wide">Verify Image</p>
                <div className="flex gap-2">
                  <input
                    value={checkImage}
                    onChange={(e) => setCheckImage(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleCheckImage()}
                    placeholder="myapp:v1.2.3  or  myapp (defaults to :latest)"
                    className="flex-1 bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                  <button
                    onClick={handleCheckImage}
                    disabled={checkingImage || !checkImage.trim()}
                    className="px-3 py-2 bg-primary text-primary-foreground rounded-lg text-sm hover:bg-primary/90 disabled:opacity-50 transition-colors flex items-center gap-1"
                  >
                    {checkingImage ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
                    Check
                  </button>
                </div>
                {checkResult && (
                  <div className={cn(
                    "mt-2 rounded-lg px-3 py-2 text-sm border flex items-start gap-2",
                    checkResult.exists
                      ? "border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-400"
                      : "border-destructive/30 bg-destructive/10 text-destructive"
                  )}>
                    {checkResult.exists
                      ? <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
                      : <XCircle className="w-4 h-4 mt-0.5 shrink-0" />}
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">{checkResult.exists ? "Image found" : "Image not found"}</p>
                      {checkResult.image && <p className="text-xs opacity-70 font-mono break-all mt-0.5">{checkResult.image}</p>}
                      {checkResult.digest && <p className="text-xs opacity-60 font-mono break-all mt-0.5">digest: {checkResult.digest}</p>}
                      {checkResult.error && <p className="text-xs opacity-70 break-all mt-0.5">{checkResult.error}</p>}
                    </div>
                  </div>
                )}
              </div>

              {/* Catalog Browser */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide">Repository Catalog</p>
                  <button
                    onClick={handleLoadCatalog}
                    disabled={loadingCatalog}
                    className="text-xs px-2 py-1 rounded border border-border text-foreground hover:bg-secondary/40 transition-colors disabled:opacity-50 flex items-center gap-1"
                  >
                    {loadingCatalog ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                    {loadingCatalog ? "Loading…" : "Load Repositories"}
                  </button>
                </div>
                {catalogRepos.length === 0 && !loadingCatalog && !catalogMessage && (
                  <p className="text-xs text-muted-foreground italic">Click "Load Repositories" to list images in this registry.</p>
                )}
                {catalogMessage && catalogRepos.length === 0 && !loadingCatalog && (
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
                    {catalogMessage}
                  </div>
                )}
                {catalogRepos.length > 0 && (
                  <div className="rounded-lg border border-border divide-y divide-border overflow-hidden">
                    {catalogRepos.map((repo) => (
                      <div key={repo}>
                        <button
                          onClick={() => handleToggleRepo(repo)}
                          className="w-full flex items-center gap-2 px-3 py-2 text-sm text-foreground hover:bg-secondary/30 transition-colors text-left"
                        >
                          {expandedRepo === repo
                            ? <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                            : <ChevronRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />}
                          <span className="font-mono">{repo}</span>
                          <span className="ml-auto text-xs text-muted-foreground">
                            {browseRegistry.url}/{repo}
                          </span>
                        </button>
                        {expandedRepo === repo && repoTags[repo] && (
                          <div className="px-8 pb-2 pt-1 bg-muted/20 text-xs text-muted-foreground">
                            <p className="mb-1 font-medium">Tip: use the Verify Image field above with <span className="font-mono">{repo}:&lt;tag&gt;</span> to confirm a specific tag exists.</p>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Add Registry Modal */}
        {showAddRegistry && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
            <div className="bg-background border border-border rounded-xl p-6 w-full max-w-md shadow-xl">
              <h3 className="text-base font-semibold text-foreground mb-4">Add Container Registry</h3>
              <form onSubmit={handleAddRegistry} className="space-y-4">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Display Name *</label>
                  <input
                    required
                    value={registryForm.name}
                    onChange={(e) => setRegistryForm((p) => ({ ...p, name: e.target.value }))}
                    placeholder="My ACR"
                    className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Registry URL *</label>
                  <input
                    required
                    value={registryForm.url}
                    onChange={(e) => setRegistryForm((p) => ({ ...p, url: e.target.value }))}
                    placeholder="mycompany.azurecr.io"
                    className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                  <p className="text-xs text-muted-foreground mt-1">Hostname only — no https:// prefix.</p>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Username (optional)</label>
                  <input
                    value={registryForm.username}
                    onChange={(e) => setRegistryForm((p) => ({ ...p, username: e.target.value }))}
                    placeholder="serviceaccount"
                    className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Password / Token (optional)</label>
                  <div className="relative">
                    <input
                      type={showRegistryPw ? "text" : "password"}
                      value={registryForm.password}
                      onChange={(e) => setRegistryForm((p) => ({ ...p, password: e.target.value }))}
                      placeholder="••••••••"
                      className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary pr-9"
                    />
                    <button
                      type="button"
                      onClick={() => setShowRegistryPw((p) => !p)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      {showRegistryPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">Stored encrypted at rest. Never returned in API responses.</p>
                </div>
                <div className="flex gap-2 pt-2">
                  <button
                    type="submit"
                    disabled={addingRegistry}
                    className="flex-1 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
                  >
                    {addingRegistry ? "Adding…" : "Add Registry"}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setShowAddRegistry(false); setRegistryForm(EMPTY_REGISTRY_FORM); }}
                    className="flex-1 py-2 border border-border text-foreground rounded-lg text-sm hover:bg-secondary/40 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Connection modal */}
        {showModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
            <div className={cn(
              "rounded-xl shadow-2xl border border-border p-6 max-w-md w-full mx-4",
              "bg-card dark:glass dark:shadow-[0_0_60px_hsl(0_0%_0%_/_0.6),0_0_0_1px_hsl(191_89%_55%_/_0.08)]"
            )}>
              <div className="flex items-center gap-3 mb-5">
                <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
                  <Cloud className="h-4 w-4 text-primary" />
                </div>
                <h2 className="font-semibold text-foreground">Connect Azure</h2>
              </div>

              <form onSubmit={handleConnect} className="space-y-3.5">
                {(
                  [
                    { field: "tenant_id",        label: "Tenant ID",                    placeholder: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" },
                    { field: "subscription_id",  label: "Subscription ID",              placeholder: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" },
                    { field: "client_id",        label: "Client ID (App ID)",           placeholder: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" },
                    { field: "resource_group",   label: "Resource Group (optional)",    placeholder: "Leave blank for subscription-wide scope" },
                    { field: "aks_cluster_name", label: "AKS Cluster Name (optional)",  placeholder: "my-aks-cluster" },
                  ] as const
                ).map(({ field, label, placeholder }) => (
                  <div key={field}>
                    <label className="block text-xs font-mono font-medium text-muted-foreground mb-1">
                      {label}
                    </label>
                    <input
                      type="text"
                      value={form[field as keyof ConnectForm]}
                      onChange={(e) => setForm((f) => ({ ...f, [field]: e.target.value }))}
                      placeholder={placeholder}
                      className={cn(
                        "w-full px-3 py-2 text-sm rounded-lg border border-border transition-colors",
                        "bg-background text-foreground placeholder:text-muted-foreground/40 font-mono",
                        "outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20"
                      )}
                    />
                  </div>
                ))}

                {/* Client secret */}
                <div>
                  <label className="block text-xs font-mono font-medium text-muted-foreground mb-1">
                    Client Secret
                  </label>
                  <div className="relative">
                    <input
                      type={showSecret ? "text" : "password"}
                      value={form.client_secret}
                      onChange={(e) => setForm((f) => ({ ...f, client_secret: e.target.value }))}
                      placeholder="Enter client secret"
                      required
                      className={cn(
                        "w-full px-3 py-2 pr-10 text-sm rounded-lg border border-border transition-colors",
                        "bg-background text-foreground placeholder:text-muted-foreground/40 font-mono",
                        "outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20"
                      )}
                    />
                    <button
                      type="button"
                      onClick={() => setShowSecret((s) => !s)}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                <div className="flex gap-3 justify-end pt-2">
                  <button
                    type="button"
                    onClick={() => { setShowModal(false); setForm(EMPTY_FORM); }}
                    className="px-4 py-2 rounded-lg text-sm text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={connecting}
                    className={cn(
                      "px-4 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2",
                      "bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50",
                      "dark:shadow-[0_0_14px_hsl(191_89%_55%_/_0.3)] dark:hover:shadow-[0_0_20px_hsl(191_89%_55%_/_0.45)]"
                    )}
                  >
                    {connecting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                    {connecting ? "Connecting…" : "Connect →"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
