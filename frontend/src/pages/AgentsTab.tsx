import { useEffect, useState, type ReactElement } from "react";
import { Plus, Play, Pencil, Trash2, Bot, Clock, Webhook, Hand, ChevronUp, History } from "lucide-react";
import api from "../lib/api";
import { useToast } from "../context/ToastContext";
import { useAppContext } from "../context/AppContext";
import CreateAgentDrawer from "../components/agents/CreateAgentDrawer";
import AgentRunPanel from "../components/agents/AgentRunPanel";

interface AgentTool {
  name: string;
  description: string;
  is_destructive: boolean;
  pre_approved: boolean;
}

interface Agent {
  id: number;
  name: string;
  description: string;
  workflow_type: "agent";
  agent_goal: string;
  agent_approved_tools: AgentTool[];
  agent_cluster_ids: string[];
  agent_minion_ids: string[];
  agent_max_retries: number;
  agent_timeout_seconds: number;
  agent_approval_timeout_seconds: number;
  trigger_type: string;
  cron_schedule: string | null;
  webhook_token: string;
}

interface AgentRun {
  id: number;
  status: string;
  triggered_by: string;
  started_at: string;
  completed_at: string | null;
  ai_summary: string | null;
}

const TRIGGER_ICON: Record<string, ReactElement> = {
  manual: <Hand className="w-3.5 h-3.5" />,
  cron: <Clock className="w-3.5 h-3.5" />,
  webhook: <Webhook className="w-3.5 h-3.5" />,
};

const STATUS_PILL: Record<string, string> = {
  completed:         "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/30",
  failed:            "bg-destructive/10 text-destructive border border-destructive/30",
  running:           "bg-sky-500/10 text-sky-600 dark:text-sky-400 border border-sky-500/30 animate-pulse",
  awaiting_approval: "bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/30",
  pending:           "bg-muted text-muted-foreground border border-border",
};

