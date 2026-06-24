// frontend/src/components/minion/ResourcesTab.tsx
import { useEffect, useState, useCallback } from "react";
import api from "../../lib/api";

interface DockerData {
  source?: "portainer" | "agent";
  containers: { Id: string; Names?: string[]; Image?: string; State?: string; Status?: string }[];
  images: { Id: string; RepoTags?: string[]; Size?: number }[];
  volumes: { Volumes?: { Name: string; Driver: string }[] };
  networks: { Id: string; Name: string; Driver?: string }[];
}
interface Svc { name: string; display_name: string; status: string }

export default function ResourcesTab({ minionId }: { minionId: string }) {
  const [services, setServices] = useState<Svc[]>([]);
  const [svcErr, setSvcErr] = useState<string | null>(null);
  const [svcLoaded, setSvcLoaded] = useState(false);
  const [docker, setDocker] = useState<DockerData | null>(null);
  const [dockerErr, setDockerErr] = useState<string | null>(null);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [form, setForm] = useState({ base_url: "", api_key: "", endpoint_id: 1 });
  const [cfgErr, setCfgErr] = useState<string | null>(null);
  const [showCfg, setShowCfg] = useState(false);
  const [logSvc, setLogSvc] = useState<string | null>(null);
  const [logOut, setLogOut] = useState("");
  const [logLoading, setLogLoading] = useState(false);

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
    // Portainer config (for the toggle label) and Docker data are fetched independently.
    try {
      const cfg = await api.get(`/minions/${minionId}/portainer`);
      setConfigured(cfg.data.configured);
    } catch { /* config probe failure shouldn't blank docker */ }
    // Docker always loads: Portainer when configured, else the agent CLI fallback.
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
      setCfgErr(null);
      setConfigured(true);
      setShowCfg(false);
      poll();
    } catch (e: unknown) {
      setCfgErr(detail(e));
    }
  }

  async function openLogs(name: string) {
    setLogSvc(name);
    setLogOut("");
    setLogLoading(true);
    try {
      const r = await api.get(`/minions/${minionId}/resources/services/${encodeURIComponent(name)}/logs`);
      setLogOut(r.data.output || "(no output)");
    } catch (e: unknown) {
      setLogOut(`Error: ${detail(e)}`);
    } finally {
      setLogLoading(false);
    }
  }

  const card = "bg-card border border-border rounded-xl p-4";
  return (
    <div className="space-y-6">
      {/* Docker */}
      <div className={card}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs text-muted-foreground uppercase tracking-wider">Docker (live)</h2>
          <div className="flex items-center gap-3 text-xs">
            {docker?.source && (
              <span className="text-muted-foreground">
                via {docker.source === "portainer" ? "Portainer" : "agent (docker CLI)"}
              </span>
            )}
            <button onClick={() => setShowCfg(v => !v)} className="text-primary hover:underline">
              {configured ? "Reconfigure Portainer" : "Configure Portainer"}
            </button>
          </div>
        </div>

        {showCfg && (
          <div className="space-y-2 max-w-md mb-4 border-b border-border pb-4">
            <p className="text-xs text-muted-foreground">Point at this host's Portainer for richer data. Leave unset to use the agent's <code>docker</code> CLI.</p>
            <input className="w-full bg-background border border-border rounded px-2 py-1.5 text-sm"
              placeholder="https://host:9443" value={form.base_url}
              onChange={e => setForm({ ...form, base_url: e.target.value })} />
            <input className="w-full bg-background border border-border rounded px-2 py-1.5 text-sm"
              placeholder="API key" value={form.api_key}
              onChange={e => setForm({ ...form, api_key: e.target.value })} />
            <input type="number" className="w-full bg-background border border-border rounded px-2 py-1.5 text-sm"
              placeholder="Endpoint ID" value={form.endpoint_id}
              onChange={e => setForm({ ...form, endpoint_id: Number(e.target.value) })} />
            <button onClick={saveConfig}
              className="px-3 py-1.5 text-sm rounded-lg bg-primary text-primary-foreground hover:bg-primary/90">
              Save & connect
            </button>
            {cfgErr && <p className="text-sm text-red-400">{cfgErr}</p>}
          </div>
        )}

        {dockerErr ? (
          <p className="text-sm text-red-400">{dockerErr}</p>
        ) : !docker ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <div className="grid grid-cols-2 gap-4 text-sm">
            <ResourceList title={`Containers (${docker.containers.length})`}
              items={docker.containers.map(c => `${(c.Names?.[0] ?? c.Id).replace(/^\//, "")} · ${c.State ?? ""}`)} />
            <ResourceList title={`Images (${docker.images.length})`}
              items={docker.images.map(i => i.RepoTags?.[0] ?? i.Id.slice(7, 19))} />
            <ResourceList title={`Volumes (${docker.volumes.Volumes?.length ?? 0})`}
              items={(docker.volumes.Volumes ?? []).map(v => v.Name)} />
            <ResourceList title={`Networks (${docker.networks.length})`}
              items={docker.networks.map(n => `${n.Name} · ${n.Driver ?? ""}`)} />
          </div>
        )}
      </div>

      {/* System services */}
      <div className={card}>
        <h2 className="text-xs text-muted-foreground uppercase tracking-wider mb-3">System Services (live)</h2>
        {svcErr ? <p className="text-sm text-red-400">{svcErr}</p> :
          services.length === 0 ? <p className="text-sm text-muted-foreground">{svcLoaded ? "No running services" : "Loading…"}</p> : (
            <div className="grid grid-cols-2 gap-x-8 gap-y-1">
              {services.map(s => (
                <button key={s.name} onClick={() => openLogs(s.name)}
                  className="flex items-center gap-2 text-sm text-left rounded px-1 -mx-1 hover:bg-muted/50 transition-colors">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-400 shrink-0" />
                  <span className="text-foreground truncate hover:text-primary" title={s.display_name}>{s.name}</span>
                </button>
              ))}
            </div>
          )}
      </div>

      {/* Service status + logs modal */}
      {logSvc && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={() => setLogSvc(null)}>
          <div className="bg-card border border-border rounded-xl w-full max-w-3xl max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b border-border">
              <span className="font-semibold text-foreground">{logSvc} — status &amp; logs</span>
              <button onClick={() => setLogSvc(null)} className="text-muted-foreground hover:text-foreground">✕</button>
            </div>
            <div className="flex-1 overflow-auto p-4">
              {logLoading ? (
                <p className="text-xs text-muted-foreground">Loading…</p>
              ) : (
                <pre className="text-xs font-mono text-foreground whitespace-pre-wrap">{logOut}</pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ResourceList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="text-muted-foreground text-xs mb-1">{title}</div>
      <div className="space-y-0.5 max-h-48 overflow-auto">
        {items.length === 0 ? <div className="text-muted-foreground/60 text-xs">none</div> :
          items.map((it, i) => <div key={i} className="text-foreground font-mono text-xs truncate">{it}</div>)}
      </div>
    </div>
  );
}
