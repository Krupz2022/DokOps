import { useEffect, useState, useCallback } from "react";
import {
  Trash2, Plus, GitBranch, Zap, X, Check, Layers,
  Users, AlertTriangle, RefreshCw, UserX, Play,
  ArrowRight, RotateCcw, Pencil, ChevronDown, ChevronRight,
} from "lucide-react";
import api from "../lib/api";

interface Stage      { id: string; name: string; order: number; group_id: string; }
interface Pipeline   { id: string; name: string; org_id: string; auto_promote: boolean; stages: Stage[]; }
interface Org        { id: string; name: string; }
interface Group      { id: string; name: string; org_id: string; }
interface Promotion  {
  id: string; to_stage_id: string; from_stage_id: string | null;
  status: string; patch_scope: string; custom_packages: string | null;
  failed_minions: string | null; reboot_minions: string | null;
  excluded_minions: string | null; triggered_by: string; triggered_at: string;
}
interface PatchAlert {
  id: string; pipeline_id: string; stage_id: string;
  reason: string; fired_at: string; acknowledged: boolean;
}

interface AppliedAdvisory {
  advisory_id: string | null;
  package_name: string;
  severity: string;
  advisory_type: string;
  from_version: string;
  to_version: string;
}

interface PromotionResult {
  id: string;
  promotion_id: string;
  minion_id: string;
  hostname: string;
  status: string;
  exit_code: number;
  stdout: string | null;
  applied_advisories: AppliedAdvisory[];
  packages_count: number;
  created_at: string;
}

const STATUS_DOT: Record<string, string> = {
  done:    "bg-emerald-500",
  partial: "bg-amber-400",
  failed:  "bg-red-500",
  running: "bg-blue-400 animate-pulse",
  pending: "bg-muted-foreground/40",
  never:   "bg-muted-foreground/20",
};
const STATUS_PILL: Record<string, string> = {
  done:    "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
  partial: "bg-amber-400/10 text-amber-400 border-amber-400/20",
  failed:  "bg-red-500/10 text-red-400 border-red-500/20",
  running: "bg-blue-400/10 text-blue-400 border-blue-400/20",
  pending: "bg-muted text-muted-foreground border-border",
  never:   "bg-muted text-muted-foreground/40 border-border/50",
};
const REASON_LABELS: Record<string, string> = {
  no_prior_run:             "Prior stage has never been applied",
  prior_stage_not_complete: "Prior stage is still running",
  prior_stage_failed:       "Prior stage failed",
  prior_stage_partial:      "Prior stage has unresolved failures",
};
const SCOPE_OPTIONS = [
  { value: "security", label: "Security" },
  { value: "all",      label: "All updates" },
  { value: "custom",   label: "Custom" },
];

