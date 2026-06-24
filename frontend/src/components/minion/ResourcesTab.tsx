import { useEffect, useState, useCallback, type ReactNode } from "react";
import api from "../../lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/Card";
import { EmptyState } from "../ui/EmptyState";
import { Box, Layers, HardDrive, Network as NetworkIcon, Server, Search, RefreshCw, FileText, Sparkles, RotateCw, X } from "lucide-react";
import { LogsTerminal } from "../ui/LogsTerminal";
import ReactMarkdown from "react-markdown";

interface DockerData {
  source?: "portainer" | "portainer-edge" | "agent";
  containers: { Id: string; Names?: string[]; Image?: string; State?: string; Status?: string }[];
  images: { Id: string; RepoTags?: string[]; Size?: number }[];
  volumes: { Volumes?: { Name: string; Driver: string }[] };
  networks: { Id: string; Name: string; Driver?: string }[];
}
interface Svc { name: string; display_name: string; status: string }

const TABS = ["containers", "images", "volumes", "networks", "services"] as const;
type Tab = (typeof TABS)[number];

export default function ResourcesTab({ minionId }: { minionId: string }) {
  const [tab, setTab] = useState<Tab>("containers");
  const [filter, setFilter] = useState("");
  const [docker, setDocker] = useState<DockerData | null>(null);
  const [dockerErr, setDockerErr] = useState<string | null>(null);
  const [services, setServices] = useState<Svc[]>([]);
  const [svcErr, setSvcErr] = useState<string | null>(null);
  const [svcLoaded, setSvcLoaded] = useState(false);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [ptr, setPtr] = useState<{ base_url?: string; endpoint_id?: number; via_agent?: boolean }>({});
  const [form, setForm] = useState({ base_url: "", api_key: "", endpoint_id: 1, via_agent: true });
  const [cfgErr, setCfgErr] = useState<string | null>(null);
  const [showCfg, setShowCfg] = useState(false);
  const [logName, setLogName] = useState<string | null>(null);
  const [logKind, setLogKind] = useState("");
  const [logOut, setLogOut] = useState("");
  const [logLoading, setLogLoading] = useState(false);
  const [aiName, setAiName] = useState<string | null>(null);
  const [aiOut, setAiOut] = useState("");
  const [aiLoading, setAiLoading] = useState(false);

  const detail = (e: unknown): string =>
    (e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "failed";

  const poll = useCallback(async () => {
    try {
      const r = await api.get(`/minions/${minionId}/resources/services`);
      setServices(r.data.services); setSvcErr(null);
    } catch (e: unknown) {
      setSvcErr(detail(e));
    } finally {
      setSvcLoaded(true);
    }
    try {
      const cfg = await api.get(`/minions/${minionId}/portainer`);
      setConfigured(cfg.data.configured);
      setPtr({ base_url: cfg.data.base_url, endpoint_id: cfg.data.endpoint_id, via_agent: cfg.data.via_agent });
    } catch { /* config probe failure shouldn't blank docker */ }
    try {
      const d = await api.get(`/minions/${minionId}/resources/docker`);
      setDocker(d.data); setDockerErr(null);
    } catch (e: unknown) {
      setDockerErr(detail(e)); setDocker(null);
    }
  }, [minionId]);

  useEffect(() => {
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, [poll]);

  async function saveConfig() {
    try {
      await api.put(`/minions/${minionId}/portainer`, form);
      setCfgErr(null); setConfigured(true); setShowCfg(false);
      poll();
    } catch (e: unknown) {
      setCfgErr(detail(e));
    }
  }

  async function openLogs(name: string, kind: string, url: string) {
    setLogName(name); setLogKind(kind); setLogOut(""); setLogLoading(true);
    try {
      const r = await api.get(url);
      setLogOut(r.data.output || "(no output)");
    } catch (e: unknown) {
      setLogOut(`Error: ${detail(e)}`);
    } finally {
      setLogLoading(false);
    }
  }

  async function analyzeContainer(name: string) {
    setAiName(name); setAiOut(""); setAiLoading(true);
    try {
      const r = await api.post(`/minions/${minionId}/resources/docker/${encodeURIComponent(name)}/analyze`, {});
      setAiOut(r.data.analysis || "_No analysis returned._");
    } catch (e: unknown) {
      setAiOut(`**Error:** ${detail(e)}`);
    } finally {
      setAiLoading(false);
    }
  }

  const cname = (c: DockerData["containers"][number]) => (c.Names?.[0] ?? c.Id).replace(/^\//, "");
  const match = (s: string) => s.toLowerCase().includes(filter.toLowerCase());

  // Derived, filtered rows for the active tab.
  const counts = {
    containers: docker?.containers.length ?? 0,
    images: docker?.images.length ?? 0,
    volumes: docker?.volumes.Volumes?.length ?? 0,
    networks: docker?.networks.length ?? 0,
    services: services.length,
  };

  const dockerLoading = !docker && !dockerErr;
  const isDockerTab = tab !== "services";

  function body(): ReactNode {
    if (isDockerTab) {
      if (dockerErr) return <EmptyState icon={Box} title="Docker unavailable" description={dockerErr} />;
      if (dockerLoading) return <Loading label="docker resources" />;
    } else if (svcErr) {
      return <EmptyState icon={Server} title="Services unavailable" description={svcErr} />;
    } else if (!svcLoaded) {
      return <Loading label="services" />;
    }

    if (tab === "containers") {
      const rows = (docker?.containers ?? []).filter(c => match(cname(c)) || match(c.Image ?? ""));
      return (
        <DataTable
          headers={["Name", "Image", "State", "Status", ""]}
          empty={<EmptyState icon={Box} title="No containers" description="No containers on this host." />}
          rows={rows.map(c => {
            const name = cname(c);
            return {
              key: c.Id || name,
              cells: [
                <span className="font-mono text-xs text-foreground">{name}</span>,
                <span className="font-mono text-xs text-muted-foreground truncate">{c.Image}</span>,
                <StateDot state={c.State} />,
                <span className="text-xs text-muted-foreground">{c.Status}</span>,
                <div className="flex gap-1.5">
                  <LogBtn onClick={() => openLogs(name, "container",
                    `/minions/${minionId}/resources/docker/${encodeURIComponent(name)}/logs`)} />
                  <AiBtn onClick={() => analyzeContainer(name)} />
                </div>,
              ],
            };
          })}
        />
      );
    }
    if (tab === "images") {
      const rows = (docker?.images ?? []).filter(i => match(i.RepoTags?.[0] ?? i.Id));
      return (
        <DataTable
          headers={["Repository:Tag", "Image ID"]}
          empty={<EmptyState icon={Layers} title="No images" description="No images on this host." />}
          rows={rows.map(i => ({
            key: i.Id || (i.RepoTags?.[0] ?? ""),
            cells: [
              <span className="font-mono text-xs text-foreground">{i.RepoTags?.[0] ?? "<none>"}</span>,
              <span className="font-mono text-xs text-muted-foreground">{i.Id.replace(/^sha256:/, "").slice(0, 12)}</span>,
            ],
          }))}
        />
      );
    }
    if (tab === "volumes") {
      const rows = (docker?.volumes.Volumes ?? []).filter(v => match(v.Name));
      return (
        <DataTable
          headers={["Name", "Driver"]}
          empty={<EmptyState icon={HardDrive} title="No volumes" description="No volumes on this host." />}
          rows={rows.map(v => ({
            key: v.Name,
            cells: [
              <span className="font-mono text-xs text-foreground">{v.Name}</span>,
              <span className="text-xs text-muted-foreground">{v.Driver}</span>,
            ],
          }))}
        />
      );
    }
    if (tab === "networks") {
      const rows = (docker?.networks ?? []).filter(n => match(n.Name));
      return (
        <DataTable
          headers={["Name", "Driver", "Network ID"]}
          empty={<EmptyState icon={NetworkIcon} title="No networks" description="No networks on this host." />}
          rows={rows.map(n => ({
            key: n.Id || n.Name,
            cells: [
              <span className="font-mono text-xs text-foreground">{n.Name}</span>,
              <span className="text-xs text-muted-foreground">{n.Driver}</span>,
              <span className="font-mono text-xs text-muted-foreground">{n.Id.slice(0, 12)}</span>,
            ],
          }))}
        />
      );
    }
    // services
    const rows = services.filter(s => match(s.name) || match(s.display_name));
    return (
      <DataTable
        headers={["Name", "Description", ""]}
        empty={<EmptyState icon={Server} title="No running services" description="No running services were reported." />}
        rows={rows.map(s => ({
          key: s.name,
          cells: [
            <span className="flex items-center gap-2 text-foreground">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-400 shrink-0" />{s.name}
            </span>,
            <span className="text-xs text-muted-foreground truncate">{s.display_name}</span>,
            <LogBtn onClick={() => openLogs(s.name, "service",
              `/minions/${minionId}/resources/services/${encodeURIComponent(s.name)}/logs`)} />,
          ],
        }))}
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* Tab bar + controls */}
      <div className="flex items-center justify-between border-b border-border">
        <div className="flex gap-0">
          {TABS.map(t => (
            <button key={t} onClick={() => { setTab(t); setFilter(""); }}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 capitalize transition-colors ${
                tab === t ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
              {t} <span className="text-muted-foreground/70">({counts[t]})</span>
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3 text-xs pb-1">
          {docker?.source && (
            <span className="text-muted-foreground">via {
              docker.source === "portainer" ? "Portainer (VM)"
                : docker.source === "portainer-edge" ? "Portainer (edge agent)"
                : "agent (docker CLI)"
            }</span>
          )}
          {tab !== "services" && (
            <button onClick={() => setShowCfg(v => {
              const next = !v;
              if (next) setForm(f => ({
                ...f,
                base_url: ptr.base_url ?? f.base_url,
                endpoint_id: ptr.endpoint_id ?? f.endpoint_id,
                via_agent: ptr.via_agent ?? true,
              }));
              return next;
            })} className="text-primary hover:underline">
              {configured ? "Reconfigure Portainer" : "Configure Portainer"}
            </button>
          )}
          <button onClick={poll} title="Refresh" className="p-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors">
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Portainer config (optional, Docker tabs only) */}
      {showCfg && tab !== "services" && (
        <Card>
          <CardContent className="space-y-3 max-w-md">
            <p className="text-xs text-muted-foreground">Point at this host's Portainer for richer data. Leave unset to use the agent's <code>docker</code> CLI.</p>
            <label className="block">
              <span className="text-xs font-medium text-muted-foreground">Portainer URL</span>
              <input className="mt-1 w-full bg-background border border-border rounded px-2 py-1.5 text-sm"
                placeholder="https://host:9443" value={form.base_url} onChange={e => setForm({ ...form, base_url: e.target.value })} />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-muted-foreground">API key</span>
              <input className="mt-1 w-full bg-background border border-border rounded px-2 py-1.5 text-sm"
                placeholder="ptr_…" value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })} />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-muted-foreground">Environment (endpoint) ID</span>
              <input type="number" className="mt-1 w-full bg-background border border-border rounded px-2 py-1.5 text-sm"
                value={form.endpoint_id} onChange={e => setForm({ ...form, endpoint_id: Number(e.target.value) })} />
              <span className="text-[11px] text-muted-foreground">Usually <code>1</code> for a local Portainer. It's the number in Portainer's URL: <code>/#!/&lt;id&gt;/docker/…</code></span>
            </label>
            <label className="flex items-start gap-2 cursor-pointer">
              <input type="checkbox" className="mt-0.5" checked={form.via_agent}
                onChange={e => setForm({ ...form, via_agent: e.target.checked })} />
              <span className="text-xs text-muted-foreground">
                <span className="font-medium text-foreground">Fetch from the minion (edge)</span> — the agent queries Portainer locally and returns the data.
                Use this when Portainer is only reachable on the minion's network, not from the DokOps server. The URL above is then from the <em>minion's</em> view (often <code>https://localhost:9443</code>).
              </span>
            </label>
            <button onClick={saveConfig} className="px-3 py-1.5 text-sm rounded-lg bg-primary text-primary-foreground hover:bg-primary/90">Save &amp; connect</button>
            {cfgErr && <p className="text-sm text-red-400">{cfgErr}</p>}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle className="capitalize">{tab}</CardTitle></CardHeader>
        <CardContent>
          {/* filter */}
          {(isDockerTab ? !dockerErr && !dockerLoading : svcLoaded && !svcErr) && (
            <div className="relative max-w-sm mb-3">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
              <input className="w-full pl-8 pr-3 h-8 text-sm border border-border rounded-md bg-background focus:outline-none focus:ring-1 focus:ring-blue-500"
                placeholder={`Filter ${tab}…`} value={filter} onChange={e => setFilter(e.target.value)} />
            </div>
          )}
          {body()}
        </CardContent>
      </Card>

      {/* Logs terminal (shared macOS-style viewer, same as K8s) */}
      <LogsTerminal
        isOpen={!!logName}
        onClose={() => setLogName(null)}
        podName={logName ?? ""}
        namespace={logKind}
        logs={logLoading ? "Loading…" : logOut}
      />

      {/* AI analysis modal */}
      {aiName && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={() => setAiName(null)}>
          <div className="bg-card border border-border rounded-xl w-full max-w-2xl max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b border-border">
              <span className="font-semibold text-foreground flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-primary" /> AI Analysis — {aiName}
              </span>
              <button onClick={() => setAiName(null)} className="text-muted-foreground hover:text-foreground"><X className="w-4 h-4" /></button>
            </div>
            <div className="flex-1 overflow-auto p-4">
              {aiLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground"><RotateCw className="w-4 h-4 animate-spin" /> Analyzing container logs…</div>
              ) : (
                <div className="prose prose-sm dark:prose-invert max-w-none text-sm"><ReactMarkdown>{aiOut}</ReactMarkdown></div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function AiBtn({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick} title="AI analyze logs"
      className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded-md border border-primary/30 text-primary hover:bg-primary/10 transition-colors">
      <Sparkles className="w-3.5 h-3.5" /> AI
    </button>
  );
}

function Loading({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center py-12 text-muted-foreground">
      <RefreshCw className="w-5 h-5 animate-spin mr-2" />Loading {label}…
    </div>
  );
}

function StateDot({ state }: { state?: string }) {
  const running = (state ?? "").toLowerCase() === "running";
  return (
    <span className="flex items-center gap-1.5 text-xs">
      <span className={`inline-block w-1.5 h-1.5 rounded-full ${running ? "bg-green-400" : "bg-slate-400"}`} />
      <span className={running ? "text-green-400" : "text-muted-foreground"}>{state || "—"}</span>
    </span>
  );
}

function LogBtn({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick} title="View logs"
      className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded-md border border-border text-muted-foreground hover:text-primary hover:border-primary/40 transition-colors">
      <FileText className="w-3.5 h-3.5" /> Logs
    </button>
  );
}

function DataTable({ headers, rows, empty }: { headers: string[]; rows: { key: string; cells: ReactNode[] }[]; empty: ReactNode }) {
  if (rows.length === 0) return <>{empty}</>;
  return (
    <table className="w-full text-sm">
      <thead className="border-b border-border">
        <tr>{headers.map((h, i) => <th key={i} className="p-3 text-left text-xs uppercase tracking-wider text-muted-foreground font-medium">{h}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map(r => (
          <tr key={r.key} className="border-b border-border hover:bg-accent/50 transition-colors">
            {r.cells.map((c, j) => <td key={j} className="p-3 max-w-xs truncate">{c}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
