import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api from "../lib/api";
import MinionApproveModal from "../components/MinionApproveModal";
import MinionJobModal from "../components/MinionJobModal";
import BlueprintTab from "../components/minion/BlueprintTab";
import ResourcesTab from "../components/minion/ResourcesTab";

interface Minion {
  id: string; hostname: string; status: string;
  grains: string; last_seen: string | null; approved_by: string | null;
}
interface Job {
  id: string; command: string; status: string;
  stdout: string; exit_code: number | null; created_at: string;
}
interface Grains {
  os?: string; arch?: string; kernel?: string;
  docker?: string; ansible?: string; systemctl?: boolean;
  cpu_pct?: number; mem_pct?: number; disk_pct?: number;
}

interface DiscoveredService {
  id: string;
  service_type: string;
  install_type: "native" | "docker";
  container_name: string | null;
  port: number;
  detected_at: string;
  overridden: boolean;
}

interface CredentialScope {
  resolved: boolean;
  scope_type: "global" | "group" | "minion" | null;
}

const SERVICE_ICONS: Record<string, string> = {
  rabbitmq: "/service-icons/rabbitmq.svg",
  redis: "/service-icons/redis.svg",
  couchdb: "/service-icons/couchdb.svg",
  postgres: "/service-icons/postgres.svg",
  mongodb: "/service-icons/mongodb.svg",
  mysql: "/service-icons/mysql.svg",
  mssql: "🗄️",
};

const SERVICE_PROBES: Record<string, string[]> = {
  rabbitmq: ["status", "queues", "cluster", "overview", "connections", "logs"],
  redis: ["info", "slowlog", "memory", "clients", "logs"],
  couchdb: ["server_info", "active_tasks", "stats", "db_list", "logs"],
  mongodb: ["status", "logs"],
  mysql: ["status", "processlist", "logs"],
  postgres: ["status", "activity", "logs"],
  mssql: ["status", "processlist", "databases", "logs"],
};

