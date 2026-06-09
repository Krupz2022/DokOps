import { useState, useEffect } from "react";
import { X, Sparkles, Loader2, AlertTriangle, Check, Shield } from "lucide-react";
import api from "../../lib/api";
import { useToast } from "../../context/ToastContext";
import { useAppContext } from "../../context/AppContext";

interface AgentTool {
  name: string;
  description: string;
  is_destructive: boolean;
  pre_approved: boolean;
}

interface Cluster { id: string; name: string; }
interface Minion { id: string; hostname: string; status: string; }

interface NotificationChannel {
  enabled: boolean;
  webhook_url?: string;
  base_url?: string;
  project_key?: string;
  issue_type?: string;
  email?: string;
  api_token?: string;
  instance_type?: string;
}

interface AgentNotifications {
  slack: NotificationChannel;
  teams: NotificationChannel;
  jira: NotificationChannel;
}

interface Agent {
  id?: number;
  name: string;
  description: string;
  agent_goal: string;
  agent_approved_tools: AgentTool[];
  agent_cluster_ids: string[];
  agent_minion_ids: string[];
  agent_max_retries: number;
  agent_timeout_seconds: number;
  agent_approval_timeout_seconds: number;
  trigger_type: string;
  cron_schedule: string | null;
  agent_notifications?: AgentNotifications;
}

interface Props {
  agent?: Agent;
  onClose: () => void;
  onSaved: () => void;
}

