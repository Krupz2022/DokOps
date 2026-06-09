import { useState } from "react";
import { X, Cloud, Wand2, Copy, Check, AlertCircle, Loader2, FileKey, Server, Search } from "lucide-react";
import api from "../../lib/api";
import { cn } from "../../lib/utils";

interface Props {
  onClose: () => void;
  onAdded: () => void;
}

type Method = "picker" | "cloud" | "token" | "kubeconfig";
type CloudProvider = "azure" | "aws";

interface DiscoveredCluster {
  name: string;
  resource_group?: string;
  region?: string;
  location?: string;
  status?: string;
  provisioning_state?: string;
  node_count?: number;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button
      type="button"
      onClick={copy}
      className="flex items-center gap-1 text-[10px] font-mono text-cyan-500 hover:text-cyan-400 bg-cyan-500/10 hover:bg-cyan-500/20 px-2 py-1 rounded transition-colors flex-shrink-0"
    >
      {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center gap-2 mb-6">
      {Array.from({ length: total }).map((_, i) => (
        <div key={i} className="flex items-center gap-2 flex-1 last:flex-none">
          <div
            className={cn(
              "w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0 transition-colors",
              i < current
                ? "bg-emerald-500 text-white"
                : i === current
                ? "bg-cyan-500 text-white"
                : "bg-secondary text-muted-foreground/40"
            )}
          >
            {i < current ? <Check className="w-3 h-3" /> : i + 1}
          </div>
          {i < total - 1 && (
            <div className={cn("h-px flex-1 transition-colors", i < current ? "bg-emerald-500/60" : "bg-border")} />
          )}
        </div>
      ))}
    </div>
  );
}

const inputCls =
  "w-full bg-background border border-border text-foreground text-sm font-mono rounded px-3 py-2 focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 placeholder:text-muted-foreground/40";

const labelCls = "block text-[10px] font-mono text-muted-foreground/60 uppercase tracking-wider mb-1.5";

