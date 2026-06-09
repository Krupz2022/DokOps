import { useEffect, useState } from "react";
import { Plus, Play, Pencil, Trash2, Workflow as WorkflowIcon, Link, Bot, History, ChevronUp, Hand, Clock, Webhook } from "lucide-react";
import type { Workflow } from "../types/workflow";
import { workflowApi } from "../lib/api";
import api from "../lib/api";
import { WorkflowBuilder } from "../components/workflows/WorkflowBuilder";
import { WorkflowExecutionView } from "../components/workflows/WorkflowExecutionView";
import { useToast } from "../context/ToastContext";
import { useAppContext } from "../context/AppContext";
import AgentsTab from "./AgentsTab";

type View = "list" | "builder" | "run";
type Tab = "scripted" | "agents";

interface WorkflowRun {
  id: number;
  status: string;
  triggered_by: string;
  started_at: string;
  completed_at: string | null;
  ai_summary: string | null;
}

const STATUS_PILL: Record<string, string> = {
  completed: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/30",
  failed:    "bg-destructive/10 text-destructive border border-destructive/30",
  running:   "bg-sky-500/10 text-sky-600 dark:text-sky-400 border border-sky-500/30 animate-pulse",
  pending:   "bg-muted text-muted-foreground border border-border",
};

const TRIGGER_ICON: Record<string, React.ReactNode> = {
  manual:  <Hand className="w-3 h-3" />,
  cron:    <Clock className="w-3 h-3" />,
  webhook: <Webhook className="w-3 h-3" />,
  alert:   <Webhook className="w-3 h-3" />,
};

const TRIGGER_PILL: Record<string, string> = {
  manual:  "bg-muted text-muted-foreground",
  webhook: "bg-sky-500/10 text-sky-500 border border-sky-500/30",
  cron:    "bg-amber-500/10 text-amber-500 border border-amber-500/30",
  all:     "bg-primary/10 text-primary border border-primary/30",
};

