import { useEffect, useState } from "react";
import api from "../lib/api";
import { useToast } from "../context/ToastContext";
import type { ActivationKey, CreatedKey } from "../types/activationKey";
import type { Blueprint } from "../types/blueprint";

interface Org { id: string; name: string; }
interface Group { id: string; name: string; }

export default function Keys() {
  const { toast } = useToast();
  const [keys, setKeys] = useState<ActivationKey[]>([]);
  const [blueprints, setBlueprints] = useState<Blueprint[]>([]);
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [name, setName] = useState("");
  const [groupId, setGroupId] = useState("");
  const [orgId, setOrgId] = useState("");
  const [runOnAttach, setRunOnAttach] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [created, setCreated] = useState<CreatedKey | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  const [tokenSaved, setTokenSaved] = useState(false);

  function genToken() { setTokenInput(crypto.randomUUID().replace(/-/g, "")); }
  async function saveToken() {
    if (!tokenInput.trim()) return;
    try {
      await api.post("/ai/config", { minion_auto_accept_key: tokenInput.trim() });
      setTokenSaved(true);
      setTimeout(() => setTokenSaved(false), 4000);
    } catch {
      toast("Failed to save enrollment token", "error");
    }
  }

  async function loadKeys() { setKeys((await api.get("/keys")).data as ActivationKey[]); }
  useEffect(() => {
    loadKeys();
    api.get("/blueprints").then(r => setBlueprints(r.data as Blueprint[])).catch(() => {});
    api.get("/organisations").then(r => setOrgs(r.data as Org[])).catch(() => {});
    api.get("/organisations/groups").then(r => setGroups(r.data as Group[])).catch(() => {});
  }, []);

  function toggle(id: string) {
    setPicked(p => p.includes(id) ? p.filter(x => x !== id) : [...p, id]);
  }
  function move(idx: number, dir: -1 | 1) {
    setPicked(p => {
      const j = idx + dir;
      if (j < 0 || j >= p.length) return p;
      const next = [...p];
      [next[idx], next[j]] = [next[j], next[idx]];
      return next;
    });
  }
  const bpName = (id: string) => blueprints.find(b => b.id === id)?.name ?? id;

  async function createKey() {
    if (!name.trim()) return;
    try {
      const r = await api.post("/keys", {
        name: name.trim(), org_id: orgId || null, group_id: groupId || null,
        run_on_attach: runOnAttach, blueprint_ids: picked,
      });
      setCreated(r.data as CreatedKey);
      setName(""); setPicked([]); setRunOnAttach(false); setGroupId(""); setOrgId("");
      loadKeys();
    } catch (e: unknown) {
      const err = e as { response?: { status?: number } };
      toast(err.response?.status === 409 ? "Key name already exists" : "Create failed", "error");
    }
  }

  async function removeKey(id: string) {
    await api.delete(`/keys/${id}`);
    loadKeys();
  }

  const installPs = created
    ? `powershell -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((irm '<DOKOPS_URL>/minion/install.ps1'))) -Url '<DOKOPS_URL>' -Token '<ENROLLMENT_TOKEN>' -Key '${created.value}'"`
    : "";

  return (
    <div className="p-6 w-full max-w-[100rem] mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground">Activation Keys</h1>
        <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
          A key attaches blueprints to onboarding. Install a machine with <code>-Key &lt;value&gt;</code> and,
          if "run on attach" is on, its blueprints apply once. <code>-Token</code> still handles enrollment auth.
        </p>
      </div>

      {/* Global enrollment token (the --token auto-accept key every minion installs with) */}
      <div className="mb-6 bg-card border border-border rounded-xl p-4">
        <h2 className="text-sm font-semibold text-foreground">Enrollment token</h2>
        <p className="text-xs text-muted-foreground mt-1 mb-2 max-w-2xl">
          The shared <code>-Token</code> every minion installs with — a matching token auto-accepts the machine on connect. Set it once; it's stored hashed, so copy it for your install commands.
        </p>
        <div className="flex gap-2 items-center max-w-2xl">
          <input value={tokenInput} onChange={e => setTokenInput(e.target.value)} placeholder="enrollment token value"
            className="flex-1 bg-background border border-border rounded-lg px-3 py-2 font-mono text-xs text-foreground" />
          <button onClick={genToken} className="text-xs px-2 py-2 rounded-lg bg-muted text-muted-foreground hover:text-foreground">generate</button>
          <button onClick={saveToken} disabled={!tokenInput.trim()}
            className="px-3 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium disabled:opacity-50">Save</button>
          {tokenSaved && <span className="text-xs text-green-400">saved</span>}
        </div>
      </div>

      {created && (
        <div className="mb-6 bg-card border border-primary/40 rounded-xl p-4 space-y-2">
          <p className="text-sm font-semibold text-foreground">Key "{created.key.name}" created — copy the value now (shown once):</p>
          <code className="block bg-background border border-border rounded px-3 py-2 text-xs text-foreground break-all">{created.value}</code>
          <p className="text-xs text-muted-foreground">Windows install command:</p>
          <code className="block bg-background border border-border rounded px-3 py-2 text-[11px] text-foreground break-all">{installPs}</code>
          <button onClick={() => setCreated(null)} className="text-xs text-muted-foreground hover:text-foreground">dismiss</button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[20rem_1fr] gap-6 items-start">
        {/* Create */}
        <div className="bg-card border border-border rounded-xl p-5 space-y-3">
          <h2 className="text-sm font-semibold text-foreground">New key</h2>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="key name (e.g. win-web)"
            className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground" />
          <select value={orgId} onChange={e => { setOrgId(e.target.value); setGroupId(""); }}
            className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground">
            <option value="">org (optional)…</option>
            {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
          <select value={groupId} onChange={e => setGroupId(e.target.value)}
            className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground">
            <option value="">group (optional)…</option>
            {groups.filter(g => !orgId || (g as Group & { org_id?: string }).org_id === orgId)
                   .map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input type="checkbox" checked={runOnAttach} onChange={e => setRunOnAttach(e.target.checked)} />
            Run blueprints on attach
          </label>
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Blueprints</p>
            <div className="space-y-1 max-h-48 overflow-auto">
              {blueprints.map(b => (
                <label key={b.id} className="flex items-center gap-2 text-sm text-foreground">
                  <input type="checkbox" checked={picked.includes(b.id)} onChange={() => toggle(b.id)} />
                  {b.name}
                </label>
              ))}
              {blueprints.length === 0 && <p className="text-xs text-muted-foreground">No blueprints yet.</p>}
            </div>
            {picked.length > 0 && (
              <div className="mt-3">
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Run order (top runs first)</p>
                <div className="space-y-1">
                  {picked.map((id, i) => (
                    <div key={id} className="flex items-center gap-2 text-sm bg-background border border-border rounded px-2 py-1">
                      <span className="text-muted-foreground w-5 text-right">{i + 1}.</span>
                      <span className="flex-1 truncate text-foreground">{bpName(id)}</span>
                      <button onClick={() => move(i, -1)} disabled={i === 0}
                        title="move up" className="px-1 text-muted-foreground hover:text-foreground disabled:opacity-30">▲</button>
                      <button onClick={() => move(i, 1)} disabled={i === picked.length - 1}
                        title="move down" className="px-1 text-muted-foreground hover:text-foreground disabled:opacity-30">▼</button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
          <button onClick={createKey} disabled={!name.trim()}
            className="px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium disabled:opacity-50">
            Create key
          </button>
        </div>

        {/* List */}
        <div className="bg-card border border-border rounded-xl p-5">
          <h2 className="text-sm font-semibold text-foreground mb-3">Keys ({keys.length})</h2>
          {keys.length === 0 ? <p className="text-sm text-muted-foreground">No keys yet.</p> : (
            <div className="space-y-2">
              {keys.map(k => (
                <div key={k.id} className="flex items-center gap-3 text-sm border-b border-border/50 last:border-0 py-2">
                  <span className="font-medium text-foreground w-40 truncate">{k.name}</span>
                  {k.run_on_attach && <span className="text-xs px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400">run-on-attach</span>}
                  {!k.enabled && <span className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">disabled</span>}
                  <span className="text-xs text-muted-foreground flex-1">{k.blueprint_ids.length} blueprint(s)</span>
                  <button onClick={() => removeKey(k.id)} className="text-xs text-muted-foreground hover:text-red-400">delete</button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
