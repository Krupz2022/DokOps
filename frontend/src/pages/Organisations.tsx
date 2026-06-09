import { useEffect, useState } from "react";
import api from "../lib/api";
import { useConfirm } from "../context/ConfirmContext";
import { useToast } from "../context/ToastContext";

interface Org { id: string; name: string; slug: string; }
interface Group { id: string; name: string; description: string | null; org_id: string; member_ids: string[]; }
interface Minion { id: string; hostname: string; status: string; }

export default function Organisations() {
  const { confirm } = useConfirm();
  const { toast } = useToast();
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [groups, setGroups] = useState<Record<string, Group[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [minions, setMinions] = useState<Minion[]>([]);
  const [newOrgName, setNewOrgName] = useState("");
  const [newOrgSlug, setNewOrgSlug] = useState("");
  const [creating, setCreating] = useState(false);
  const [newGroupName, setNewGroupName] = useState<Record<string, string>>({});
  // add-minion picker state: orgId → selected minion id
  const [addPick, setAddPick] = useState<Record<string, string>>({});

  useEffect(() => {
    api.get("/organisations/").then(r => setOrgs(r.data));
    api.get("/minions/").then(r => setMinions(r.data));
  }, []);

  // Auto-derive slug from name
  function handleOrgNameChange(val: string) {
    setNewOrgName(val);
    setNewOrgSlug(val.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""));
  }

  async function createOrg() {
    if (!newOrgName.trim() || !newOrgSlug.trim()) return;
    setCreating(true);
    try {
      const r = await api.post("/organisations/", { name: newOrgName.trim(), slug: newOrgSlug.trim() });
      setOrgs(prev => [...prev, r.data]);
      setNewOrgName(""); setNewOrgSlug("");
    } finally { setCreating(false); }
  }

  async function toggleOrg(orgId: string) {
    if (expanded.has(orgId)) {
      setExpanded(prev => { const n = new Set(prev); n.delete(orgId); return n; });
      return;
    }
    const r = await api.get(`/organisations/${orgId}`);
    setGroups(prev => ({ ...prev, [orgId]: r.data.groups }));
    setExpanded(prev => new Set([...prev, orgId]));
  }

  async function refreshOrg(orgId: string) {
    const r = await api.get(`/organisations/${orgId}`);
    setGroups(prev => ({ ...prev, [orgId]: r.data.groups }));
  }

  async function createGroup(orgId: string) {
    const name = newGroupName[orgId]?.trim();
    if (!name) return;
    const r = await api.post(`/organisations/${orgId}/groups`, { name });
    setGroups(prev => ({ ...prev, [orgId]: [...(prev[orgId] || []), { ...r.data, member_ids: [] }] }));
    setNewGroupName(prev => ({ ...prev, [orgId]: "" }));
  }

  async function deleteOrg(orgId: string) {
    const ok = await confirm({ title: "Delete organisation", description: "This will remove the organisation and all its groups. Continue?", variant: "danger", confirmLabel: "Delete" });
    if (!ok) return;
    try {
      await api.delete(`/organisations/${orgId}`);
      setOrgs(prev => prev.filter(o => o.id !== orgId));
    } catch (err: any) {
      toast(err?.response?.status === 403 ? "God Mode required to delete organisations." : "Delete failed.", "error");
    }
  }

  async function deleteGroup(orgId: string, groupId: string) {
    const ok = await confirm({ title: "Delete group", description: "Remove this group and all its members?", variant: "danger", confirmLabel: "Delete" });
    if (!ok) return;
    try {
      await api.delete(`/organisations/groups/${groupId}`);
      setGroups(prev => ({ ...prev, [orgId]: prev[orgId].filter(x => x.id !== groupId) }));
    } catch (err: any) {
      toast(err?.response?.status === 403 ? "God Mode required to delete groups." : "Delete failed.", "error");
    }
  }

  async function moveMinion(orgId: string, minionId: string, toGroupId: string) {
    await api.post(`/organisations/${orgId}/assign`, { minion_id: minionId, group_id: toGroupId });
    await refreshOrg(orgId);
  }

  async function addMinion(orgId: string) {
    const minionId = addPick[orgId];
    const orgGroups = groups[orgId] || [];
    // assign to first group if none selected, otherwise need a target — we use the picker group
    if (!minionId) return;
    // If only one group, assign there; otherwise user picks via move dropdown after adding
    const targetGroup = orgGroups[0];
    if (!targetGroup) { toast("Create a group first.", "error"); return; }
    await api.post(`/organisations/${orgId}/assign`, { minion_id: minionId, group_id: targetGroup.id });
    setAddPick(prev => ({ ...prev, [orgId]: "" }));
    await refreshOrg(orgId);
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex justify-between items-start mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Groups</h1>
          <p className="text-muted-foreground text-sm mt-1">Organise minions by customer and environment</p>
        </div>
      </div>

      {/* Create org */}
      <div className="bg-card border border-border rounded-lg p-4 mb-6 flex gap-3">
        <input value={newOrgName} onChange={e => handleOrgNameChange(e.target.value)}
          placeholder="Customer name" className="flex-1 bg-muted border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
        <input value={newOrgSlug} onChange={e => setNewOrgSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
          placeholder="slug" className="w-36 bg-muted border border-border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary" />
        <button onClick={createOrg} disabled={creating || !newOrgName.trim() || !newOrgSlug.trim()}
          className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm disabled:opacity-40">
          Add Organisation
        </button>
      </div>

      {/* Org list */}
      <div className="space-y-3">
        {orgs.map(org => {
          const orgGroups = groups[org.id] || [];
          // minions already assigned anywhere in this org
          const assignedIds = new Set(orgGroups.flatMap(g => g.member_ids));
          const unassigned = minions.filter(m => !assignedIds.has(m.id));

          return (
            <div key={org.id} className="bg-card border border-border rounded-lg overflow-hidden">
              {/* Org header */}
              <div className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-muted/30" onClick={() => toggleOrg(org.id)}>
                <div>
                  <span className="font-medium text-foreground">{org.name}</span>
                  <span className="text-xs text-muted-foreground font-mono ml-2">{org.slug}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-muted-foreground">{orgGroups.length || "?"} groups · {assignedIds.size} minions</span>
                  <span className="text-muted-foreground text-xs">{expanded.has(org.id) ? "▲" : "▼"}</span>
                  <button onClick={e => { e.stopPropagation(); deleteOrg(org.id); }}
                    className="text-xs text-red-400 hover:text-red-300 border border-red-800 px-2 py-1 rounded">Remove</button>
                </div>
              </div>

              {expanded.has(org.id) && (
                <div className="border-t border-border px-4 py-3 space-y-3">
                  {/* Groups */}
                  {orgGroups.map(g => (
                    <div key={g.id} className="bg-muted/20 border border-border rounded-lg overflow-hidden">
                      {/* Group header */}
                      <div className="flex items-center justify-between px-3 py-2 bg-muted/30">
                        <span className="text-sm font-semibold text-foreground">{g.name}</span>
                        <button onClick={() => deleteGroup(org.id, g.id)} className="text-xs text-red-400 hover:text-red-300">Remove group</button>
                      </div>
                      {/* Minion rows */}
                      {g.member_ids.length === 0 ? (
                        <p className="px-3 py-2 text-xs text-muted-foreground">No minions in this group.</p>
                      ) : (
                        g.member_ids.map(mid => {
                          const m = minions.find(x => x.id === mid);
                          const otherGroups = orgGroups.filter(x => x.id !== g.id);
                          return (
                            <div key={mid} className="flex items-center justify-between px-3 py-2 border-t border-border/50">
                              <div className="flex items-center gap-2">
                                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${m?.status === "active" ? "bg-green-500" : m?.status === "pending" ? "bg-yellow-400" : "bg-red-500"}`} />
                                <span className="text-sm font-medium">{m?.hostname ?? mid.slice(0, 8)}</span>
                                <span className="text-xs text-muted-foreground font-mono">{mid.slice(0, 8)}…</span>
                              </div>
                              {otherGroups.length > 0 && (
                                <select
                                  defaultValue=""
                                  onChange={e => { if (e.target.value) moveMinion(org.id, mid, e.target.value); e.target.value = ""; }}
                                  className="bg-muted border border-border rounded px-2 py-0.5 text-xs text-muted-foreground"
                                >
                                  <option value="" disabled>Move to…</option>
                                  {otherGroups.map(og => <option key={og.id} value={og.id}>{og.name}</option>)}
                                </select>
                              )}
                            </div>
                          );
                        })
                      )}
                    </div>
                  ))}

                  {/* Add group */}
                  <div className="flex gap-2">
                    <input value={newGroupName[org.id] || ""} onChange={e => setNewGroupName(p => ({ ...p, [org.id]: e.target.value }))}
                      placeholder="New group name (e.g. qa, prod)" className="flex-1 bg-muted border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
                    <button onClick={() => createGroup(org.id)} className="px-3 py-1.5 bg-primary text-primary-foreground rounded-lg text-sm">Add Group</button>
                  </div>

                  {/* Add unassigned minion */}
                  {unassigned.length > 0 && orgGroups.length > 0 && (
                    <div className="flex gap-2 pt-1 border-t border-border/50">
                      <select value={addPick[org.id] || ""} onChange={e => setAddPick(p => ({ ...p, [org.id]: e.target.value }))}
                        className="flex-1 bg-muted border border-border rounded-lg px-3 py-1.5 text-sm">
                        <option value="">Add unassigned minion…</option>
                        {unassigned.map(m => <option key={m.id} value={m.id}>{m.hostname}</option>)}
                      </select>
                      <button onClick={() => addMinion(org.id)} disabled={!addPick[org.id]}
                        className="px-3 py-1.5 bg-primary text-primary-foreground rounded-lg text-sm disabled:opacity-40">Add</button>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