export default function Workflows() {
  const { toast } = useToast();
  const { godModeActive } = useAppContext();
  const [view, setView] = useState<View>("list");
  const [tab, setTab] = useState<Tab>("scripted");
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingWorkflow, setEditingWorkflow] = useState<Workflow | undefined>(undefined);
  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const [allRuns, setAllRuns] = useState<Record<number, WorkflowRun[]>>({});
  const [expandedHistory, setExpandedHistory] = useState<Record<number, boolean>>({});

  const fetchWorkflows = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await workflowApi.list();
      setWorkflows(res.data);
    } catch {
      setError("Failed to load workflows");
    } finally {
      setLoading(false);
    }
  };

  const fetchRuns = async (wfId: number) => {
    try {
      const res = await workflowApi.listRuns(wfId);
      const sorted = (res.data as WorkflowRun[]).sort(
        (a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime()
      );
      setAllRuns((prev) => ({ ...prev, [wfId]: sorted }));
    } catch { /* no runs yet */ }
  };

  useEffect(() => { fetchWorkflows(); }, []);
  useEffect(() => {
    workflows.filter((wf) => wf.workflow_type !== "agent").forEach((wf) => fetchRuns(wf.id));
  }, [workflows]);

  const handleNew = () => {
    setEditingWorkflow(undefined);
    setView("builder");
  };

  const handleEdit = (wf: Workflow) => {
    setEditingWorkflow(wf);
    setView("builder");
  };

  const handleRun = async (wf: Workflow) => {
    try {
      const res = await workflowApi.run(wf.id, {});
      setActiveRunId(res.data.run_id);
      setView("run");
    } catch {
      toast("Failed to start workflow run", "error");
    }
  };

  const handleDelete = async (wf: Workflow) => {
    if (!godModeActive) {
      toast("God Mode required to delete workflows", "error");
      return;
    }
    try {
      await api.delete(`/workflows/${wf.id}`);
      toast("Workflow deleted", "success");
      fetchWorkflows();
    } catch {
      toast("Failed to delete workflow", "error");
    }
  };

  const handleSave = (_id: number) => {
    setView("list");
    fetchWorkflows();
  };

  const handleCancel = () => {
    setView("list");
  };

  const handleBack = () => {
    setView("list");
    setActiveRunId(null);
  };

  // --- Run view ---
  if (view === "run" && activeRunId !== null) {
    return (
      <div className="p-6 h-full">
        <WorkflowExecutionView runId={activeRunId} onBack={handleBack} />
      </div>
    );
  }

  // --- Builder view ---
  if (view === "builder") {
    return (
      <div className="p-6 h-full flex flex-col">
        <div className="mb-4 flex items-center justify-between flex-shrink-0">
          <h1 className="text-foreground text-xl font-semibold">
            {editingWorkflow ? "Edit Workflow" : "New Workflow"}
          </h1>
        </div>
        <div className="flex-1 min-h-0">
          <WorkflowBuilder
            workflow={editingWorkflow}
            onSave={handleSave}
            onCancel={handleCancel}
          />
        </div>
      </div>
    );
  }

  // --- Agents tab ---
  if (tab === "agents") {
    return (
      <div className="p-6 h-full flex flex-col gap-4">
        <div className="flex-shrink-0">
          <div className="flex rounded-lg border border-border overflow-hidden w-fit">
            <button
              onClick={() => setTab("scripted")}
              className="px-4 py-2 text-sm font-medium transition-colors text-muted-foreground hover:text-foreground hover:bg-muted/50"
            >
              Scripted Workflows
            </button>
            <button
              onClick={() => setTab("agents")}
              className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium transition-colors border-l border-white/10 bg-primary/20 text-primary"
            >
              <Bot className="w-4 h-4" />
              Agents
            </button>
          </div>
        </div>
        <div className="flex-1 min-h-0">
          <AgentsTab />
        </div>
      </div>
    );
  }

  // --- List view ---
  return (
    <div className="p-6 space-y-5">
      {/* Tab switcher */}
      <div className="flex rounded-lg border border-border overflow-hidden w-fit">
        <button
          onClick={() => setTab("scripted")}
          className="px-4 py-2 text-sm font-medium transition-colors bg-primary/20 text-primary"
        >
          Scripted Workflows
        </button>
        <button
          onClick={() => setTab("agents")}
          className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium transition-colors border-l border-white/10 text-muted-foreground hover:text-foreground hover:bg-muted/50"
        >
          <Bot className="w-4 h-4" />
          Agents
        </button>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-foreground text-xl font-semibold">Workflows</h1>
          <p className="text-muted-foreground text-sm mt-0.5">
            Automate multi-step DevOps actions with triggers and connectors.
          </p>
        </div>
        <button
          onClick={handleNew}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary hover:bg-primary/90 text-primary-foreground text-sm font-medium transition-colors"
        >
          <Plus size={16} />
          New Workflow
        </button>
      </div>

      {/* Loading */}
      {loading && (
        <div className="text-muted-foreground text-sm">Loading workflows…</div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="bg-destructive/10 border border-destructive/30 rounded-lg px-4 py-3 text-destructive text-sm">
          {error}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && workflows.filter((wf) => wf.workflow_type !== "agent").length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 space-y-4">
          <div className="w-14 h-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center">
            <WorkflowIcon className="w-7 h-7 text-primary" />
          </div>
          <div className="text-foreground text-sm font-medium">No workflows yet</div>
          <div className="text-muted-foreground text-xs text-center max-w-xs">
            Create your first workflow to automate multi-step tasks across your infrastructure.
          </div>
          <button
            onClick={handleNew}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary hover:bg-primary/90 text-primary-foreground text-sm font-medium transition-colors"
          >
            <Plus size={16} />
            Create First Workflow
          </button>
        </div>
      )}

      {/* Workflow cards */}
      {!loading && workflows.filter((wf) => wf.workflow_type !== "agent").length > 0 && (
        <div className="space-y-2">
          {workflows.filter((wf) => wf.workflow_type !== "agent").map((wf) => {
            const runs = allRuns[wf.id] ?? [];
            const lastRun = runs[0];
            const historyOpen = expandedHistory[wf.id] ?? false;

            return (
              <div key={wf.id} className="bg-card border border-border rounded-xl overflow-hidden">
                {/* Card header row */}
                <div className="px-5 py-4 flex items-center gap-4">
                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                      <span className="text-foreground text-sm font-medium">{wf.name}</span>
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium capitalize ${TRIGGER_PILL[wf.trigger_type] ?? TRIGGER_PILL.manual}`}>
                        {wf.trigger_type}
                      </span>
                      {lastRun && (
                        <span className={`px-2 py-0.5 rounded-full text-xs ${STATUS_PILL[lastRun.status] ?? STATUS_PILL.pending}`}>
                          {lastRun.status}
                        </span>
                      )}
                    </div>
                    {wf.description && (
                      <p className="text-muted-foreground text-xs truncate">{wf.description}</p>
                    )}
                    <div className="flex items-center gap-4 mt-1">
                      <span className="text-muted-foreground text-xs">
                        {wf.steps.length} step{wf.steps.length !== 1 ? "s" : ""}
                      </span>
                      <span className="text-muted-foreground text-xs">by {wf.created_by}</span>
                      {lastRun && (
                        <span className="text-muted-foreground text-xs">
                          Last run {new Date(lastRun.started_at).toLocaleString()}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-1 flex-shrink-0">
                    {(wf.trigger_type === "webhook" || wf.trigger_type === "all") && wf.webhook_token && (
                      <button
                        onClick={() => {
                          const url = `${import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1"}/workflows/webhook/${wf.webhook_token}`;
                          navigator.clipboard.writeText(url);
                          toast("Webhook URL copied", "success");
                        }}
                        title="Copy webhook URL"
                        className="p-2 rounded-lg text-muted-foreground hover:text-sky-500 hover:bg-sky-500/10 transition-colors"
                      >
                        <Link size={15} />
                      </button>
                    )}
                    <button onClick={() => handleRun(wf)} title="Run"
                      className="p-2 rounded-lg text-muted-foreground hover:text-emerald-600 hover:bg-emerald-500/10 transition-colors">
                      <Play size={15} />
                    </button>
                    {runs.length > 0 && (
                      <button
                        onClick={() => setExpandedHistory((prev) => ({ ...prev, [wf.id]: !historyOpen }))}
                        title="Run history"
                        className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                      >
                        {historyOpen ? <ChevronUp size={15} /> : <History size={15} />}
                      </button>
                    )}
                    <button onClick={() => handleEdit(wf)} title="Edit"
                      className="p-2 rounded-lg text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors">
                      <Pencil size={15} />
                    </button>
                    <button onClick={() => handleDelete(wf)} title="Delete"
                      className="p-2 rounded-lg text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors">
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>

                {/* Run history panel */}
                {historyOpen && runs.length > 0 && (
                  <div className="border-t border-border bg-muted/20">
                    <div className="px-5 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Run History
                    </div>
                    <div className="divide-y divide-border/50">
                      {runs.slice(0, 10).map((run) => (
                        <button
                          key={run.id}
                          onClick={() => { setActiveRunId(run.id); setView("run"); }}
                          className="w-full flex items-center gap-3 px-5 py-2.5 hover:bg-muted/40 transition-colors text-left"
                        >
                          <span className={`px-2 py-0.5 rounded-full text-xs flex-shrink-0 ${STATUS_PILL[run.status] ?? STATUS_PILL.pending}`}>
                            {run.status}
                          </span>
                          <span className="text-xs text-muted-foreground flex-shrink-0">Run #{run.id}</span>
                          <span className="flex items-center gap-1 text-xs text-muted-foreground/60 flex-shrink-0">
                            {TRIGGER_ICON[run.triggered_by] ?? TRIGGER_ICON.manual}
                            {run.triggered_by}
                          </span>
                          <span className="text-xs text-muted-foreground/60 flex-shrink-0">
                            {new Date(run.started_at).toLocaleString()}
                          </span>
                          {run.ai_summary && (
                            <span className="text-xs text-muted-foreground/50 truncate min-w-0">
                              — {run.ai_summary.slice(0, 80)}
                            </span>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