export default function AddClusterModal({ onClose, onAdded }: Props) {
  const [method, setMethod] = useState<Method>("picker");

  const [cloudProvider, setCloudProvider] = useState<CloudProvider>("azure");
  const [cloudForm, setCloudForm] = useState({
    subscription_id: "",
    tenant_id: "",
    client_id: "",
    client_secret: "",
    access_key_id: "",
    secret_access_key: "",
    region: "us-east-1",
  });
  const [credentialId, setCredentialId] = useState<string | null>(null);
  const [discovered, setDiscovered] = useState<DiscoveredCluster[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [cloudStep, setCloudStep] = useState<"creds" | "discover">("creds");
  const [discoverSearch, setDiscoverSearch] = useState("");

  const [tokenStep, setTokenStep] = useState(0);
  const [tokenForm, setTokenForm] = useState({ name: "", api_server: "", token: "" });
  const [kubeconfigFile, setKubeconfigFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const manifestCmd = `kubectl apply -f ${window.location.origin}/api/v1/clusters/manifest`;
  const tokenCmd = `kubectl get secret dokops-token -n dokops -o jsonpath='{.data.token}' | base64 -d`;

  async function handleCloudCredentials() {
    setLoading(true);
    setError("");
    try {
      const endpoint =
        cloudProvider === "azure"
          ? "/clusters/cloud/credentials/azure"
          : "/clusters/cloud/credentials/aws";
      const body =
        cloudProvider === "azure"
          ? {
              subscription_id: cloudForm.subscription_id,
              tenant_id: cloudForm.tenant_id,
              client_id: cloudForm.client_id,
              client_secret: cloudForm.client_secret,
            }
          : {
              access_key_id: cloudForm.access_key_id,
              secret_access_key: cloudForm.secret_access_key,
              region: cloudForm.region,
            };
      const res = await api.post(endpoint, body);
      const cid: string = res.data.id;
      setCredentialId(cid);
      const disc = await api.get(`/clusters/cloud/${cid}/discover`);
      setDiscovered(disc.data);
      setCloudStep("discover");
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setError(err.response?.data?.detail || "Failed to discover clusters");
    } finally {
      setLoading(false);
    }
  }

  async function handleImportSelected() {
    if (!credentialId) return;
    setLoading(true);
    setError("");
    try {
      for (const name of selected) {
        const cluster = discovered.find((c) => c.name === name);
        if (!cluster) continue;
        if (cloudProvider === "azure") {
          await api.post(`/clusters/cloud/${credentialId}/import/aks`, {
            cluster_name: name,
            resource_group: cluster.resource_group || "",
          });
        } else {
          await api.post(`/clusters/cloud/${credentialId}/import/eks`, { cluster_name: name });
        }
      }
      onAdded();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setError(err.response?.data?.detail || "Import failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleKubeconfigUpload() {
    if (!kubeconfigFile) return;
    setLoading(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("file", kubeconfigFile);
      await api.post("/clusters/upload/kubeconfig", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      onAdded();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setError(err.response?.data?.detail || "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifyToken() {
    setLoading(true);
    setError("");
    try {
      await api.post("/clusters/connect/token", {
        name: tokenForm.name,
        api_server: tokenForm.api_server,
        token: tokenForm.token,
        provider: "generic",
      });
      onAdded();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setError(err.response?.data?.detail || "Connection failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-card border border-border rounded-xl w-full max-w-xl mx-4 shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div>
            <h2 className="text-sm font-semibold text-foreground">Add a Cluster</h2>
            <p className="text-[11px] text-muted-foreground mt-0.5">Connect any Kubernetes cluster to DokOps</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-6">
          {/* Method Picker */}
          {method === "picker" && (
            <div className="flex flex-col gap-3">
              <button
                type="button"
                onClick={() => setMethod("cloud")}
                className="flex items-center gap-4 bg-secondary/30 hover:bg-secondary/60 border border-border hover:border-primary/30 rounded-lg p-4 text-left transition-all"
              >
                <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center flex-shrink-0">
                  <Cloud className="w-5 h-5 text-cyan-500" />
                </div>
                <div className="flex-1">
                  <div className="text-sm font-semibold text-foreground">Cloud Auto-Discovery</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">Azure AKS · AWS EKS — sign in once, pick clusters</div>
                </div>
                <span className="text-[10px] font-semibold text-cyan-500 bg-cyan-500/10 px-2 py-0.5 rounded">Fastest</span>
              </button>

              <button
                type="button"
                onClick={() => setMethod("token")}
                className="flex items-center gap-4 bg-secondary/30 hover:bg-secondary/60 border border-border hover:border-emerald-500/30 rounded-lg p-4 text-left transition-all"
              >
                <div className="w-10 h-10 rounded-lg bg-emerald-500/10 flex items-center justify-center flex-shrink-0">
                  <Wand2 className="w-5 h-5 text-emerald-500" />
                </div>
                <div className="flex-1">
                  <div className="text-sm font-semibold text-foreground">Guided Token Setup</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">Any cluster including on-prem · 2 kubectl commands</div>
                </div>
                <span className="text-[10px] font-semibold text-muted-foreground bg-secondary px-2 py-0.5 rounded">Universal</span>
              </button>

              <button
                type="button"
                onClick={() => setMethod("kubeconfig")}
                className="flex items-center gap-4 bg-secondary/30 hover:bg-secondary/60 border border-border hover:border-violet-500/30 rounded-lg p-4 text-left transition-all"
              >
                <div className="w-10 h-10 rounded-lg bg-violet-500/10 flex items-center justify-center flex-shrink-0">
                  <FileKey className="w-5 h-5 text-violet-500" />
                </div>
                <div className="flex-1">
                  <div className="text-sm font-semibold text-foreground">Kubeconfig File</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">Upload your existing kubeconfig directly</div>
                </div>
                <span className="text-[10px] font-semibold text-muted-foreground bg-secondary px-2 py-0.5 rounded">Advanced</span>
              </button>
            </div>
          )}

          {/* Cloud Path */}
          {method === "cloud" && (
            <div>
              {cloudStep === "creds" && (
                <>
                  <div className="flex gap-2 mb-4">
                    {(["azure", "aws"] as CloudProvider[]).map((p) => (
                      <button
                        key={p}
                        type="button"
                        onClick={() => setCloudProvider(p)}
                        className={cn(
                          "px-3 py-1.5 rounded text-xs font-semibold transition-colors",
                          cloudProvider === p
                            ? "bg-primary text-primary-foreground"
                            : "bg-secondary text-muted-foreground hover:text-foreground"
                        )}
                      >
                        {p === "azure" ? "Azure AKS" : "AWS EKS"}
                      </button>
                    ))}
                  </div>
                  <div className="flex flex-col gap-3">
                    {cloudProvider === "azure" ? (
                      <>
                        {(["subscription_id", "tenant_id", "client_id", "client_secret"] as const).map((f) => (
                          <div key={f}>
                            <label className={labelCls}>{f.replace(/_/g, " ")}</label>
                            <input
                              type={f === "client_secret" ? "password" : "text"}
                              value={cloudForm[f]}
                              onChange={(e) => setCloudForm((prev) => ({ ...prev, [f]: e.target.value }))}
                              className={inputCls}
                            />
                          </div>
                        ))}
                      </>
                    ) : (
                      <>
                        {(["access_key_id", "secret_access_key", "region"] as const).map((f) => (
                          <div key={f}>
                            <label className={labelCls}>{f.replace(/_/g, " ")}</label>
                            <input
                              type={f === "secret_access_key" ? "password" : "text"}
                              value={cloudForm[f]}
                              onChange={(e) => setCloudForm((prev) => ({ ...prev, [f]: e.target.value }))}
                              className={inputCls}
                            />
                          </div>
                        ))}
                      </>
                    )}
                  </div>
                </>
              )}

              {cloudStep === "discover" && (() => {
                const filtered = discovered.filter(c =>
                  c.name.toLowerCase().includes(discoverSearch.toLowerCase())
                );
                const allFilteredSelected = filtered.length > 0 && filtered.every(c => selected.has(c.name));
                return (
                  <div className="flex flex-col gap-2">
                    {/* Search + Select All toolbar */}
                    <div className="flex items-center gap-2 mb-1">
                      <div className="relative flex-1">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/50 pointer-events-none" />
                        <input
                          type="text"
                          value={discoverSearch}
                          onChange={e => setDiscoverSearch(e.target.value)}
                          placeholder="Filter clusters…"
                          className="w-full bg-secondary/40 border border-border rounded-lg pl-8 pr-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:border-primary/40"
                        />
                      </div>
                      <button
                        type="button"
                        onClick={() => setSelected(prev => {
                          const s = new Set(prev);
                          if (allFilteredSelected) {
                            filtered.forEach(c => s.delete(c.name));
                          } else {
                            filtered.forEach(c => s.add(c.name));
                          }
                          return s;
                        })}
                        className="px-2.5 py-1.5 text-xs font-medium border border-border rounded-lg text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors whitespace-nowrap"
                      >
                        {allFilteredSelected ? "Deselect All" : "Select All"}
                      </button>
                    </div>

                    <div className="text-[10px] text-muted-foreground mb-1">
                      {filtered.length} of {discovered.length} clusters · {selected.size} selected
                    </div>

                    <div className="max-h-56 overflow-y-auto flex flex-col gap-2 pr-1">
                      {filtered.length === 0 ? (
                        <p className="text-xs text-muted-foreground text-center py-6">No clusters match "{discoverSearch}"</p>
                      ) : filtered.map((c) => (
                        <button
                          key={c.name}
                          type="button"
                          onClick={() =>
                            setSelected((prev) => {
                              const s = new Set(prev);
                              s.has(c.name) ? s.delete(c.name) : s.add(c.name);
                              return s;
                            })
                          }
                          className={cn(
                            "flex items-center gap-3 p-3 rounded-lg border text-left transition-all",
                            selected.has(c.name)
                              ? "border-primary/50 bg-primary/5"
                              : "border-border bg-secondary/20 hover:bg-secondary/40"
                          )}
                        >
                          <div
                            className={cn(
                              "w-4 h-4 rounded flex items-center justify-center flex-shrink-0 transition-colors",
                              selected.has(c.name) ? "bg-primary" : "bg-secondary border border-border"
                            )}
                          >
                            {selected.has(c.name) && <Check className="w-2.5 h-2.5 text-primary-foreground" />}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="text-sm text-foreground font-medium truncate">{c.name}</div>
                            <div className="text-[11px] text-muted-foreground">
                              {c.resource_group || c.region} · {c.node_count != null ? `${c.node_count} nodes` : ""}
                            </div>
                          </div>
                          <span
                            className={cn(
                              "text-[10px] px-2 py-0.5 rounded font-semibold shrink-0",
                              c.provisioning_state === "Succeeded" || c.status === "ACTIVE"
                                ? "bg-emerald-500/10 text-emerald-500"
                                : "bg-amber-500/10 text-amber-500"
                            )}
                          >
                            {c.provisioning_state || c.status || "UNKNOWN"}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })()}

              {error && (
                <div className="flex items-center gap-2 mt-3 text-xs text-destructive bg-destructive/10 border border-destructive/20 px-3 py-2 rounded font-mono">
                  <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                  {error}
                </div>
              )}

              <div className="flex gap-2 mt-4">
                <button
                  type="button"
                  onClick={() => {
                    setMethod("picker");
                    setCloudStep("creds");
                    setError("");
                    setCredentialId(null);
                    setDiscovered([]);
                    setSelected(new Set());
                  }}
                  className="flex-1 py-2 text-xs text-muted-foreground hover:text-foreground bg-secondary/50 hover:bg-secondary rounded transition-colors"
                >
                  Back
                </button>
                {cloudStep === "creds" ? (
                  <button
                    type="button"
                    onClick={handleCloudCredentials}
                    disabled={
                      loading ||
                      (cloudProvider === "azure"
                        ? !cloudForm.subscription_id || !cloudForm.tenant_id || !cloudForm.client_id || !cloudForm.client_secret
                        : !cloudForm.access_key_id || !cloudForm.secret_access_key)
                    }
                    className="flex-1 py-2 text-xs font-semibold text-primary-foreground bg-primary hover:bg-primary/90 rounded transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                  >
                    {loading ? <><Loader2 className="w-3.5 h-3.5 animate-spin" />Discovering...</> : "Discover Clusters →"}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleImportSelected}
                    disabled={loading || selected.size === 0}
                    className="flex-1 py-2 text-xs font-semibold text-primary-foreground bg-primary hover:bg-primary/90 rounded transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                  >
                    {loading ? <><Loader2 className="w-3.5 h-3.5 animate-spin" />Importing...</> : `Import Selected (${selected.size}) →`}
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Kubeconfig Path */}
          {method === "kubeconfig" && (
            <div>
              <p className="text-sm text-foreground font-semibold mb-1">Upload kubeconfig file</p>
              <p className="text-xs text-muted-foreground mb-4 leading-relaxed">
                The file must contain a bearer token. Exec-based auth (aws-iam-authenticator, gke-gcloud-auth-plugin) is not supported — use Cloud Auto-Discovery for those.
              </p>
              <label
                htmlFor="kubeconfig-upload"
                className="flex flex-col items-center justify-center gap-3 border-2 border-dashed border-border hover:border-violet-500/40 rounded-lg p-8 cursor-pointer transition-colors bg-secondary/20 hover:bg-secondary/40"
              >
                <Server className="w-8 h-8 text-muted-foreground/40" />
                <span className="text-sm text-muted-foreground">
                  {kubeconfigFile ? kubeconfigFile.name : "Click to select kubeconfig file"}
                </span>
                {kubeconfigFile && (
                  <span className="text-[10px] text-violet-500 font-mono">{(kubeconfigFile.size / 1024).toFixed(1)} KB</span>
                )}
                <input
                  id="kubeconfig-upload"
                  type="file"
                  className="hidden"
                  accept=".yaml,.yml,.conf,"
                  onChange={(e) => { setKubeconfigFile(e.target.files?.[0] ?? null); setError(""); }}
                />
              </label>

              {error && (
                <div className="flex items-center gap-2 mt-3 text-xs text-destructive bg-destructive/10 border border-destructive/20 px-3 py-2 rounded font-mono">
                  <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                  {error}
                </div>
              )}

              <div className="flex gap-2 mt-4">
                <button
                  type="button"
                  onClick={() => { setMethod("picker"); setError(""); setKubeconfigFile(null); }}
                  className="flex-1 py-2 text-xs text-muted-foreground hover:text-foreground bg-secondary/50 hover:bg-secondary rounded transition-colors"
                >
                  Back
                </button>
                <button
                  type="button"
                  onClick={handleKubeconfigUpload}
                  disabled={!kubeconfigFile || loading}
                  className="flex-1 py-2 text-xs font-semibold text-white bg-violet-600 hover:bg-violet-500 rounded transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {loading ? <><Loader2 className="w-3.5 h-3.5 animate-spin" />Uploading...</> : "Add Cluster →"}
                </button>
              </div>
            </div>
          )}

          {/* Token Path */}
          {method === "token" && (
            <div>
              <StepIndicator current={tokenStep} total={3} />

              {tokenStep === 0 && (
                <div>
                  <p className="text-sm text-foreground font-semibold mb-1">Apply the DokOps service account</p>
                  <p className="text-xs text-muted-foreground mb-3 leading-relaxed">
                    Run this command in your cluster terminal. It creates a read-only service account DokOps will use.
                  </p>
                  <div className="flex items-center gap-2 bg-secondary/40 border border-emerald-500/20 rounded-lg px-3 py-2.5">
                    <code className="text-xs text-emerald-500 font-mono flex-1 break-all">{manifestCmd}</code>
                    <CopyButton text={manifestCmd} />
                  </div>
                </div>
              )}

              {tokenStep === 1 && (
                <div>
                  <p className="text-sm text-foreground font-semibold mb-1">Copy the generated token</p>
                  <p className="text-xs text-muted-foreground mb-3 leading-relaxed">
                    Run this command to extract the service account token:
                  </p>
                  <div className="flex items-center gap-2 bg-secondary/40 border border-emerald-500/20 rounded-lg px-3 py-2.5">
                    <code className="text-xs text-emerald-500 font-mono flex-1 break-all">{tokenCmd}</code>
                    <CopyButton text={tokenCmd} />
                  </div>
                </div>
              )}

              {tokenStep === 2 && (
                <div className="flex flex-col gap-3">
                  {(["name", "api_server", "token"] as const).map((f) => (
                    <div key={f}>
                      <label className={labelCls}>
                        {f === "api_server" ? "API Server URL" : f === "name" ? "Cluster Display Name" : "Paste Token"}
                      </label>
                      <input
                        type={f === "token" ? "password" : "text"}
                        placeholder={
                          f === "api_server"
                            ? "https://my-cluster.eastus.azmk8s.io"
                            : f === "token"
                            ? "eyJhbGci..."
                            : "prod-cluster"
                        }
                        value={tokenForm[f]}
                        onChange={(e) => setTokenForm((prev) => ({ ...prev, [f]: e.target.value }))}
                        className={inputCls}
                      />
                    </div>
                  ))}
                </div>
              )}

              {error && (
                <div className="flex items-center gap-2 mt-3 text-xs text-destructive bg-destructive/10 border border-destructive/20 px-3 py-2 rounded font-mono">
                  <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                  {error}
                </div>
              )}

              <div className="flex gap-2 mt-5">
                <button
                  type="button"
                  onClick={() => {
                    tokenStep === 0 ? setMethod("picker") : setTokenStep((s) => s - 1);
                    setError("");
                  }}
                  className="flex-1 py-2 text-xs text-muted-foreground hover:text-foreground bg-secondary/50 hover:bg-secondary rounded transition-colors"
                >
                  {tokenStep === 0 ? "Back" : "← Previous"}
                </button>
                {tokenStep < 2 ? (
                  <button
                    type="button"
                    onClick={() => setTokenStep((s) => s + 1)}
                    className="flex-1 py-2 text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-500 rounded transition-colors"
                  >
                    Next →
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleVerifyToken}
                    disabled={loading || !tokenForm.name || !tokenForm.api_server || !tokenForm.token}
                    className="flex-1 py-2 text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-500 rounded transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                  >
                    {loading ? <><Loader2 className="w-3.5 h-3.5 animate-spin" />Connecting...</> : "Save Cluster →"}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
