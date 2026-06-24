// frontend/src/components/minion/ResourcesTab.tsx
import { useEffect, useState, useCallback } from "react";
import api from "../../lib/api";

interface DockerData {
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
    // Config and Docker fetches are independent: a Docker 502/503 must not blank the config state.
    let isConfigured = false;
    try {
      const cfg = await api.get(`/minions/${minionId}/portainer`);
      setConfigured(cfg.data.configured);
      isConfigured = cfg.data.configured;
    } catch (e: unknown) {
      setDockerErr(detail(e));
      return;
    }
    if (isConfigured) {
      try {
        const d = await api.get(`/minions/${minionId}/resources/docker`);
        setDocker(d.data); setDockerErr(null);
      } catch (e: unknown) {
        setDockerErr(detail(e));
      }
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
      poll();
    } catch (e: unknown) {
      setCfgErr(detail(e));
    }
  }

  const card = "bg-card border border-border rounded-xl p-4";
  return (
    <div className="space-y-6">
      {/* Docker */}
      <div className={card}>
        <h2 className="text-xs text-muted-foreground uppercase tracking-wider mb-3">Docker (live via Portainer)</h2>
        {configured === false ? (
          <div className="space-y-2 max-w-md">
            <p className="text-sm text-muted-foreground">Portainer not configured for this minion.</p>
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
        ) : dockerErr ? (
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
                <div key={s.name} className="flex items-center gap-2 text-sm">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-400" />
                  <span className="text-foreground truncate" title={s.display_name}>{s.name}</span>
                </div>
              ))}
            </div>
          )}
      </div>
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