function GaugeBar({ label, value }: { label: string; value: number }) {
  const color = value > 85 ? "bg-red-500" : value > 65 ? "bg-amber-400" : "bg-emerald-500";
  return (
    <div className="bg-card border border-border rounded-xl p-4 text-center">
      <div className="text-muted-foreground text-xs uppercase tracking-wider mb-1">{label}</div>
      <div className="text-2xl font-bold text-foreground">{value}%</div>
      <div className="bg-muted rounded-full h-1.5 mt-2">
        <div className={`${color} h-1.5 rounded-full transition-all`} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

export default function MinionDetail() {
  const { minionId } = useParams<{ minionId: string }>();
  const navigate = useNavigate();
  const [minion, setMinion] = useState<Minion | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [showApprove, setShowApprove] = useState(false);
  const [showJob, setShowJob] = useState(false);
  const [jobOutput, setJobOutput] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "jobs" | "services" | "resources" | "blueprints">("overview");
  const [services, setServices] = useState<DiscoveredService[]>([]);
  const [credScopes, setCredScopes] = useState<Record<string, CredentialScope>>({});
  const [diagService, setDiagService] = useState<DiscoveredService | null>(null);
  const [diagProbe, setDiagProbe] = useState<string>("status");
  const [diagOutput, setDiagOutput] = useState<string>("");
  const [diagExitCode, setDiagExitCode] = useState<number | null>(null);
  const [diagRunning, setDiagRunning] = useState(false);
  const [discoverLoading, setDiscoverLoading] = useState(false);

  async function load() {
    if (!minionId) return;
    const [mRes, jRes] = await Promise.all([
      api.get(`/minions/${minionId}`),
      api.get(`/minions/${minionId}/jobs`),
    ]);
    setMinion(mRes.data);
    setJobs((jRes.data as Job[]).slice(-10).reverse());
    setLoading(false);
  }

  useEffect(() => { load(); loadServices(); }, [minionId]);

  async function handleDelete() {
    if (!minionId) return;
    if (!confirm("Remove this minion from DokOps?")) return;
    await api.delete(`/minions/${minionId}`);
    navigate("/infrastructure/minions");
  }

  async function handleJobSubmit(cmd: string) {
    if (!minionId) return;
    setShowJob(false);
    try {
      const r = await api.post(`/minions/${minionId}/jobs`, { command: cmd, actor: "ui" });
      setJobOutput((r.data as { stdout?: string }).stdout ?? "(no output)");
      load();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setJobOutput(`Error: ${err.response?.data?.detail ?? err.message}`);
    }
  }

  async function loadServices() {
    if (!minionId) return;
    try {
      const res = await api.get(`/minions/${minionId}/services`);
      const svcs = res.data as DiscoveredService[];
      setServices(svcs);
      const scopes: Record<string, CredentialScope> = {};
      await Promise.all(
        svcs.map(async (s) => {
          try {
            const r = await api.get(`/service-credentials/resolve/${minionId}/${s.service_type}`);
            scopes[s.service_type] = r.data as CredentialScope;
          } catch {
            scopes[s.service_type] = { resolved: false, scope_type: null };
          }
        })
      );
      setCredScopes(scopes);
    } catch {
      // silently ignore
    }
  }

  async function handleDiscover() {
    if (!minionId) return;
    setDiscoverLoading(true);
    try {
      await api.post(`/minions/${minionId}/services/discover`);
      // Discovery is async over WebSocket — poll after 3s and again at 8s to catch slow devices
      setTimeout(() => loadServices(), 3000);
      setTimeout(() => { loadServices(); setDiscoverLoading(false); }, 8000);
    } catch { setDiscoverLoading(false); }
  }

  async function handleDiagnose() {
    if (!diagService || !minionId) return;
    setDiagRunning(true);
    setDiagOutput("");
    setDiagExitCode(null);
    try {
      const r = await api.post(`/minions/${minionId}/jobs`, {
        command: `__probe__:${diagService.service_type}:${diagProbe}`,
        actor: "ui_diagnose",
      });
      const data = r.data as { stdout?: string; exit_code?: number };
      setDiagOutput(data.stdout ?? "(no output)");
      setDiagExitCode(data.exit_code ?? 0);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setDiagOutput(`Error: ${err.response?.data?.detail ?? err.message}`);
      setDiagExitCode(1);
    } finally {
      setDiagRunning(false);
    }
  }

  if (loading) return <div className="p-6 text-muted-foreground">Loading…</div>;
  if (!minion) return <div className="p-6 text-red-400">Minion not found</div>;

  let grains: Grains = {};
  try { grains = JSON.parse(minion.grains); } catch { /* noop */ }


  const statusDot = minion.status === "active" ? "bg-green-400" : minion.status === "pending" ? "bg-yellow-400" : "bg-red-400";

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div className="flex items-start gap-3">
          <div className="mt-1">
            <span className={`inline-block w-2.5 h-2.5 rounded-full ${statusDot} ring-2 ring-offset-2 ring-offset-background ring-current opacity-80`} />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-foreground leading-tight">{minion.hostname}</h1>
            <div className="flex flex-wrap items-center gap-2 mt-1.5">
              <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${
                minion.status === "active"  ? "border-green-800 text-green-400 bg-green-950/40" :
                minion.status === "pending" ? "border-yellow-800 text-yellow-400 bg-yellow-950/40" :
                                              "border-red-800 text-red-400 bg-red-950/40"
              }`}>{minion.status}</span>
              {minion.last_seen && (
                <span className="text-xs text-muted-foreground">
                  Last seen {new Date(minion.last_seen).toLocaleString()}
                </span>
              )}
              {minion.approved_by && (
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <span className="text-muted-foreground/50">·</span>
                  Approved by <span className="text-foreground font-medium">{minion.approved_by}</span>
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {minion.status === "pending" && (
            <button onClick={() => setShowApprove(true)} className="px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-700 text-white text-sm font-medium">
              Approve
            </button>
          )}
          {minion.status === "active" && (
            <button onClick={() => setShowJob(true)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>
              Run Command
            </button>
          )}
          <button
            onClick={handleDelete}
            title="Remove minion"
            className="p-1.5 rounded-lg text-muted-foreground hover:text-red-400 hover:bg-red-950/40 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-border mb-6">
        {(["overview", "jobs", "services", "resources", "blueprints"] as const).map(tab => (
          <button
            key={tab}
            onClick={() => { setActiveTab(tab); setDiagService(null); }}
            className={`px-4 py-2 text-sm capitalize border-b-2 transition-colors ${
              activeTab === tab
                ? "border-primary text-primary font-medium"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Overview tab */}
      {activeTab === "overview" && (
        <div>
          <div className="grid grid-cols-3 gap-4 mb-6">
            <GaugeBar label="CPU" value={grains.cpu_pct ?? 0} />
            <GaugeBar label="MEM" value={grains.mem_pct ?? 0} />
            <GaugeBar label="DISK" value={grains.disk_pct ?? 0} />
          </div>

          <div className="bg-card border border-border rounded-xl p-4 mb-6">
            <h2 className="text-xs text-muted-foreground uppercase tracking-wider mb-3">Grains</h2>
            <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-sm">
              {(
                [
                  ["OS", grains.os], ["Arch", grains.arch], ["Kernel", grains.kernel],
                  ["Docker", grains.docker], ["Ansible", grains.ansible],
                  ["systemctl", grains.systemctl ? "✓" : "—"],
                ] as [string, string | boolean | undefined][]
              ).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <span className="text-muted-foreground w-20 shrink-0">{k}</span>
                  <span className="text-foreground">{v ?? "—"}</span>
                </div>
              ))}
            </div>
          </div>

          {jobOutput !== null && (
            <div className="bg-muted/40 border border-border rounded-xl p-4 mb-6">
              <div className="flex justify-between items-center mb-2">
                <h2 className="text-xs text-muted-foreground uppercase tracking-wider">Last Output</h2>
                <button onClick={() => setJobOutput(null)} className="text-xs text-muted-foreground hover:text-foreground">✕ clear</button>
              </div>
              <pre className="font-mono text-xs text-foreground whitespace-pre-wrap overflow-auto max-h-48">{jobOutput}</pre>
            </div>
          )}
        </div>
      )}

      {/* Jobs tab */}
      {activeTab === "jobs" && (
        <div className="bg-card border border-border rounded-xl p-4">
          <h2 className="text-xs text-muted-foreground uppercase tracking-wider mb-3">Recent Jobs</h2>
          {jobs.length === 0 ? (
            <p className="text-muted-foreground text-sm">No jobs yet.</p>
          ) : (
            <div className="space-y-1">
              {jobs.map((j) => (
                <div key={j.id} className="flex items-center gap-3 text-sm py-1">
                  <span className={j.exit_code === 0 ? "text-green-400" : "text-red-400"}>
                    {j.exit_code === 0 ? "✓" : "✗"}
                  </span>
                  <span className="font-mono text-foreground flex-1 truncate">{j.command}</span>
                  <span className="text-muted-foreground text-xs">
                    {new Date(j.created_at).toLocaleTimeString()}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Services tab */}
      {activeTab === "services" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground">Discovered Services</h2>
            <button
              onClick={handleDiscover}
              disabled={discoverLoading}
              className="px-3 py-1.5 text-xs rounded-lg bg-primary/10 text-primary hover:bg-primary/20 disabled:opacity-50"
            >
              {discoverLoading ? "Scanning…" : "Refresh Discovery"}
            </button>
          </div>

          {services.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              No services discovered yet. Click "Refresh Discovery" to scan this device.
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-3">
              {services.map(svc => {
                const scope = credScopes[svc.service_type];
                return (
                  <div key={svc.id} className="border border-border rounded-xl p-4 bg-card hover:border-border/70 transition-colors">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        {(() => { const ic = SERVICE_ICONS[svc.service_type]; return ic?.startsWith("/") ? <img src={ic} alt={svc.service_type} className="w-6 h-6 object-contain" /> : <span className="text-xl">{ic ?? "⚙️"}</span>; })()}
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-foreground capitalize">{svc.service_type}</span>
                            <span className={`text-xs px-1.5 py-0.5 rounded ${svc.install_type === "docker" ? "bg-blue-500/20 text-blue-400" : "bg-green-500/20 text-green-400"}`}>
                              {svc.install_type}
                            </span>
                            {svc.overridden && <span className="text-xs px-1.5 py-0.5 rounded bg-yellow-500/20 text-yellow-400">manual</span>}
                          </div>
                          <div className="text-xs text-muted-foreground mt-0.5">
                            :{svc.port}
                            {svc.container_name && ` · container: ${svc.container_name}`}
                            {scope?.resolved && ` · creds: ${scope.scope_type}`}
                            {scope && !scope.resolved && <span className="text-yellow-400"> · no credentials</span>}
                          </div>
                        </div>
                      </div>
                      <button
                        onClick={() => { setDiagService(svc); setDiagProbe(SERVICE_PROBES[svc.service_type]?.[0] ?? "status"); setDiagOutput(""); setDiagExitCode(null); }}
                        className="px-3 py-1.5 text-xs rounded-lg bg-primary text-primary-foreground hover:bg-primary/90"
                      >
                        Diagnose
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Diagnose modal */}
          {diagService && (
            <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
              <div className="bg-card border border-border rounded-xl w-full max-w-3xl max-h-[80vh] flex flex-col">
                <div className="flex items-center justify-between p-4 border-b border-border">
                  <div className="flex items-center gap-2">
                    {(() => { const ic = SERVICE_ICONS[diagService.service_type]; return ic?.startsWith("/") ? <img src={ic} alt={diagService.service_type} className="w-5 h-5 object-contain" /> : <span className="text-lg">{ic ?? "⚙️"}</span>; })()}
                    <span className="font-semibold text-foreground capitalize">{diagService.service_type}</span>
                    <span className="text-muted-foreground text-sm">on {minion?.hostname}</span>
                  </div>
                  <button onClick={() => setDiagService(null)} className="text-muted-foreground hover:text-foreground">✕</button>
                </div>
                <div className="p-4 border-b border-border flex items-center gap-3">
                  <select
                    value={diagProbe}
                    onChange={e => setDiagProbe(e.target.value)}
                    className="bg-background border border-border rounded px-2 py-1.5 text-sm text-foreground"
                  >
                    {(SERVICE_PROBES[diagService.service_type] ?? []).map(p => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                  <button
                    onClick={handleDiagnose}
                    disabled={diagRunning}
                    className="px-4 py-1.5 text-sm rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                  >
                    {diagRunning ? "Running…" : "Run Probe"}
                  </button>
                </div>
                <div className="flex-1 overflow-auto p-4">
                  {diagOutput ? (
                    <pre className={`text-xs font-mono whitespace-pre-wrap ${diagExitCode !== 0 ? "text-red-400" : "text-green-400"}`}>{diagOutput}</pre>
                  ) : (
                    <p className="text-xs text-muted-foreground text-center py-8">Select a probe and click Run.</p>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === "resources" && minionId && (
        <ResourcesTab minionId={minionId} />
      )}

      {activeTab === "blueprints" && minionId && (
        <BlueprintTab minionId={minionId} />
      )}

      {showApprove && (
        <MinionApproveModal
          minionId={minion.id}
          hostname={minion.hostname}
          onClose={() => setShowApprove(false)}
          onApproved={() => { setShowApprove(false); load(); }}
        />
      )}
      {showJob && (
        <MinionJobModal
          minionId={minion.id}
          onClose={() => setShowJob(false)}
          onJobSubmitted={handleJobSubmit}
        />
      )}
    </div>
  );
}