export default function AgentsTab() {
  const { toast } = useToast();
  const { godModeActive } = useAppContext();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingAgent, setEditingAgent] = useState<Agent | undefined>(undefined);
  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const [activeAgentId, setActiveAgentId] = useState<number | null>(null);
  const [allRuns, setAllRuns] = useState<Record<number, AgentRun[]>>({});
  const [expandedHistory, setExpandedHistory] = useState<Record<number, boolean>>({});

  const fetchAgents = async () => {
    setLoading(true);
    try {
      const res = await api.get("/workflows");
      const all = res.data as Agent[];
      setAgents(all.filter((w) => w.workflow_type === "agent"));
    } catch {
      toast("Failed to load agents", "error");
    } finally {
      setLoading(false);
    }
  };

  const fetchRuns = async (agentId: number) => {
    try {
      const res = await api.get(`/workflows/${agentId}/runs`);
      const runs: AgentRun[] = res.data;
      const sorted = runs.sort(
        (a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime()
      );
      setAllRuns((prev) => ({ ...prev, [agentId]: sorted }));
    } catch {
      // no runs yet
    }
  };

  useEffect(() => { fetchAgents(); }, []);
  useEffect(() => { agents.forEach((a) => fetchRuns(a.id)); }, [agents]);

  const handleRun = async (agent: Agent) => {
    try {
      const res = await api.post(`/workflows/${agent.id}/run`, {});
      setActiveRunId(res.data.run_id);
      setActiveAgentId(agent.id);
    } catch {
      toast("Failed to start agent run", "error");
    }
  };

  const handleDelete = async (agent: Agent) => {
    if (!godModeActive) { toast("God Mode required to delete agents", "error"); return; }
    try {
      await api.delete(`/workflows/${agent.id}`, { headers: { "X-Mode": "GOD" } });
      toast("Agent deleted", "success");
      fetchAgents();
    } catch {
      toast("Failed to delete agent", "error");
    }
  };

  if (activeRunId && activeAgentId) {
    return (
      <AgentRunPanel
        runId={activeRunId}
        workflowId={activeAgentId}
        onBack={() => { setActiveRunId(null); setActiveAgentId(null); fetchAgents(); }}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4 flex-1 min-h-0">
      <div className="flex items-center justify-between flex-shrink-0">
        <div>
          <h2 className="text-foreground font-semibold">Agents</h2>
          <p className="text-muted-foreground text-sm mt-0.5">
            Autonomous AI agents that run goals against your clusters
          </p>
        </div>
        <button
          onClick={() => { setEditingAgent(undefined); setDrawerOpen(true); }}
          className="flex items-center gap-2 px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Agent
        </button>
      </div>

      {loading ? (
        <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
          Loading agents...
        </div>
      ) : agents.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground">
          <Bot className="w-10 h-10 opacity-30" />
          <p className="text-sm">No agents yet. Create one to get started.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3 overflow-y-auto">
          {agents.map((agent) => {
            const runs = allRuns[agent.id] ?? [];
            const lastRun = runs[0];
            const historyOpen = expandedHistory[agent.id] ?? false;

            return (
              <div key={agent.id} className="rounded-xl border border-border bg-card overflow-hidden">
                {/* Agent header row */}
                <div className="p-4 flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Bot className="w-4 h-4 text-primary flex-shrink-0" />
                      <span className="font-medium text-foreground text-sm truncate">{agent.name}</span>
                      <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border border-border bg-muted text-muted-foreground">
                        {TRIGGER_ICON[agent.trigger_type] ?? TRIGGER_ICON.manual}
                        {agent.trigger_type}
                      </span>
                      {lastRun && (
                        <span className={`px-2 py-0.5 rounded-full text-xs ${STATUS_PILL[lastRun.status] ?? STATUS_PILL.pending}`}>
                          {lastRun.status}
                        </span>
                      )}
                    </div>
                    <p className="text-muted-foreground text-xs mt-1.5 line-clamp-2">{agent.agent_goal}</p>
                    <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
                      <span>{agent.agent_approved_tools.length} tools</span>
                      {agent.agent_cluster_ids.length > 0 && (
                        <span>{agent.agent_cluster_ids.length} cluster{agent.agent_cluster_ids.length > 1 ? "s" : ""}</span>
                      )}
                      {lastRun && (
                        <span>Last run {new Date(lastRun.started_at).toLocaleString()}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <button
                      onClick={() => handleRun(agent)}
                      className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-muted-foreground hover:text-emerald-600 dark:hover:text-emerald-400 transition-colors"
                      title="Run now"
                    >
                      <Play className="w-4 h-4" />
                    </button>
                    {runs.length > 0 && (
                      <button
                        onClick={() => setExpandedHistory((prev) => ({ ...prev, [agent.id]: !historyOpen }))}
                        className="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                        title="Run history"
                      >
                        {historyOpen ? <ChevronUp className="w-4 h-4" /> : <History className="w-4 h-4" />}
                      </button>
                    )}
                    <button
                      onClick={() => { setEditingAgent(agent); setDrawerOpen(true); }}
                      className="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                      title="Edit"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(agent)}
                      className="p-1.5 rounded-lg hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
                      title="Delete"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Run history panel */}
                {historyOpen && runs.length > 0 && (
                  <div className="border-t border-border bg-muted/20">
                    <div className="px-4 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Run History
                    </div>
                    <div className="divide-y divide-border/50">
                      {runs.slice(0, 10).map((run) => (
                        <button
                          key={run.id}
                          onClick={() => { setActiveRunId(run.id); setActiveAgentId(agent.id); }}
                          className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted/40 transition-colors text-left"
                        >
                          <span className={`px-2 py-0.5 rounded-full text-xs flex-shrink-0 ${STATUS_PILL[run.status] ?? STATUS_PILL.pending}`}>
                            {run.status}
                          </span>
                          <span className="text-xs text-muted-foreground flex-shrink-0">
                            Run #{run.id}
                          </span>
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

      {drawerOpen && (
        <CreateAgentDrawer
          agent={editingAgent}
          onClose={() => setDrawerOpen(false)}
          onSaved={() => { setDrawerOpen(false); fetchAgents(); }}
        />
      )}
    </div>
  );
}
