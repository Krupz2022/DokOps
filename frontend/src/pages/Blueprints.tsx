import { useEffect, useState } from "react";
import { ScrollText, Plus, ArrowLeft, ChevronRight, ChevronDown, Trash2, RefreshCw } from "lucide-react";
import api from "../lib/api";
import { cn } from "../lib/utils";
import { useToast } from "../context/ToastContext";
import { useConfirm } from "../context/ConfirmContext";
import { useAppContext } from "../context/AppContext";
import type { Blueprint, BlueprintSource, BlueprintAssignment } from "../types/blueprint";
import { Button } from "../components/ui/Button";
import {
  FleetPage, FleetStat, Surface, Eyebrow, fieldCls,
} from "../components/fleet/FleetPage";

interface Org { id: string; name: string; slug?: string; }
interface Group { id: string; name: string; }
interface MinionLite { id: string; hostname: string; }

export default function Blueprints() {
  const { toast } = useToast();
  const { confirm } = useConfirm();
  const { isSuperuser } = useAppContext();
  const [reseeding, setReseeding] = useState(false);
  const [list, setList] = useState<Blueprint[]>([]);
  const [editing, setEditing] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [yamlBody, setYamlBody] = useState("resources: []");
  const [sources, setSources] = useState<BlueprintSource[]>([]);
  const [assignments, setAssignments] = useState<BlueprintAssignment[]>([]);
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [minions, setMinions] = useState<MinionLite[]>([]);
  const [newScopeType, setNewScopeType] = useState<"org" | "group" | "minion">("minion");
  const [newScopeId, setNewScopeId] = useState("");
  const [collapsedOrgs, setCollapsedOrgs] = useState<Set<string>>(new Set());

  function toggleOrg(key: string) {
    setCollapsedOrgs(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  // Resolve a stored scope id to a human-readable name (falls back to the id).
  function scopeLabel(type: string, id: string): string {
    if (type === "org") return orgs.find(o => o.id === id)?.name ?? id;
    if (type === "group") return groups.find(g => g.id === id)?.name ?? id;
    if (type === "minion") return minions.find(m => m.id === id)?.hostname ?? id;
    return id;
  }

  async function loadList() {
    const r = await api.get("/blueprints");
    setList(r.data as Blueprint[]);
  }
  useEffect(() => {
    loadList();
    api.get("/organisations").then(r => setOrgs(r.data as Org[])).catch(() => setOrgs([]));
    api.get("/organisations/groups").then(r => setGroups(r.data as Group[])).catch(() => setGroups([]));
    api.get("/minions").then(r => setMinions(r.data as MinionLite[])).catch(() => setMinions([]));
  }, []);

  async function selectBlueprint(id: string) {
    const [bp, src, asn] = await Promise.all([
      api.get(`/blueprints/${id}`),
      api.get(`/blueprints/${id}/sources`),
      api.get(`/blueprints/${id}/assignments`),
    ]);
    const b = bp.data as Blueprint;
    setSelectedId(b.id);
    setName(b.name);
    setYamlBody(b.yaml_body);
    setSources(src.data as BlueprintSource[]);
    setAssignments(asn.data as BlueprintAssignment[]);
    setEditing(true);
  }

  function newBlueprint() {
    setSelectedId(null);
    setName("");
    setYamlBody("resources: []");
    setSources([]);
    setAssignments([]);
    setEditing(true);
  }

  function backToList() {
    setEditing(false);
    loadList();
  }

  async function reseed() {
    setReseeding(true);
    try {
      const r = await api.post("/blueprints/reseed");
      const removed = r.data?.removed ?? 0;
      toast(`Re-seeded ${r.data?.seeded ?? 0} from folder${removed ? `, removed ${removed} stale` : ""}`, "success");
      loadList();
    } catch {
      toast("Re-seed failed", "error");
    } finally {
      setReseeding(false);
    }
  }

  async function deleteBlueprint(id: string) {
    const ok = await confirm({
      title: "Delete blueprint",
      description: "Remove this blueprint, its sources, and assignments? If it was seeded from a blueprints/ folder, it will reappear on the next backend restart unless you also delete the folder.",
      variant: "danger",
      confirmLabel: "Delete",
    });
    if (!ok) return;
    try {
      await api.delete(`/blueprints/${id}`);
      toast("Blueprint deleted", "success");
      if (selectedId === id) setEditing(false);
      loadList();
    } catch {
      toast("Delete failed", "error");
    }
  }

  async function save() {
    try {
      if (selectedId) {
        await api.put(`/blueprints/${selectedId}`, { name, yaml_body: yamlBody });
        toast("Blueprint saved", "success");
      } else {
        const r = await api.post("/blueprints", { name, yaml_body: yamlBody });
        toast("Blueprint created", "success");
        await loadList();
        await selectBlueprint((r.data as Blueprint).id);
        return;
      }
      loadList();
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } };
      toast(err.response?.status === 409 ? "Blueprint name already exists" : (err.response?.data?.detail ?? "Save failed"), "error");
    }
  }

  async function addAssignment() {
    if (!selectedId || !newScopeId.trim()) return;
    await api.post(`/blueprints/${selectedId}/assignments`, { scope_type: newScopeType, scope_id: newScopeId.trim() });
    const asn = await api.get(`/blueprints/${selectedId}/assignments`);
    setAssignments(asn.data as BlueprintAssignment[]);
    setNewScopeId("");
  }
  async function removeAssignment(id: string) {
    await api.delete(`/blueprints/assignments/${id}`);
    setAssignments(assignments.filter(a => a.id !== id));
  }

  /* ── List view (grouped per org) ───────────────────────────────────────── */
  if (!editing) {
    const orgIdSet = new Set(orgs.map(o => o.id));
    const unassigned = list.filter(b => !(b.org_ids ?? []).some(id => orgIdSet.has(id)));
    const groupsToRender = [
      ...orgs.map(o => ({ key: o.id, title: o.name, slug: o.slug ?? "", items: list.filter(b => (b.org_ids ?? []).includes(o.id)) })),
      ...(unassigned.length ? [{ key: "__unassigned", title: "Unassigned", slug: "", items: unassigned }] : []),
    ];
    return (
      <FleetPage
        icon={ScrollText}
        title="Blueprints"
        subtitle="Declarative desired-state configs, grouped by org. Assign to an org, group, or minion and apply across your fleet."
        vitals={<FleetStat value={list.length} label="blueprints" tone="purple" />}
        actions={
          <div className="flex items-center gap-2">
            {isSuperuser && (
              <Button variant="outline" size="sm" onClick={reseed} disabled={reseeding} title="Re-run the folder seed (picks up YAML added to backend/app/blueprints/ without a restart)">
                <RefreshCw className={cn("w-3.5 h-3.5", reseeding && "animate-spin")} /> Re-seed
              </Button>
            )}
            <Button size="sm" onClick={newBlueprint}><Plus className="w-3.5 h-3.5" /> New blueprint</Button>
          </div>
        }
      >
        {list.length === 0 ? (
          <Surface className="p-12 text-center">
            <ScrollText className="w-8 h-8 text-muted-foreground/40 mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">No blueprints yet — create one to get started.</p>
          </Surface>
        ) : (
          <div className="space-y-3">
            {groupsToRender.map(g => {
              const open = !collapsedOrgs.has(g.key);
              return (
                <Surface key={g.key} className="overflow-hidden">
                  <div className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-secondary/40 transition-colors" onClick={() => toggleOrg(g.key)}>
                    <div className="flex items-center gap-2 min-w-0">
                      {open ? <ChevronDown className="w-4 h-4 text-muted-foreground flex-shrink-0" /> : <ChevronRight className="w-4 h-4 text-muted-foreground flex-shrink-0" />}
                      <span className="font-medium text-foreground truncate">{g.title}</span>
                      {g.slug && <span className="text-xs text-muted-foreground font-mono">{g.slug}</span>}
                    </div>
                    <span className="text-xs text-muted-foreground flex-shrink-0">{g.items.length} blueprint{g.items.length === 1 ? "" : "s"}</span>
                  </div>
                  {open && (
                    <div className="border-t border-border/70 divide-y divide-border/70">
                      {g.items.length === 0 ? (
                        <p className="px-4 py-3 text-xs text-muted-foreground">No blueprints in this org yet.</p>
                      ) : g.items.map(b => (
                        <div key={b.id} onClick={() => selectBlueprint(b.id)}
                          className="group w-full text-left flex items-center gap-3 px-4 py-2.5 hover:bg-secondary/40 transition-colors cursor-pointer">
                          <ScrollText className="w-4 h-4 text-muted-foreground group-hover:text-primary transition-colors flex-shrink-0" />
                          <span className="font-medium text-foreground truncate flex-1" title={b.name}>{shortName(b.name)}</span>
                          <span className="text-[11px] text-muted-foreground font-mono flex-shrink-0">
                            {b.updated_at ? new Date(b.updated_at).toLocaleDateString() : "—"}
                          </span>
                          <button onClick={e => { e.stopPropagation(); deleteBlueprint(b.id); }} title="Delete blueprint"
                            className="opacity-0 group-hover:opacity-100 focus:opacity-100 inline-flex items-center justify-center w-7 h-7 rounded-md text-muted-foreground hover:text-red-400 hover:bg-red-500/10 transition-all flex-shrink-0">
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                          <ChevronRight className="w-4 h-4 text-muted-foreground/40 group-hover:text-primary transition-colors flex-shrink-0" />
                        </div>
                      ))}
                    </div>
                  )}
                </Surface>
              );
            })}
          </div>
        )}
      </FleetPage>
    );
  }

  /* ── Editor view ───────────────────────────────────────────────────────── */
  return (
    <FleetPage
      icon={ScrollText}
      title={selectedId ? name || "Blueprint" : "New blueprint"}
      subtitle={selectedId ? "Set assignments and edit the desired-state YAML. Sources are seeded from the scope's files/ folder." : "Name it and save, then set assignments and edit the YAML."}
      actions={
        <div className="flex items-center gap-2">
          {selectedId && (
            <Button variant="outline" size="sm" onClick={() => deleteBlueprint(selectedId)}
              className="text-red-400 hover:text-red-400 hover:bg-red-500/10 border-red-500/30">
              <Trash2 className="w-3.5 h-3.5" /> Delete
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={backToList}><ArrowLeft className="w-3.5 h-3.5" /> All blueprints</Button>
        </div>
      }
    >
      {/* Name + save */}
      <Surface className="p-4 mb-5">
        <div className="flex flex-col sm:flex-row gap-3 sm:items-end">
          <div className="flex-1">
            <Eyebrow className="mb-1">Name</Eyebrow>
            <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. web-baseline" className={fieldCls} />
          </div>
          <Button onClick={save} disabled={!name.trim()}>{selectedId ? "Save changes" : "Create blueprint"}</Button>
        </div>
      </Surface>

      {/* Sources + Assignments on top */}
      <div className="grid lg:grid-cols-2 gap-5 items-start mb-5">
        <Surface className="p-5">
          <Eyebrow className="mb-3">Sources ({sources.length})</Eyebrow>
          {sources.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No sources attached. Drop files in this scope's <code>files/</code> folder to ship them.
            </p>
          ) : (
            <div className="space-y-2">
              {sources.map(s => (
                <div key={s.id} className="border border-border rounded-lg px-3 py-2 bg-background/40 flex items-center gap-3">
                  <span className="font-mono text-xs text-foreground flex-1 truncate" title={s.name}>{s.name}</span>
                  <span className="text-xs text-muted-foreground flex-shrink-0">
                    {s.encoding === "base64" ? "binary" : "text"} · {fmtSize(s.size ?? 0)}
                  </span>
                </div>
              ))}
            </div>
          )}
          <p className="text-[11px] text-muted-foreground mt-3">
            Read-only — sources come from the scope's <code>files/</code> folder and are referenced by a resource's <code>source:</code>.
          </p>
        </Surface>

        <Surface className="p-5">
          <Eyebrow className="mb-3">Assignments ({assignments.length})</Eyebrow>
          <div className="space-y-2">
            {assignments.map(a => (
              <div key={a.id} className="flex items-center gap-2 text-sm group">
                <span className="tag w-16 justify-center">{a.scope_type}</span>
                <span className="text-foreground flex-1 truncate" title={a.scope_id}>{scopeLabel(a.scope_type, a.scope_id)}</span>
                <button onClick={() => removeAssignment(a.id)} className="text-xs text-muted-foreground hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity">remove</button>
              </div>
            ))}
            <div className="flex gap-2 items-center pt-1">
              <select value={newScopeType}
                onChange={e => { setNewScopeType(e.target.value as "org" | "group" | "minion"); setNewScopeId(""); }}
                className={cn(fieldCls, "w-24 py-1.5 text-xs")}>
                <option value="org">org</option>
                <option value="group">group</option>
                <option value="minion">minion</option>
              </select>
              <select value={newScopeId} onChange={e => setNewScopeId(e.target.value)} className={cn(fieldCls, "flex-1 w-auto py-1.5 text-xs")}>
                <option value="">select {newScopeType}…</option>
                {newScopeType === "org" && orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                {newScopeType === "group" && groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                {newScopeType === "minion" && minions.map(m => <option key={m.id} value={m.id}>{m.hostname || m.id}</option>)}
              </select>
              <Button size="sm" variant="outline" onClick={addAssignment} disabled={!selectedId || !newScopeId.trim()}>Add</Button>
            </div>
            {!selectedId && <p className="text-[11px] text-muted-foreground">Save the blueprint before assigning.</p>}
          </div>
        </Surface>
      </div>

      {/* YAML editor — the workspace */}
      <Surface className="p-5">
        <Eyebrow className="mb-1">Desired-state YAML</Eyebrow>
        <textarea value={yamlBody} onChange={e => setYamlBody(e.target.value)} rows={22} spellCheck={false}
          className={fieldCls + " font-mono text-xs leading-relaxed resize-y"} />
        <div className="flex items-center gap-3 mt-3">
          <Button onClick={save} disabled={!name.trim()}>{selectedId ? "Save changes" : "Create blueprint"}</Button>
        </div>
      </Surface>
    </FleetPage>
  );
}

function fmtSize(n: number): string {
  return n < 1024 ? `${n} B` : `${Math.ceil(n / 1024)} KB`;
}

// Seeded blueprints are path-encoded (e.g. "orgs/win/test.yaml"); under an org group
// show just the leaf so the list reads cleanly. Full name stays in the row's title.
function shortName(name: string): string {
  return /^(orgs|groups|minions)\//.test(name) ? (name.split("/").pop() || name) : name;
}