export default function CreateAgentDrawer({ agent, onClose, onSaved }: Props) {
  const { toast } = useToast();
  const { godModeActive } = useAppContext();
  const [name, setName] = useState(agent?.name ?? "");
  const [goal, setGoal] = useState(agent?.agent_goal ?? "");
  const [tools, setTools] = useState<AgentTool[]>(agent?.agent_approved_tools ?? []);
  const [clusterIds, setClusterIds] = useState<string[]>(agent?.agent_cluster_ids ?? []);
  const [minionIds, setMinionIds] = useState<string[]>(agent?.agent_minion_ids ?? []);
  const [triggerType, setTriggerType] = useState(agent?.trigger_type ?? "manual");
  const [cronSchedule, setCronSchedule] = useState(agent?.cron_schedule ?? "");
  const [maxRetries, setMaxRetries] = useState(agent?.agent_max_retries ?? 3);
  const [timeoutMins, setTimeoutMins] = useState(Math.round((agent?.agent_timeout_seconds ?? 900) / 60));
  const [approvalTimeoutMins, setApprovalTimeoutMins] = useState(Math.round((agent?.agent_approval_timeout_seconds ?? 600) / 60));
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [minions, setMinions] = useState<Minion[]>([]);
  const [notifications, setNotifications] = useState<AgentNotifications>(
    agent?.agent_notifications ?? {
      slack: { enabled: false, webhook_url: "" },
      teams: { enabled: false, webhook_url: "" },
      jira:  { enabled: false, base_url: "", project_key: "", issue_type: "Task", email: "", api_token: "", instance_type: "cloud" },
    }
  );
  const [discovering, setDiscovering] = useState(false);
  const [saving, setSaving] = useState(false);
  const [section, setSection] = useState<1 | 2 | 3 | 4 | 5 | 6>(1);

  useEffect(() => {
    api.get("/clusters/").then((r) => setClusters(r.data)).catch(() => {});
    api.get("/minions/").then((r) => {
      const all = r.data as Minion[];
      setMinions(all.filter((m) => m.status === "active"));
    }).catch(() => {});
  }, []);

  const handleDiscoverTools = async () => {
    if (!goal.trim()) { toast("Enter a goal first", "error"); return; }
    setDiscovering(true);
    try {
      const res = await api.post("/workflows/agents/discover-tools", { goal });
      setTools(res.data.tools as AgentTool[]);
      setSection(2);
    } catch {
      toast("Failed to analyse goal", "error");
    } finally {
      setDiscovering(false);
    }
  };

  const toggleTool = (toolName: string) => {
    setTools((prev) =>
      prev.some((t) => t.name === toolName)
        ? prev.filter((t) => t.name !== toolName)
        : prev
    );
  };

  const togglePreApproved = (toolName: string) => {
    setTools((prev) =>
      prev.map((t) => t.name === toolName ? { ...t, pre_approved: !t.pre_approved } : t)
    );
  };

  const toggleCluster = (id: string) => {
    setClusterIds((prev) => prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]);
  };

  const toggleMinion = (id: string) => {
    setMinionIds((prev) => prev.includes(id) ? prev.filter((m) => m !== id) : [...prev, id]);
  };

  const handleSave = async () => {
    if (!name.trim()) { toast("Name is required", "error"); return; }
    if (!goal.trim()) { toast("Goal is required", "error"); return; }
    setSaving(true);
    const payload = {
      name,
      description: "",
      workflow_type: "agent",
      agent_goal: goal,
      agent_approved_tools: tools,
      agent_cluster_ids: clusterIds,
      agent_minion_ids: minionIds,
      trigger_type: triggerType,
      cron_schedule: triggerType === "cron" ? cronSchedule : null,
      agent_max_retries: maxRetries,
      agent_timeout_seconds: timeoutMins * 60,
      agent_approval_timeout_seconds: approvalTimeoutMins * 60,
      agent_notifications: notifications,
    };
    try {
      if (agent?.id) {
        await api.put(`/workflows/${agent.id}`, payload);
      } else {
        await api.post("/workflows", payload);
      }
      toast(agent?.id ? "Agent updated" : "Agent created", "success");
      onSaved();
    } catch {
      toast("Failed to save agent", "error");
    } finally {
      setSaving(false);
    }
  };

  const SECTION_LABELS = ["Goal", "Tools", "Scope", "Trigger", "Safety", "Notify"];

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="w-full max-w-lg bg-background border-l border-white/10 flex flex-col h-full shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 flex-shrink-0">
          <h2 className="font-semibold text-foreground">
            {agent?.id ? "Edit Agent" : "New Agent"}
          </h2>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/10 text-muted-foreground hover:text-foreground transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Section tabs */}
        <div className="flex border-b border-white/10 flex-shrink-0 overflow-x-auto">
          {SECTION_LABELS.map((label, i) => (
            <button
              key={label}
              onClick={() => setSection((i + 1) as 1 | 2 | 3 | 4 | 5 | 6)}
              className={`px-4 py-2.5 text-xs font-medium whitespace-nowrap transition-colors ${
                section === i + 1
                  ? "border-b-2 border-primary text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">

          {/* Section 1: Goal */}
          {section === 1 && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1.5">Agent Name</label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Payment Pod Watchdog"
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/50"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1.5">Goal (natural language)</label>
                <textarea
                  value={goal}
                  onChange={(e) => setGoal(e.target.value)}
                  rows={5}
                  placeholder="e.g. Check the payment pod for CrashLoopBackOff. If found, restart it and monitor for 2 minutes. If recovered post success to Teams, otherwise post full error analysis."
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/50 resize-none"
                />
              </div>
              <button
                onClick={handleDiscoverTools}
                disabled={discovering || !goal.trim()}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {discovering ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                {discovering ? "Analysing..." : "Analyse Goal"}
              </button>
            </div>
          )}

          {/* Section 2: Tools */}
          {section === 2 && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                Review the tools this agent will use. Untick any you don't want. Pre-approve destructive tools to skip the runtime confirmation prompt.
              </p>
              {tools.length === 0 ? (
                <p className="text-sm text-muted-foreground py-4 text-center">
                  Go to Goal tab and click "Analyse Goal" to discover tools.
                </p>
              ) : (
                tools.map((tool) => (
                  <div
                    key={tool.name}
                    className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/5 px-3 py-2.5"
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <input
                        type="checkbox"
                        checked={tools.some((t) => t.name === tool.name)}
                        onChange={() => toggleTool(tool.name)}
                        className="rounded accent-primary"
                      />
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-sm font-medium text-foreground">{tool.name}</span>
                          {tool.is_destructive && (
                            <span className="flex items-center gap-1 text-xs text-amber-400">
                              <AlertTriangle className="w-3 h-3" />
                              Destructive
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground truncate">{tool.description}</p>
                      </div>
                    </div>
                    {tool.is_destructive && (
                      <button
                        onClick={() => godModeActive && togglePreApproved(tool.name)}
                        disabled={!godModeActive}
                        title={!godModeActive ? "Enable God Mode to pre-approve destructive tools" : tool.pre_approved ? "Pre-approved (no runtime prompt)" : "Will pause for approval at runtime"}
                        className={`flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-colors flex-shrink-0 ${
                          !godModeActive
                            ? "opacity-40 cursor-not-allowed bg-white/5 text-muted-foreground border border-white/10"
                            : tool.pre_approved
                            ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                            : "bg-white/5 text-muted-foreground border border-white/10 hover:border-amber-500/30"
                        }`}
                      >
                        {tool.pre_approved ? <Check className="w-3 h-3" /> : <Shield className="w-3 h-3" />}
                        {tool.pre_approved ? "Pre-approved" : "Approve at runtime"}
                      </button>
                    )}
                  </div>
                ))
              )}
            </div>
          )}

          {/* Section 3: Scope */}
          {section === 3 && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-2">Target Clusters</label>
                {clusters.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No clusters connected.</p>
                ) : (
                  <div className="space-y-1.5">
                    {clusters.map((c) => (
                      <label key={c.id} className="flex items-center gap-2.5 rounded-lg border border-white/10 bg-white/5 px-3 py-2 cursor-pointer hover:bg-white/[0.08] transition-colors">
                        <input
                          type="checkbox"
                          checked={clusterIds.includes(c.id)}
                          onChange={() => toggleCluster(c.id)}
                          className="rounded accent-primary"
                        />
                        <span className="text-sm text-foreground">{c.name}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-2">Target Minions (active only)</label>
                {minions.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No active minions.</p>
                ) : (
                  <div className="space-y-1.5">
                    {minions.map((m) => (
                      <label key={m.id} className="flex items-center gap-2.5 rounded-lg border border-white/10 bg-white/5 px-3 py-2 cursor-pointer hover:bg-white/[0.08] transition-colors">
                        <input
                          type="checkbox"
                          checked={minionIds.includes(m.id)}
                          onChange={() => toggleMinion(m.id)}
                          className="rounded accent-primary"
                        />
                        <span className="text-sm text-foreground">{m.hostname}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Section 4: Trigger */}
          {section === 4 && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-2">Trigger Type</label>
                <div className="flex gap-2">
                  {(["manual", "cron", "webhook"] as const).map((t) => (
                    <button
                      key={t}
                      onClick={() => setTriggerType(t)}
                      className={`px-3 py-2 rounded-lg text-sm font-medium capitalize transition-colors ${
                        triggerType === t
                          ? "bg-primary/20 text-primary border border-primary/30"
                          : "bg-white/5 text-muted-foreground border border-white/10 hover:bg-white/10"
                      }`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>
              {triggerType === "cron" && (
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1.5">Cron Expression</label>
                  <input
                    value={cronSchedule}
                    onChange={(e) => setCronSchedule(e.target.value)}
                    placeholder="*/15 * * * *"
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/50 font-mono"
                  />
                  <p className="text-xs text-muted-foreground mt-1">e.g. */15 * * * * = every 15 minutes</p>
                </div>
              )}
              {triggerType === "webhook" && agent?.id && (
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1.5">Webhook Token</label>
                  <p className="font-mono text-xs bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-foreground break-all">
                    POST /api/v1/workflows/webhook/{(agent as any).webhook_token}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Section 5: Safety */}
          {section === 5 && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1.5">Max Retries</label>
                <input
                  type="number"
                  min={1} max={10}
                  value={maxRetries}
                  onChange={(e) => setMaxRetries(Number(e.target.value))}
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-foreground focus:outline-none focus:border-primary/50"
                />
                <p className="text-xs text-muted-foreground mt-1">Loop stops after this many iterations and posts a failure report</p>
              </div>
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1.5">Timeout (minutes)</label>
                <input
                  type="number"
                  min={1} max={60}
                  value={timeoutMins}
                  onChange={(e) => setTimeoutMins(Number(e.target.value))}
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-foreground focus:outline-none focus:border-primary/50"
                />
                <p className="text-xs text-muted-foreground mt-1">Hard stop — whichever of retries/timeout hits first ends the run</p>
              </div>
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1.5">Approval Timeout (minutes)</label>
                <input
                  type="number"
                  min={1} max={30}
                  value={approvalTimeoutMins}
                  onChange={(e) => setApprovalTimeoutMins(Number(e.target.value))}
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-foreground focus:outline-none focus:border-primary/50"
                />
                <p className="text-xs text-muted-foreground mt-1">If no approval received within this time, destructive action is auto-skipped</p>
              </div>
            </div>
          )}

          {/* Section 6: Notifications */}
          {section === 6 && (
            <div className="space-y-5">
              <p className="text-xs text-muted-foreground">
                Configure where to send a summary when this agent finishes a run (manual, cron, or webhook).
              </p>

              {/* Slack */}
              <div className="rounded-lg border border-border bg-secondary/30 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-foreground">Slack</span>
                  <button
                    type="button"
                    onClick={() => setNotifications(n => ({ ...n, slack: { ...n.slack, enabled: !n.slack.enabled } }))}
                    className={`w-9 h-5 rounded-full transition-colors relative ${notifications.slack.enabled ? "bg-emerald-500" : "bg-muted"}`}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-background transition-transform ${notifications.slack.enabled ? "translate-x-4" : ""}`} />
                  </button>
                </div>
                {notifications.slack.enabled && (
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">Webhook URL</label>
                    <input
                      value={notifications.slack.webhook_url ?? ""}
                      onChange={(e) => setNotifications(n => ({ ...n, slack: { ...n.slack, webhook_url: e.target.value } }))}
                      placeholder="https://hooks.slack.com/services/..."
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/50"
                    />
                  </div>
                )}
              </div>

              {/* Teams */}
              <div className="rounded-lg border border-border bg-secondary/30 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-foreground">Microsoft Teams</span>
                  <button
                    type="button"
                    onClick={() => setNotifications(n => ({ ...n, teams: { ...n.teams, enabled: !n.teams.enabled } }))}
                    className={`w-9 h-5 rounded-full transition-colors relative ${notifications.teams.enabled ? "bg-emerald-500" : "bg-muted"}`}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-background transition-transform ${notifications.teams.enabled ? "translate-x-4" : ""}`} />
                  </button>
                </div>
                {notifications.teams.enabled && (
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">Webhook URL</label>
                    <input
                      value={notifications.teams.webhook_url ?? ""}
                      onChange={(e) => setNotifications(n => ({ ...n, teams: { ...n.teams, webhook_url: e.target.value } }))}
                      placeholder="https://outlook.office.com/webhook/..."
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/50"
                    />
                  </div>
                )}
              </div>

              {/* Jira */}
              <div className="rounded-lg border border-border bg-secondary/30 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-foreground">Jira (create issue)</span>
                  <button
                    type="button"
                    onClick={() => setNotifications(n => ({ ...n, jira: { ...n.jira, enabled: !n.jira.enabled } }))}
                    className={`w-9 h-5 rounded-full transition-colors relative ${notifications.jira.enabled ? "bg-emerald-500" : "bg-muted"}`}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-background transition-transform ${notifications.jira.enabled ? "translate-x-4" : ""}`} />
                  </button>
                </div>
                {notifications.jira.enabled && (
                  <div className="space-y-2">
                    {[
                      { label: "Base URL", key: "base_url", placeholder: "https://yourorg.atlassian.net" },
                      { label: "Project Key", key: "project_key", placeholder: "OPS" },
                      { label: "Issue Type", key: "issue_type", placeholder: "Task" },
                      { label: "Email", key: "email", placeholder: "you@company.com" },
                    ].map(({ label, key, placeholder }) => (
                      <div key={key}>
                        <label className="block text-xs text-muted-foreground mb-1">{label}</label>
                        <input
                          value={(notifications.jira as unknown as Record<string, string>)[key] ?? ""}
                          onChange={(e) => setNotifications(n => ({ ...n, jira: { ...n.jira, [key]: e.target.value } }))}
                          placeholder={placeholder}
                          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/50"
                        />
                      </div>
                    ))}
                    <div>
                      <label className="block text-xs text-muted-foreground mb-1">API Token</label>
                      <input
                        type="password"
                        value={notifications.jira.api_token ?? ""}
                        onChange={(e) => setNotifications(n => ({ ...n, jira: { ...n.jira, api_token: e.target.value } }))}
                        placeholder="••••••••••••"
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/50"
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-white/10 flex justify-end gap-3 flex-shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            {agent?.id ? "Save Changes" : "Create Agent"}
          </button>
        </div>
      </div>
    </div>
  );
}