export default function Pipelines() {
  const [orgs, setOrgs]             = useState<Org[]>([]);
  const [groups, setGroups]         = useState<Group[]>([]);
  const [pipelines, setPipelines]   = useState<Pipeline[]>([]);
  const [promotions, setPromotions] = useState<Record<string, Promotion[]>>({});
  const [alerts, setAlerts]         = useState<PatchAlert[]>([]);
  const [promoResults, setPromoResults] = useState<Record<string, PromotionResult[]>>({});
  const [loadingResults, setLoadingResults] = useState<string | null>(null);
  const [expandedResult, setExpandedResult] = useState<string | null>(null);

  const [applyScope, setApplyScope]   = useState<Record<string, string>>({});
  const [applyReboot, setApplyReboot] = useState<Record<string, boolean>>({});
  const [applying, setApplying]       = useState<string | null>(null);
  const [promoting, setPromoting]     = useState<string | null>(null);
  const [retrying, setRetrying]       = useState<string | null>(null);
  const [excluding, setExcluding]     = useState<{ promoId: string; minionId: string } | null>(null);
  const [excludeReason, setExcludeReason] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [deleting, setDeleting]       = useState<string | null>(null);

  // expanded stage panel per pipeline: pipelineId → stageId | null
  const [expandedStage, setExpandedStage] = useState<Record<string, string | null>>({});

  const [showCreate, setShowCreate]         = useState(false);
  const [newName, setNewName]               = useState("");
  const [newOrgId, setNewOrgId]             = useState("");
  const [newAutoPromote, setNewAutoPromote] = useState(false);
  const [creating, setCreating]             = useState(false);

  const [addingStage, setAddingStage]   = useState<string | null>(null);
  const [stageName, setStageName]       = useState("");
  const [stageGroupId, setStageGroupId] = useState("");

  const [editingStage, setEditingStage]     = useState<string | null>(null);
  const [editStageName, setEditStageName]   = useState("");
  const [editStageGroupId, setEditStageGroupId] = useState("");
  const [savingStage, setSavingStage]       = useState(false);

  const loadPromotions = useCallback(async (ids: string[]) => {
    const res = await Promise.all(ids.map(id => api.get(`/patches/pipelines/${id}/promotions`)));
    const map: Record<string, Promotion[]> = {};
    ids.forEach((id, i) => { map[id] = res[i].data; });
    setPromotions(map);
  }, []);

  const loadAlerts = useCallback(async () => {
    const r = await api.get("/patches/alerts/");
    setAlerts(r.data);
  }, []);

  async function loadAll() {
    const orgRes = await api.get("/organisations/");
    const loadedOrgs: Org[] = orgRes.data;
    setOrgs(loadedOrgs);
    const orgDetails = await Promise.all(loadedOrgs.map(o => api.get(`/organisations/${o.id}`)));
    setGroups(orgDetails.flatMap(r => (r.data.groups ?? []) as Group[]));
    const plRes = await Promise.all(loadedOrgs.map(o => api.get(`/patches/organisations/${o.id}/pipelines`)));
    const all: Pipeline[] = plRes.flatMap(r => r.data);
    setPipelines(all);
    setApplyScope(prev => {
      const next = { ...prev };
      all.forEach(p => { if (!next[p.id]) next[p.id] = "security"; });
      return next;
    });
    await Promise.all([loadPromotions(all.map(p => p.id)), loadAlerts()]);
  }

  useEffect(() => { loadAll(); }, []);

  function latestPromo(pipelineId: string, stageId: string): Promotion | undefined {
    return (promotions[pipelineId] ?? [])
      .filter(p => p.to_stage_id === stageId)
      .sort((a, b) => new Date(b.triggered_at).getTime() - new Date(a.triggered_at).getTime())[0];
  }

  async function toggleStage(pipelineId: string, stageId: string) {
    setExpandedStage(prev => ({
      ...prev,
      [pipelineId]: prev[pipelineId] === stageId ? null : stageId,
    }));
    const promo = (promotions[pipelineId] ?? [])
      .filter(p => p.to_stage_id === stageId)
      .sort((a, b) => new Date(b.triggered_at).getTime() - new Date(a.triggered_at).getTime())[0];

    if (promo && !promoResults[promo.id]) {
      setLoadingResults(promo.id);
      try {
        const r = await api.get(`/patches/promotions/${promo.id}/results`);
        setPromoResults(prev => ({ ...prev, [promo.id]: r.data }));
      } finally {
        setLoadingResults(null);
      }
    }
  }

  async function applyToStage(pipelineId: string, stageId: string) {
    setApplying(stageId);
    try {
      await api.post(`/patches/pipelines/${pipelineId}/stages/${stageId}/apply`, {
        scope: applyScope[pipelineId] ?? "security",
        reboot_after: applyReboot[pipelineId] ?? false,
      });
      await loadAll();
    } finally { setApplying(null); }
  }

  async function promoteStage(pipelineId: string, stageId: string) {
    setPromoting(stageId);
    try {
      await api.post(`/patches/pipelines/${pipelineId}/stages/${stageId}/promote`);
      await loadAll();
    } finally { setPromoting(null); }
  }

  async function retryPromo(promoId: string) {
    setRetrying(promoId);
    try {
      await api.post(`/patches/promotions/${promoId}/retry`);
      await loadAll();
    } finally { setRetrying(null); }
  }

  async function excludeMinion() {
    if (!excluding || !excludeReason.trim()) return;
    await api.post(`/patches/promotions/${excluding.promoId}/exclude/${excluding.minionId}`, { reason: excludeReason.trim() });
    setExcluding(null); setExcludeReason(""); await loadAll();
  }

  async function acknowledgeAlert(alertId: string) {
    await api.post(`/patches/alerts/${alertId}/acknowledge`);
    setAlerts(prev => prev.filter(a => a.id !== alertId));
  }

  async function createPipeline() {
    if (!newName.trim() || !newOrgId) return;
    setCreating(true);
    try {
      await api.post(`/patches/organisations/${newOrgId}/pipelines`, { name: newName.trim(), auto_promote: newAutoPromote });
      setNewName(""); setNewOrgId(""); setNewAutoPromote(false); setShowCreate(false);
      await loadAll();
    } finally { setCreating(false); }
  }

  async function addStage(pipelineId: string, count: number) {
    if (!stageName.trim() || !stageGroupId) return;
    await api.post(`/patches/pipelines/${pipelineId}/stages`, { name: stageName.trim(), group_id: stageGroupId, order: count });
    setStageName(""); setStageGroupId(""); setAddingStage(null); await loadAll();
  }

  async function saveStage(pipelineId: string, stageId: string) {
    if (!editStageName.trim() || !editStageGroupId) return;
    setSavingStage(true);
    try {
      await api.patch(`/patches/pipelines/${pipelineId}/stages/${stageId}`, { name: editStageName.trim(), group_id: editStageGroupId });
      setEditingStage(null); await loadAll();
    } finally { setSavingStage(false); }
  }

  async function deletePipeline(pipelineId: string) {
    setDeleting(pipelineId);
    try {
      await api.delete(`/patches/pipelines/${pipelineId}`);
      setPipelines(ps => ps.filter(p => p.id !== pipelineId));
    } finally { setDeleting(null); setConfirmDelete(null); }
  }

  const orgGroupsMap = groups.reduce<Record<string, Group[]>>((acc, g) => {
    acc[g.org_id] = [...(acc[g.org_id] || []), g];
    return acc;
  }, {});

  return (
    <div className="p-6">

      {/* Page header */}
      <div className="flex justify-between items-center mb-6">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
            <GitBranch className="w-4 h-4 text-primary" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-foreground">Patch Pipelines</h1>
            <p className="text-xs text-muted-foreground">Staged rollout across device groups</p>
          </div>
        </div>
        <button onClick={() => setShowCreate(v => !v)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors">
          <Plus className="w-3.5 h-3.5" /> New Pipeline
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="bg-card border border-border rounded-xl p-5 mb-4 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm font-semibold">Create Pipeline</p>
            <button onClick={() => setShowCreate(false)} className="text-muted-foreground hover:text-foreground"><X className="w-4 h-4" /></button>
          </div>
          <div className="grid grid-cols-2 gap-3 mb-3">
            <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Name — e.g. prod-rollout"
              className="bg-muted border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary placeholder:text-muted-foreground/50" />
            <select value={newOrgId} onChange={e => setNewOrgId(e.target.value)}
              className="bg-muted border border-border rounded-lg px-3 py-2 text-sm text-foreground">
              <option value="">Organisation…</option>
              {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer mb-4 select-none">
            <div onClick={() => setNewAutoPromote(v => !v)}
              className={`w-8 h-4 rounded-full flex items-center px-0.5 cursor-pointer transition-colors ${newAutoPromote ? "bg-primary" : "bg-muted border border-border"}`}>
              <div className={`w-3 h-3 rounded-full bg-white shadow transition-transform ${newAutoPromote ? "translate-x-4" : "translate-x-0"}`} />
            </div>
            Auto-promote stages on success
          </label>
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowCreate(false)} className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground">Cancel</button>
            <button onClick={createPipeline} disabled={creating || !newName.trim() || !newOrgId}
              className="px-4 py-1.5 bg-primary text-primary-foreground rounded-lg text-sm font-medium disabled:opacity-40">
              {creating ? "Creating…" : "Create"}
            </button>
          </div>
        </div>
      )}

      {/* Exclude minion modal */}
      {excluding && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card border border-border rounded-xl p-6 w-[400px] shadow-2xl">
            <h3 className="font-semibold mb-1">Exclude Minion</h3>
            <p className="text-xs text-muted-foreground mb-4">
              <code className="font-mono">{excluding.minionId.slice(0, 8)}…</code> will be skipped for this cycle.
            </p>
            <textarea value={excludeReason} onChange={e => setExcludeReason(e.target.value)}
              placeholder="Reason for exclusion (required)" rows={3}
              className="w-full bg-muted border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary resize-none mb-4" />
            <div className="flex gap-2 justify-end">
              <button onClick={() => { setExcluding(null); setExcludeReason(""); }}
                className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground">Cancel</button>
              <button onClick={excludeMinion} disabled={!excludeReason.trim()}
                className="px-4 py-1.5 bg-amber-500 text-white rounded-lg text-sm font-medium disabled:opacity-40">Exclude</button>
            </div>
          </div>
        </div>
      )}

      {/* Pipeline strips */}
      <div className="space-y-2">
        {pipelines.map(p => {
          const org       = orgs.find(o => o.id === p.org_id);
          const stages    = [...p.stages].sort((a, b) => a.order - b.order);
          const orgGroups = orgGroupsMap[p.org_id] || [];
          const scope     = applyScope[p.id] ?? "security";
          const pAlerts   = alerts.filter(a => a.pipeline_id === p.id);
          const active    = expandedStage[p.id];
          const activeStage = stages.find(s => s.id === active);

          return (
            <div key={p.id} className="bg-card border border-border rounded-xl overflow-hidden shadow-sm">

              {/* ── Horizontal strip ── */}
              <div className="flex items-center gap-0 min-h-[56px] px-4">

                {/* Left: identity */}
                <div className="flex items-center gap-2 w-52 shrink-0 pr-3 border-r border-border/60 self-stretch py-3">
                  <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-foreground truncate leading-tight">{p.name}</p>
                    <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                      {org && <span className="text-[10px] px-1.5 py-px bg-muted border border-border rounded-full text-muted-foreground">{org.name}</span>}
                      {p.auto_promote && (
                        <span className="flex items-center gap-0.5 text-[10px] px-1.5 py-px bg-amber-500/10 border border-amber-500/20 rounded-full text-amber-500">
                          <Zap className="w-2 h-2" />auto
                        </span>
                      )}
                      {pAlerts.length > 0 && (
                        <span className="flex items-center gap-0.5 text-[10px] px-1.5 py-px bg-red-500/10 border border-red-500/20 rounded-full text-red-400">
                          <AlertTriangle className="w-2 h-2" />{pAlerts.length}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Middle: stage pills */}
                <div className="flex-1 flex items-center gap-1 overflow-x-auto px-3 py-3 scrollbar-none">
                  {stages.length === 0 ? (
                    <span className="text-xs text-muted-foreground/50 italic flex items-center gap-1.5">
                      <Layers className="w-3.5 h-3.5" /> No stages yet
                    </span>
                  ) : (
                    stages.map((stage, idx) => {
                      const promo     = latestPromo(p.id, stage.id);
                      const status    = promo?.status ?? "never";
                      const group     = groups.find(g => g.id === stage.group_id);
                      const isActive  = active === stage.id;
                      const isLast    = idx === stages.length - 1;

                      return (
                        <div key={stage.id} className="flex items-center gap-1 shrink-0">
                          <button
                            onClick={() => toggleStage(p.id, stage.id)}
                            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-medium transition-all ${
                              isActive
                                ? "bg-primary/10 border-primary/30 text-primary"
                                : "bg-muted/50 border-border/60 text-foreground hover:border-primary/30 hover:bg-muted"
                            }`}
                          >
                            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${STATUS_DOT[status] ?? STATUS_DOT.never}`} />
                            <span className="truncate max-w-[80px]">{stage.name}</span>
                            {group && <span className="text-muted-foreground/60 truncate max-w-[60px] hidden sm:inline">{group.name}</span>}
                            {isActive ? <ChevronDown className="w-3 h-3 shrink-0" /> : <ChevronRight className="w-3 h-3 shrink-0 opacity-40" />}
                          </button>
                          {!isLast && <ArrowRight className="w-3 h-3 text-muted-foreground/30 shrink-0" />}
                        </div>
                      );
                    })
                  )}

                  {/* Inline add stage */}
                  <button
                    onClick={() => { setAddingStage(p.id); setStageName(""); setStageGroupId(""); }}
                    className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs text-muted-foreground/50 hover:text-primary hover:bg-muted transition-colors shrink-0 ml-1"
                  >
                    <Plus className="w-3 h-3" />Stage
                  </button>
                </div>

                {/* Right: scope + reboot + delete */}
                <div className="flex items-center gap-2 pl-3 border-l border-border/60 self-stretch py-3 shrink-0">
                  <div className="flex items-center gap-0.5 bg-muted rounded-lg p-0.5">
                    {SCOPE_OPTIONS.map(opt => (
                      <button key={opt.value}
                        onClick={() => setApplyScope(prev => ({ ...prev, [p.id]: opt.value }))}
                        className={`px-2 py-0.5 rounded-md text-[11px] font-medium transition-colors ${
                          scope === opt.value ? "bg-background text-foreground shadow-sm border border-border/60" : "text-muted-foreground hover:text-foreground"
                        }`}>
                        {opt.label}
                      </button>
                    ))}
                  </div>

                  <button
                    onClick={() => setApplyReboot(prev => ({ ...prev, [p.id]: !(prev[p.id] ?? false) }))}
                    title="Reboot if needed after patching"
                    className={`p-1.5 rounded-lg border text-[11px] transition-colors ${
                      (applyReboot[p.id] ?? false)
                        ? "bg-sky-500/10 border-sky-500/25 text-sky-400"
                        : "bg-muted border-border text-muted-foreground/50 hover:text-foreground"
                    }`}
                  >
                    <RotateCcw className="w-3.5 h-3.5" />
                  </button>

                  {confirmDelete === p.id ? (
                    <div className="flex items-center gap-1">
                      <span className="text-[11px] text-red-400">Sure?</span>
                      <button onClick={() => deletePipeline(p.id)} disabled={deleting === p.id}
                        className="p-1 rounded bg-red-500/15 border border-red-500/30 text-red-400 hover:bg-red-500/25 disabled:opacity-40 transition-colors">
                        <Check className="w-3 h-3" />
                      </button>
                      <button onClick={() => setConfirmDelete(null)}
                        className="p-1 rounded bg-muted border border-border text-muted-foreground hover:text-foreground">
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ) : (
                    <button onClick={() => setConfirmDelete(p.id)}
                      className="p-1.5 rounded-lg text-muted-foreground/30 hover:text-red-400 hover:bg-red-500/10 transition-colors">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>

              {/* ── Alert banners ── */}
              {pAlerts.map(alert => (
                <div key={alert.id} className="mx-4 mb-2 flex items-center gap-3 px-3 py-2 bg-red-500/[0.07] border border-red-500/20 rounded-lg">
                  <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0" />
                  <p className="text-xs text-red-300 flex-1 truncate">
                    <span className="font-medium">{stages.find(s => s.id === alert.stage_id)?.name ?? "Stage"}</span>
                    {" — "}{REASON_LABELS[alert.reason] ?? alert.reason}
                  </p>
                  <button onClick={() => acknowledgeAlert(alert.id)}
                    className="shrink-0 text-[11px] px-2 py-0.5 bg-red-500/15 border border-red-500/25 rounded text-red-300 hover:bg-red-500/25 transition-colors">
                    Dismiss
                  </button>
                </div>
              ))}

              {/* ── Expanded stage panel ── */}
              {activeStage && (() => {
                const promo         = latestPromo(p.id, activeStage.id);
                const status        = promo?.status ?? "never";
                const group         = groups.find(g => g.id === activeStage.group_id);
                const isApplying    = applying === activeStage.id;
                const isPromoting   = promoting === activeStage.id;
                const idx           = stages.findIndex(s => s.id === activeStage.id);
                const isLastStage   = idx === stages.length - 1;
                const canPromote    = status === "done" && !isLastStage;
                const failedMinions: string[] = JSON.parse(promo?.failed_minions ?? "[]");
                const rebootMinions: string[] = JSON.parse(promo?.reboot_minions ?? "[]");

                return (
                  <div className="border-t border-border/60 mx-4 mb-3 mt-1 rounded-lg bg-muted/30 border border-border/40 p-4">
                    <div className="flex items-start justify-between gap-4">

                      {/* Stage meta */}
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className={`w-2 h-2 rounded-full ${STATUS_DOT[status]}`} />
                          <span className="text-sm font-semibold text-foreground">{activeStage.name}</span>
                          <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${STATUS_PILL[status] ?? STATUS_PILL.never}`}>
                            {status === "never" ? "never run" : status}
                          </span>
                          {/* Edit stage inline */}
                          <button onClick={() => {
                            setEditingStage(activeStage.id);
                            setEditStageName(activeStage.name);
                            setEditStageGroupId(activeStage.group_id);
                          }} className="p-0.5 text-muted-foreground/40 hover:text-primary transition-colors">
                            <Pencil className="w-3 h-3" />
                          </button>
                        </div>
                        {group && (
                          <div className="flex items-center gap-1 text-xs text-muted-foreground">
                            <Users className="w-3 h-3" /> {group.name}
                          </div>
                        )}
                        {promo && (
                          <p className="text-[11px] text-muted-foreground/60 mt-1">
                            Last run {new Date(promo.triggered_at).toLocaleString()} by {promo.triggered_by}
                          </p>
                        )}
                      </div>

                      {/* Actions */}
                      <div className="flex items-center gap-2 shrink-0">
                        {canPromote && (
                          <button onClick={() => promoteStage(p.id, activeStage.id)} disabled={isPromoting}
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/10 border border-emerald-500/25 text-emerald-500 rounded-lg text-xs font-semibold hover:bg-emerald-500/20 disabled:opacity-40 transition-colors">
                            {isPromoting ? <span className="w-3 h-3 border border-emerald-500/60 border-t-transparent rounded-full animate-spin" /> : <ArrowRight className="w-3 h-3" />}
                            Promote
                          </button>
                        )}
                        <button onClick={() => applyToStage(p.id, activeStage.id)} disabled={isApplying}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-primary-foreground rounded-lg text-xs font-semibold hover:bg-primary/90 disabled:opacity-40 transition-colors">
                          {isApplying
                            ? <><span className="w-3 h-3 border-2 border-primary-foreground/40 border-t-primary-foreground rounded-full animate-spin" />Applying…</>
                            : <><Play className="w-3 h-3 fill-primary-foreground" />Apply</>
                          }
                        </button>
                      </div>
                    </div>

                    {/* Edit stage form */}
                    {editingStage === activeStage.id && (
                      <div className="mt-3 pt-3 border-t border-border/60 flex gap-2">
                        <input value={editStageName} onChange={e => setEditStageName(e.target.value)}
                          className="flex-1 bg-background border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary" autoFocus />
                        <select value={editStageGroupId} onChange={e => setEditStageGroupId(e.target.value)}
                          className="bg-background border border-border rounded-lg px-3 py-1.5 text-sm text-foreground">
                          <option value="">Group…</option>
                          {orgGroups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                        </select>
                        <button onClick={() => saveStage(p.id, activeStage.id)} disabled={savingStage || !editStageName.trim() || !editStageGroupId}
                          className="px-3 py-1.5 bg-primary text-primary-foreground rounded-lg text-sm font-medium disabled:opacity-40">
                          {savingStage ? "…" : <Check className="w-4 h-4" />}
                        </button>
                        <button onClick={() => setEditingStage(null)} className="p-1.5 text-muted-foreground hover:text-foreground"><X className="w-4 h-4" /></button>
                      </div>
                    )}

                    {/* Failed minions */}
                    {failedMinions.length > 0 && promo && (
                      <div className="mt-3 pt-3 border-t border-amber-500/20">
                        <div className="flex items-center justify-between mb-2">
                          <p className="text-[11px] font-semibold text-amber-400 uppercase tracking-wide">{failedMinions.length} failed</p>
                          <button onClick={() => retryPromo(promo.id)} disabled={retrying === promo.id}
                            className="flex items-center gap-1 text-[11px] px-2 py-0.5 bg-amber-500/10 border border-amber-500/20 text-amber-400 rounded hover:bg-amber-500/20 disabled:opacity-40 transition-colors">
                            <RefreshCw className="w-2.5 h-2.5" />{retrying === promo.id ? "Retrying…" : "Retry all"}
                          </button>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {failedMinions.map(mid => (
                            <div key={mid} className="flex items-center gap-1 px-2 py-0.5 bg-amber-500/5 border border-amber-500/15 rounded text-[11px] font-mono text-muted-foreground">
                              {mid.slice(0, 12)}…
                              <button onClick={() => setExcluding({ promoId: promo.id, minionId: mid })}
                                className="text-muted-foreground/50 hover:text-amber-400 transition-colors ml-0.5">
                                <UserX className="w-2.5 h-2.5" />
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Reboot needed */}
                    {rebootMinions.length > 0 && (
                      <div className="mt-3 pt-3 border-t border-sky-500/20">
                        <p className="text-[11px] font-semibold text-sky-400 uppercase tracking-wide mb-1.5 flex items-center gap-1">
                          <RotateCcw className="w-3 h-3" />{rebootMinions.length} need reboot
                        </p>
                        <div className="flex flex-wrap gap-1.5">
                          {rebootMinions.map(mid => (
                            <span key={mid} className="px-2 py-0.5 bg-sky-500/5 border border-sky-500/15 rounded text-[11px] font-mono text-muted-foreground">{mid.slice(0, 12)}…</span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Per-minion results */}
                    {(() => {
                      const results = promoResults[promo?.id ?? ""] ?? [];
                      if (!promo) return null;
                      if (loadingResults === promo.id) return (
                        <div className="mt-3 pt-3 border-t border-border/60">
                          <p className="text-xs text-muted-foreground animate-pulse">Loading results…</p>
                        </div>
                      );
                      if (results.length === 0) return null;
                      return (
                        <div className="mt-3 pt-3 border-t border-border/60">
                          <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                            Per-minion results ({results.length})
                          </p>
                          <div className="space-y-1">
                            {results.map(r => (
                              <div key={r.id} className="rounded-lg border border-border/60 overflow-hidden">
                                <button
                                  onClick={() => setExpandedResult(expandedResult === r.minion_id ? null : r.minion_id)}
                                  className="w-full flex items-center gap-2 px-3 py-2 hover:bg-muted/40 transition-colors text-left"
                                >
                                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${r.status === "done" ? "bg-emerald-500" : "bg-red-500"}`} />
                                  <span className="text-xs font-medium text-foreground flex-1">{r.hostname}</span>
                                  <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${
                                    r.status === "done"
                                      ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/20"
                                      : "bg-red-500/10 text-red-400 border-red-500/20"
                                  }`}>{r.status}</span>
                                  <span className="text-[10px] text-muted-foreground">{r.packages_count} pkg{r.packages_count !== 1 ? "s" : ""}</span>
                                  {expandedResult === r.minion_id
                                    ? <ChevronDown className="w-3 h-3 text-muted-foreground shrink-0" />
                                    : <ChevronRight className="w-3 h-3 text-muted-foreground/40 shrink-0" />}
                                </button>
                                {expandedResult === r.minion_id && (
                                  <div className="px-3 pb-3 border-t border-border/40 bg-muted/20">
                                    {r.applied_advisories.length > 0 && (
                                      <div className="mt-2">
                                        <p className="text-[10px] text-muted-foreground uppercase font-semibold mb-1.5">Advisories snapshotted</p>
                                        <div className="space-y-1 max-h-40 overflow-y-auto">
                                          {r.applied_advisories.map((a, i) => (
                                            <div key={i} className="flex items-center gap-2 text-[11px]">
                                              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                                                a.severity === "critical" ? "bg-red-500" :
                                                a.severity === "high" ? "bg-orange-400" :
                                                a.severity === "medium" ? "bg-yellow-400" : "bg-muted-foreground/40"
                                              }`} />
                                              <span className="font-mono text-muted-foreground truncate flex-1">
                                                {a.advisory_id ?? a.package_name}
                                              </span>
                                              <span className="text-muted-foreground/50 shrink-0">
                                                {a.from_version} → {a.to_version}
                                              </span>
                                            </div>
                                          ))}
                                        </div>
                                      </div>
                                    )}
                                    {r.stdout && (
                                      <div className="mt-2">
                                        <p className="text-[10px] text-muted-foreground uppercase font-semibold mb-1">Output</p>
                                        <pre className="text-[10px] font-mono text-muted-foreground bg-background border border-border/60 rounded p-2 max-h-28 overflow-y-auto whitespace-pre-wrap break-all">
                                          {r.stdout}
                                        </pre>
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      );
                    })()}
                  </div>
                );
              })()}

              {/* ── Add stage form ── */}
              {addingStage === p.id && (
                <div className="border-t border-border/60 px-4 pb-4 pt-3">
                  <p className="text-xs font-semibold text-foreground mb-2">New Stage</p>
                  <div className="flex gap-2">
                    <input value={stageName} onChange={e => setStageName(e.target.value)}
                      placeholder="Stage name — dev, staging, prod"
                      className="flex-1 bg-muted border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary placeholder:text-muted-foreground/40"
                      autoFocus />
                    <select value={stageGroupId} onChange={e => setStageGroupId(e.target.value)}
                      className="bg-muted border border-border rounded-lg px-3 py-2 text-sm text-foreground">
                      <option value="">Device group…</option>
                      {orgGroups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                    </select>
                    <button onClick={() => addStage(p.id, stages.length)} disabled={!stageName.trim() || !stageGroupId}
                      className="px-3.5 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium disabled:opacity-40 hover:bg-primary/90">Add</button>
                    <button onClick={() => setAddingStage(null)} className="p-2 text-muted-foreground hover:text-foreground"><X className="w-4 h-4" /></button>
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {pipelines.length === 0 && (
          <div className="border border-dashed border-border rounded-xl p-12 text-center">
            <div className="w-10 h-10 rounded-xl bg-muted border border-border flex items-center justify-center mx-auto mb-3">
              <GitBranch className="w-5 h-5 text-muted-foreground/40" />
            </div>
            <p className="text-sm font-medium text-foreground mb-1">No pipelines</p>
            <p className="text-xs text-muted-foreground">Create a pipeline to define a staged rollout — dev → staging → prod.</p>
          </div>
        )}
      </div>
    </div>
  );
}
