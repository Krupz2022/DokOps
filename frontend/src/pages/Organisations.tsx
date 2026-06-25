import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Building2, ChevronDown, ChevronRight, Trash2, Plus } from "lucide-react";
import api from "../lib/api";
import { useConfirm } from "../context/ConfirmContext";
import { useToast } from "../context/ToastContext";
import { Button } from "../components/ui/Button";
import {
  FleetPage, FleetStat, MinionStatusDot, Surface, fieldCls,
} from "../components/fleet/FleetPage";

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
    if (!minionId) return;
    const targetGroup = orgGroups[0];
    if (!targetGroup) { toast("Create a group first.", "error"); return; }
    await api.post(`/organisations/${orgId}/assign`, { minion_id: minionId, group_id: targetGroup.id });
    setAddPick(prev => ({ ...prev, [orgId]: "" }));
    await refreshOrg(orgId);
  }

  return (
    <FleetPage
      icon={Building2}
      title="Groups"
      subtitle="Organise minions by customer and environment."
      vitals={
        <>
          <FleetStat value={orgs.length} label="organisations" tone="cyan" />
          <FleetStat value={minions.length} label="minions" tone="blue" />
        </>
      }
    >
      {/* Create org */}
      <Surface className="p-4 mb-6">
        <div className="flex flex-col sm:flex-row gap-3">
          <input value={newOrgName} onChange={e => handleOrgNameChange(e.target.value)}
            placeholder="Customer name" className={fieldCls + " flex-1"} />
          <input value={newOrgSlug} onChange={e => setNewOrgSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
            placeholder="slug" className={fieldCls + " sm:w-40 font-mono"} />
          <Button onClick={createOrg} loading={creating} disabled={!newOrgName.trim() || !newOrgSlug.trim()}>
            <Plus className="w-4 h-4" /> Add organisation
          </Button>
        </div>
      </Surface>

      {orgs.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-12">No organisations yet — add one above.</p>
      ) : (
        <div className="space-y-3">
          {orgs.map(org => {
            const orgGroups = groups[org.id] || [];
            const assignedIds = new Set(orgGroups.flatMap(g => g.member_ids));
            const unassigned = minions.filter(m => !assignedIds.has(m.id));
            const isOpen = expanded.has(org.id);

            return (
              <Surface key={org.id} className="overflow-hidden">
                {/* Org header */}
                <div className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-secondary/40 transition-colors" onClick={() => toggleOrg(org.id)}>
                  <div className="flex items-center gap-2.5 min-w-0">
                    {isOpen ? <ChevronDown className="w-4 h-4 text-muted-foreground flex-shrink-0" /> : <ChevronRight className="w-4 h-4 text-muted-foreground flex-shrink-0" />}
                    <span className="font-medium text-foreground truncate">{org.name}</span>
                    <span className="text-xs text-muted-foreground font-mono">{org.slug}</span>
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0">
                    <span className="text-xs text-muted-foreground">{isOpen ? orgGroups.length : "·"} groups · {assignedIds.size} minions</span>
                    <button onClick={e => { e.stopPropagation(); deleteOrg(org.id); }}
                      title="Delete organisation"
                      className="inline-flex items-center justify-center w-7 h-7 rounded-md text-muted-foreground hover:text-red-400 hover:bg-red-500/10 transition-colors">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {isOpen && (
                  <div className="border-t border-border/70 px-4 py-3 space-y-3">
                    {/* Groups */}
                    {orgGroups.map(g => (
                      <div key={g.id} className="border border-border rounded-lg overflow-hidden bg-background/40">
                        <div className="flex items-center justify-between px-3 py-2 bg-secondary/40">
                          <span className="text-sm font-semibold text-foreground">{g.name}</span>
                          <button onClick={() => deleteGroup(org.id, g.id)}
                            title="Delete group"
                            className="inline-flex items-center justify-center w-6 h-6 rounded text-muted-foreground hover:text-red-400 hover:bg-red-500/10 transition-colors">
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                        {g.member_ids.length === 0 ? (
                          <p className="px-3 py-2 text-xs text-muted-foreground">No minions in this group.</p>
                        ) : (
                          g.member_ids.map(mid => {
                            const m = minions.find(x => x.id === mid);
                            const otherGroups = orgGroups.filter(x => x.id !== g.id);
                            return (
                              <div key={mid} className="flex items-center justify-between px-3 py-2 border-t border-border/50">
                                <Link to={`/infrastructure/minions/${mid}`}
                                  className="group/m flex items-center gap-2 min-w-0 hover:text-primary transition-colors" title="Open minion">
                                  <MinionStatusDot status={m?.status ?? "offline"} className="w-1.5 h-1.5" />
                                  <span className="text-sm font-medium truncate group-hover/m:text-primary group-hover/m:underline">{m?.hostname ?? mid.slice(0, 8)}</span>
                                  <span className="text-xs text-muted-foreground font-mono">{mid.slice(0, 8)}…</span>
                                </Link>
                                {otherGroups.length > 0 && (
                                  <select
                                    defaultValue=""
                                    onChange={e => { if (e.target.value) moveMinion(org.id, mid, e.target.value); e.target.value = ""; }}
                                    className="bg-background border border-border rounded px-2 py-0.5 text-xs text-muted-foreground"
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
                        placeholder="New group name (e.g. qa, prod)" className={fieldCls + " flex-1 py-1.5"} />
                      <Button size="sm" onClick={() => createGroup(org.id)}><Plus className="w-3.5 h-3.5" /> Group</Button>
                    </div>

                    {/* Add unassigned minion */}
                    {unassigned.length > 0 && orgGroups.length > 0 && (
                      <div className="flex gap-2 pt-1 border-t border-border/50">
                        <select value={addPick[org.id] || ""} onChange={e => setAddPick(p => ({ ...p, [org.id]: e.target.value }))}
                          className={fieldCls + " flex-1 py-1.5"}>
                          <option value="">Add unassigned minion…</option>
                          {unassigned.map(m => <option key={m.id} value={m.id}>{m.hostname}</option>)}
                        </select>
                        <Button size="sm" onClick={() => addMinion(org.id)} disabled={!addPick[org.id]}>Add</Button>
                      </div>
                    )}
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
