import { useEffect, useState } from "react";
import { KeyRound, ChevronUp, ChevronDown, Trash2, RefreshCw } from "lucide-react";
import api from "../lib/api";
import { useToast } from "../context/ToastContext";
import type { ActivationKey, CreatedKey } from "../types/activationKey";
import type { Blueprint } from "../types/blueprint";
import { Button } from "../components/ui/Button";
import {
  FleetPage, FleetStat, Surface, CopyBlock, Eyebrow, fieldCls,
} from "../components/fleet/FleetPage";

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
    <FleetPage
      icon={KeyRound}
      title="Activation keys"
      subtitle="A key attaches blueprints to onboarding. Install with -Key <value>; if “run on attach” is on, its blueprints apply once."
      vitals={
        <>
          <FleetStat value={keys.length} label="keys" tone="cyan" />
          <FleetStat value={blueprints.length} label="blueprints" tone="purple" />
        </>
      }
    >
      {/* Enrollment token */}
      <Surface className="p-4 mb-6">
        <Eyebrow className="mb-1">Enrollment token</Eyebrow>
        <p className="text-xs text-muted-foreground mb-3 max-w-2xl">
          The shared <code>-Token</code> every minion installs with — a matching token auto-accepts the machine on connect.
          Stored hashed, so copy it for your install commands.
        </p>
        <div className="flex gap-2 items-center max-w-2xl">
          <input value={tokenInput} onChange={e => setTokenInput(e.target.value)} placeholder="enrollment token value"
            className={fieldCls + " flex-1 font-mono text-xs"} />
          <Button variant="outline" size="sm" onClick={genToken}><RefreshCw className="w-3.5 h-3.5" /> Generate</Button>
          <Button size="sm" onClick={saveToken} disabled={!tokenInput.trim()}>Save</Button>
          {tokenSaved && <span className="text-xs text-emerald-400">saved</span>}
        </div>
      </Surface>

      {created && (
        <Surface className="mb-6 p-4 border-primary/40 space-y-3">
          <p className="text-sm font-semibold text-foreground">
            Key “{created.key.name}” created — copy the value now (shown once):
          </p>
          <CopyBlock value={created.value} />
          <CopyBlock label="Windows install command" value={installPs} />
          <button onClick={() => setCreated(null)} className="text-xs text-muted-foreground hover:text-foreground">dismiss</button>
        </Surface>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[22rem_1fr] gap-6 items-start">
        {/* Create */}
        <Surface className="p-5 space-y-3">
          <Eyebrow>New key</Eyebrow>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="key name (e.g. win-web)" className={fieldCls} />
          <select value={orgId} onChange={e => { setOrgId(e.target.value); setGroupId(""); }} className={fieldCls}>
            <option value="">org (optional)…</option>
            {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
          <select value={groupId} onChange={e => setGroupId(e.target.value)} className={fieldCls}>
            <option value="">group (optional)…</option>
            {groups.filter(g => !orgId || (g as Group & { org_id?: string }).org_id === orgId)
                   .map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input type="checkbox" className="accent-primary" checked={runOnAttach} onChange={e => setRunOnAttach(e.target.checked)} />
            Run blueprints on attach
          </label>

          <div>
            <Eyebrow className="mb-1.5">Blueprints</Eyebrow>
            <div className="space-y-1 max-h-48 overflow-auto">
              {blueprints.map(b => (
                <label key={b.id} className="flex items-center gap-2 text-sm text-foreground">
                  <input type="checkbox" className="accent-primary" checked={picked.includes(b.id)} onChange={() => toggle(b.id)} />
                  {b.name}
                </label>
              ))}
              {blueprints.length === 0 && <p className="text-xs text-muted-foreground">No blueprints yet.</p>}
            </div>
            {picked.length > 0 && (
              <div className="mt-3">
                <Eyebrow className="mb-1.5">Run order (top runs first)</Eyebrow>
                <div className="space-y-1">
                  {picked.map((id, i) => (
                    <div key={id} className="flex items-center gap-2 text-sm bg-background border border-border rounded-lg px-2 py-1">
                      <span className="text-muted-foreground font-mono w-5 text-right text-xs">{i + 1}</span>
                      <span className="flex-1 truncate text-foreground">{bpName(id)}</span>
                      <button onClick={() => move(i, -1)} disabled={i === 0} title="Move up"
                        className="p-0.5 text-muted-foreground hover:text-foreground disabled:opacity-30"><ChevronUp className="w-4 h-4" /></button>
                      <button onClick={() => move(i, 1)} disabled={i === picked.length - 1} title="Move down"
                        className="p-0.5 text-muted-foreground hover:text-foreground disabled:opacity-30"><ChevronDown className="w-4 h-4" /></button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <Button onClick={createKey} disabled={!name.trim()} className="w-full">Create key</Button>
        </Surface>

        {/* List */}
        <Surface className="p-5">
          <Eyebrow className="mb-3">Keys ({keys.length})</Eyebrow>
          {keys.length === 0 ? <p className="text-sm text-muted-foreground">No keys yet.</p> : (
            <div className="divide-y divide-border/60">
              {keys.map(k => (
                <div key={k.id} className="flex items-center gap-3 text-sm py-2.5 group">
                  <span className="font-medium text-foreground w-40 truncate">{k.name}</span>
                  {k.run_on_attach && <span className="tag tag-amber">run-on-attach</span>}
                  {!k.enabled && <span className="tag">disabled</span>}
                  <span className="text-xs text-muted-foreground flex-1">{k.blueprint_ids.length} blueprint(s)</span>
                  <button onClick={() => removeKey(k.id)} title="Delete key"
                    className="opacity-0 group-hover:opacity-100 focus:opacity-100 inline-flex items-center justify-center w-7 h-7 rounded-md text-muted-foreground hover:text-red-400 hover:bg-red-500/10 transition-all">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </Surface>
      </div>
    </FleetPage>
  );
}
