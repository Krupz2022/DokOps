import { useEffect, useState } from "react";
import api from "../lib/api";
import { useToast } from "../context/ToastContext";
import type { Blueprint, BlueprintSource, BlueprintAssignment } from "../types/blueprint";

interface Org { id: string; name: string; }

export default function Blueprints() {
  const { toast } = useToast();
  const [list, setList] = useState<Blueprint[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [yamlBody, setYamlBody] = useState("resources: []");
  const [sources, setSources] = useState<BlueprintSource[]>([]);
  const [assignments, setAssignments] = useState<BlueprintAssignment[]>([]);
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [newScopeType, setNewScopeType] = useState<"org" | "group" | "minion">("minion");
  const [newScopeId, setNewScopeId] = useState("");
  const [newSourceName, setNewSourceName] = useState("");

  async function loadList() {
    const r = await api.get("/blueprints");
    setList(r.data as Blueprint[]);
  }
  useEffect(() => {
    loadList();
    api.get("/organisations").then(r => setOrgs(r.data as Org[])).catch(() => setOrgs([]));
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
  }

  function newBlueprint() {
    setSelectedId(null);
    setName("");
    setYamlBody("resources: []");
    setSources([]);
    setAssignments([]);
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

  async function saveSource(sourceName: string, content: string) {
    if (!selectedId) { toast("Save the blueprint first", "error"); return; }
    await api.put(`/blueprints/${selectedId}/sources/${encodeURIComponent(sourceName)}`, { content });
    const src = await api.get(`/blueprints/${selectedId}/sources`);
    setSources(src.data as BlueprintSource[]);
    setNewSourceName("");
    toast("Source saved", "success");
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

  return (
    <div className="p-6 w-full max-w-[100rem] mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground leading-tight">Blueprints</h1>
          <p className="text-sm text-muted-foreground mt-1 max-w-xl">
            Declarative desired-state configs. Assign to an org, group, or minion and apply across your fleet.
          </p>
        </div>
        <button onClick={newBlueprint}
          className="shrink-0 px-3.5 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium">
          + New blueprint
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[15rem_1fr] gap-6 items-start">
        {/* List */}
        <aside className="bg-card border border-border rounded-xl p-2">
          {list.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center px-3 py-8">No blueprints yet.<br />Create one to get started.</p>
          ) : (
            <div className="space-y-0.5">
              {list.map(b => (
                <button key={b.id} onClick={() => selectBlueprint(b.id)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${selectedId === b.id ? "bg-primary/10 text-primary font-medium" : "text-foreground hover:bg-muted/50"}`}>
                  {b.name}
                </button>
              ))}
            </div>
          )}
        </aside>

        {/* Editor */}
        <section className="space-y-5 min-w-0">
          <div className="bg-card border border-border rounded-xl p-5 space-y-4">
            <div>
              <label className="text-xs text-muted-foreground uppercase tracking-wider">Name</label>
              <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. web-baseline"
                className="w-full mt-1 bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground uppercase tracking-wider">YAML</label>
              <textarea value={yamlBody} onChange={e => setYamlBody(e.target.value)} rows={18} spellCheck={false}
                className="w-full mt-1 bg-background border border-border rounded-lg px-3 py-2 font-mono text-xs text-foreground leading-relaxed resize-y focus:outline-none focus:ring-1 focus:ring-primary" />
            </div>
            <div className="flex items-center gap-3">
              <button onClick={save} className="px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium">
                {selectedId ? "Save changes" : "Create blueprint"}
              </button>
              {selectedId && <span className="text-xs text-muted-foreground">Editing “{name}”</span>}
            </div>
          </div>

          <div className="grid xl:grid-cols-2 gap-5 items-start">
        {/* Sources */}
        <details open className="bg-card border border-border rounded-xl p-5">
          <summary className="text-sm font-semibold text-foreground cursor-pointer">Sources ({sources.length})</summary>
          <div className="mt-3 space-y-3">
            {sources.map(s => (
              <SourceEditor key={s.id} source={s} onSave={(content) => saveSource(s.name, content)} />
            ))}
            <div className="flex gap-2">
              <input value={newSourceName} onChange={e => setNewSourceName(e.target.value)} placeholder="new source name (e.g. nginx.conf)"
                className="flex-1 bg-background border border-border rounded px-2 py-1 text-xs text-foreground" />
              <button onClick={() => newSourceName.trim() && saveSource(newSourceName.trim(), "")}
                className="text-xs px-2 py-1 rounded bg-primary/10 text-primary hover:bg-primary/20">Add</button>
            </div>
            <p className="text-[11px] text-muted-foreground">Source deletion isn't available in v1.</p>
          </div>
        </details>

        {/* Assignments */}
        <details open className="bg-card border border-border rounded-xl p-5">
          <summary className="text-sm font-semibold text-foreground cursor-pointer">Assignments ({assignments.length})</summary>
          <div className="mt-3 space-y-2">
            {assignments.map(a => (
              <div key={a.id} className="flex items-center gap-2 text-sm">
                <span className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground w-14 text-center">{a.scope_type}</span>
                <span className="font-mono text-foreground flex-1 truncate">{a.scope_id}</span>
                <button onClick={() => removeAssignment(a.id)} className="text-xs text-muted-foreground hover:text-red-400">remove</button>
              </div>
            ))}
            <div className="flex gap-2 items-center pt-1">
              <select value={newScopeType} onChange={e => setNewScopeType(e.target.value as "org" | "group" | "minion")}
                className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground">
                <option value="org">org</option>
                <option value="group">group</option>
                <option value="minion">minion</option>
              </select>
              {newScopeType === "org" ? (
                <select value={newScopeId} onChange={e => setNewScopeId(e.target.value)}
                  className="flex-1 bg-background border border-border rounded px-2 py-1 text-xs text-foreground">
                  <option value="">select org…</option>
                  {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
              ) : (
                <input value={newScopeId} onChange={e => setNewScopeId(e.target.value)}
                  placeholder={newScopeType === "group" ? "group id" : "minion id"}
                  className="flex-1 bg-background border border-border rounded px-2 py-1 text-xs text-foreground" />
              )}
              <button onClick={addAssignment} disabled={!selectedId || !newScopeId.trim()}
                className="text-xs px-2 py-1 rounded bg-primary/10 text-primary hover:bg-primary/20 disabled:opacity-50">Add</button>
            </div>
            {!selectedId && <p className="text-[11px] text-muted-foreground">Save the blueprint before assigning.</p>}
          </div>
        </details>
          </div>
        </section>
      </div>
    </div>
  );
}

function SourceEditor({ source, onSave }: { source: BlueprintSource; onSave: (content: string) => void }) {
  const [content, setContent] = useState(source.content);
  return (
    <div className="border border-border rounded-lg p-2">
      <div className="flex items-center justify-between mb-1">
        <span className="font-mono text-xs text-foreground">{source.name}</span>
        <button onClick={() => onSave(content)} className="text-xs text-primary hover:underline">save</button>
      </div>
      <textarea value={content} onChange={e => setContent(e.target.value)} rows={4} spellCheck={false}
        className="w-full bg-background border border-border rounded px-2 py-1 font-mono text-xs text-foreground" />
    </div>
  );
}
