import { useEffect, useState, useMemo } from "react";
import { Plus, X, Trash2, Clock, ToggleLeft, ToggleRight } from "lucide-react";
import api from "../lib/api";

interface Org { id: string; name: string; }
interface Stage { id: string; name: string; order: number; }
interface Pipeline { id: string; name: string; org_id: string; stages: Stage[]; }

interface Schedule {
  id: string;
  pipeline_id: string;
  stage_id: string;
  cron_expr: string;
  timezone: string;
  patch_scope: string;
  promote_from_previous: boolean;
  auto_reboot: boolean;
  enabled: boolean;
  next_run_at: string | null;
  week_of_month: number | null;
  notifications: ScheduleNotifications | null;
  ai_beautify: boolean;
}

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

interface ScheduleNotifications {
  slack: NotificationChannel;
  teams: NotificationChannel;
  jira: NotificationChannel;
}

const TIMEZONES = [
  "UTC", "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Madrid",
  "Europe/Rome", "Europe/Amsterdam", "Europe/Brussels", "Europe/Warsaw",
  "Europe/Prague", "Europe/Vienna", "Europe/Budapest", "Europe/Bucharest",
  "Europe/Athens", "Europe/Helsinki", "Europe/Istanbul", "Europe/Moscow",
  "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
  "America/Toronto", "America/Vancouver", "America/Sao_Paulo", "America/Mexico_City",
  "America/Buenos_Aires", "Asia/Dubai", "Asia/Kolkata", "Asia/Bangkok",
  "Asia/Singapore", "Asia/Tokyo", "Asia/Seoul", "Asia/Shanghai",
  "Australia/Sydney", "Australia/Melbourne", "Pacific/Auckland",
];

const DAYS_OF_WEEK = [
  { label: "Sun", value: 0 },
  { label: "Mon", value: 1 },
  { label: "Tue", value: 2 },
  { label: "Wed", value: 3 },
  { label: "Thu", value: 4 },
  { label: "Fri", value: 5 },
  { label: "Sat", value: 6 },
];

const WEEK_OPTIONS = [
  { label: "Every week", value: null },
  { label: "1st",        value: 1 },
  { label: "2nd",        value: 2 },
  { label: "3rd",        value: 3 },
  { label: "4th",        value: 4 },
];

const SCOPE_LABELS: Record<string, string> = {
  security: "Security only",
  all: "All updates",
  custom: "Custom packages",
};

const HOURS = Array.from({ length: 24 }, (_, i) => i);
const MINUTES = [0, 15, 30, 45];

/** Build a 5-field cron expression from parts. */
function buildCron(minute: number, hour: number, dow: number): string {
  return `${minute} ${hour} * * ${dow}`;
}

/** Generate human-readable schedule description. */
function describeSchedule(cron_expr: string, week_of_month: number | null, tz: string): string {
  const WEEK_LABELS: Record<number, string> = { 1: "1st", 2: "2nd", 3: "3rd", 4: "4th" };
  const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const parts = cron_expr.trim().split(/\s+/);
  if (parts.length === 5 && parts[2] === "*" && parts[3] === "*") {
    const min = parseInt(parts[0], 10);
    const hour = parseInt(parts[1], 10);
    const dow = parseInt(parts[4], 10);
    if (!isNaN(min) && !isNaN(hour) && !isNaN(dow) && dow >= 0 && dow <= 6) {
      const time = `${String(hour).padStart(2, "0")}:${String(min).padStart(2, "0")}`;
      const day = DAY_NAMES[dow];
      const prefix = week_of_month ? `Every ${WEEK_LABELS[week_of_month]} ${day}` : `Every ${day}`;
      return `${prefix} at ${time} (${tz})`;
    }
  }
  return `${cron_expr} (${tz})`;
}

export default function Schedules() {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);

  const [showCreate, setShowCreate] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [tzSearch, setTzSearch] = useState("");
  const [showTzDropdown, setShowTzDropdown] = useState(false);

  const [form, setForm] = useState({
    pipeline_id: "",
    stage_id: "",
    day_of_week: 1,
    week_of_month: null as number | null,
    hour: 2,
    minute: 0,
    timezone: "UTC",
    patch_scope: "security",
    custom_packages: "",
    promote_from_previous: false,
    auto_reboot: false,
  });

  const defaultNotifications: ScheduleNotifications = {
    slack: { enabled: false, webhook_url: "" },
    teams: { enabled: false, webhook_url: "" },
    jira:  { enabled: false, base_url: "", project_key: "", issue_type: "Task", email: "", api_token: "", instance_type: "cloud" },
  };

  const [notifications, setNotifications] = useState<ScheduleNotifications>(defaultNotifications);
  const [aiBeautify, setAiBeautify] = useState(false);

  async function loadAll() {
    const [schedsRes, orgsRes] = await Promise.all([
      api.get("/patches/schedules/"),
      api.get("/organisations/"),
    ]);
    setSchedules(schedsRes.data);
    const loadedOrgs: Org[] = orgsRes.data;
    const pipelineResults = await Promise.all(
      loadedOrgs.map(o => api.get(`/patches/organisations/${o.id}/pipelines`))
    );
    setPipelines(pipelineResults.flatMap(r => r.data));
  }

  useEffect(() => { loadAll(); }, []);

  const selectedPipeline = pipelines.find(p => p.id === form.pipeline_id);
  const stagesForPipeline = selectedPipeline?.stages ?? [];

  const filteredTzs = useMemo(
    () => TIMEZONES.filter(tz => tz.toLowerCase().includes(tzSearch.toLowerCase())),
    [tzSearch]
  );

  const cronPreview = useMemo(
    () => describeSchedule(buildCron(form.minute, form.hour, form.day_of_week), form.week_of_month, form.timezone),
    [form.day_of_week, form.week_of_month, form.hour, form.minute, form.timezone]
  );

  function resetForm() {
    setForm({
      pipeline_id: "", stage_id: "",
      day_of_week: 1, week_of_month: null,
      hour: 2, minute: 0,
      timezone: "UTC", patch_scope: "security",
      custom_packages: "", promote_from_previous: false, auto_reboot: false,
    });
    setNotifications(defaultNotifications);
    setAiBeautify(false);
  }

  async function createSchedule() {
    if (!form.pipeline_id || !form.stage_id) return;
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        pipeline_id: form.pipeline_id,
        stage_id: form.stage_id,
        cron_expr: buildCron(form.minute, form.hour, form.day_of_week),
        week_of_month: form.week_of_month,
        timezone: form.timezone,
        patch_scope: form.patch_scope,
        promote_from_previous: form.promote_from_previous,
        auto_reboot: form.auto_reboot,
        notifications,
        ai_beautify: aiBeautify,
      };
      if (form.patch_scope === "custom" && form.custom_packages.trim()) {
        payload.custom_packages = form.custom_packages.split(",").map(s => s.trim()).filter(Boolean);
      }
      const r = await api.post("/patches/schedules/", payload);
      setSchedules(prev => [...prev, r.data]);
      setShowCreate(false);
      resetForm();
    } finally { setSaving(false); }
  }

  async function toggleSchedule(id: string) {
    const current = schedules.find(s => s.id === id);
    const r = await api.patch(`/patches/schedules/${id}`, { enabled: !current?.enabled });
    setSchedules(prev => prev.map(s => s.id === id ? r.data : s));
  }

  async function deleteSchedule(id: string) {
    setDeleting(id);
    try {
      await api.delete(`/patches/schedules/${id}`);
      setSchedules(prev => prev.filter(s => s.id !== id));
    } finally { setDeleting(null); }
  }

  function getPipelineName(id: string) { return pipelines.find(p => p.id === id)?.name ?? id; }
  function getStageName(pipelineId: string, stageId: string) {
    return pipelines.find(p => p.id === pipelineId)?.stages.find(s => s.id === stageId)?.name ?? stageId;
  }

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-8">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
            <Clock className="w-4 h-4 text-primary" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-foreground">Patch Schedules</h1>
            <p className="text-xs text-muted-foreground mt-0.5">Automated maintenance windows</p>
          </div>
        </div>
        <button
          onClick={() => setShowCreate(v => !v)}
          className="flex items-center gap-1.5 px-3.5 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          New Schedule
        </button>
      </div>

      {showCreate && (
        <div className="bg-card border border-border rounded-xl p-5 mb-6 shadow-sm space-y-5">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-foreground">Create Schedule</p>
            <button onClick={() => { setShowCreate(false); resetForm(); }} className="text-muted-foreground hover:text-foreground">
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Pipeline + Stage */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Pipeline</label>
              <select
                value={form.pipeline_id}
                onChange={e => setForm(p => ({ ...p, pipeline_id: e.target.value, stage_id: "" }))}
                className="w-full bg-muted border border-border rounded-lg px-3 py-2 text-sm text-foreground"
              >
                <option value="">Select pipeline…</option>
                {pipelines.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Stage</label>
              <select
                value={form.stage_id}
                onChange={e => setForm(p => ({ ...p, stage_id: e.target.value }))}
                disabled={!form.pipeline_id}
                className="w-full bg-muted border border-border rounded-lg px-3 py-2 text-sm text-foreground disabled:opacity-50"
              >
                <option value="">Select stage…</option>
                {stagesForPipeline.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
          </div>

          {/* Day of week */}
          <div>
            <label className="text-xs text-muted-foreground mb-2 block">Day of week</label>
            <div className="flex gap-1.5 flex-wrap">
              {DAYS_OF_WEEK.map(d => (
                <button
                  key={d.value}
                  type="button"
                  onClick={() => setForm(p => ({ ...p, day_of_week: d.value }))}
                  className={`px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors ${
                    form.day_of_week === d.value
                      ? "bg-primary text-primary-foreground border-primary"
                      : "bg-muted border-border text-muted-foreground hover:text-foreground hover:border-primary/40"
                  }`}
                >
                  {d.label}
                </button>
              ))}
            </div>
          </div>

          {/* Week of month */}
          <div>
            <label className="text-xs text-muted-foreground mb-2 block">Week of month</label>
            <div className="flex gap-1.5 flex-wrap">
              {WEEK_OPTIONS.map(w => (
                <button
                  key={String(w.value)}
                  type="button"
                  onClick={() => setForm(p => ({ ...p, week_of_month: w.value }))}
                  className={`px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors ${
                    form.week_of_month === w.value
                      ? "bg-primary text-primary-foreground border-primary"
                      : "bg-muted border-border text-muted-foreground hover:text-foreground hover:border-primary/40"
                  }`}
                >
                  {w.label}
                </button>
              ))}
            </div>
          </div>

          {/* Time + Timezone */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground mb-2 block">Time</label>
              <div className="flex items-center gap-2">
                <select
                  value={form.hour}
                  onChange={e => setForm(p => ({ ...p, hour: parseInt(e.target.value, 10) }))}
                  className="flex-1 bg-muted border border-border rounded-lg px-3 py-2 text-sm text-foreground font-mono"
                >
                  {HOURS.map(h => (
                    <option key={h} value={h}>{String(h).padStart(2, "0")}</option>
                  ))}
                </select>
                <span className="text-muted-foreground text-sm font-mono">:</span>
                <select
                  value={form.minute}
                  onChange={e => setForm(p => ({ ...p, minute: parseInt(e.target.value, 10) }))}
                  className="flex-1 bg-muted border border-border rounded-lg px-3 py-2 text-sm text-foreground font-mono"
                >
                  {MINUTES.map(m => (
                    <option key={m} value={m}>{String(m).padStart(2, "0")}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="relative">
              <label className="text-xs text-muted-foreground mb-2 block">Timezone</label>
              <input
                value={tzSearch || form.timezone}
                onFocus={() => { setTzSearch(""); setShowTzDropdown(true); }}
                onChange={e => { setTzSearch(e.target.value); setShowTzDropdown(true); }}
                onBlur={() => setTimeout(() => setShowTzDropdown(false), 150)}
                className="w-full bg-muted border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
              />
              {showTzDropdown && filteredTzs.length > 0 && (
                <div className="absolute z-20 mt-1 w-full bg-card border border-border rounded-lg shadow-lg max-h-48 overflow-y-auto">
                  {filteredTzs.map(tz => (
                    <button
                      key={tz}
                      onMouseDown={() => { setForm(p => ({ ...p, timezone: tz })); setTzSearch(""); setShowTzDropdown(false); }}
                      className="w-full text-left px-3 py-2 text-sm hover:bg-muted text-foreground"
                    >
                      {tz}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Preview */}
          <div className="px-3 py-2 rounded-lg bg-primary/5 border border-primary/20 text-sm text-primary">
            {cronPreview}
          </div>

          {/* Promote from previous */}
          <label className="flex items-center gap-3 cursor-pointer select-none">
            <div
              onClick={() => setForm(p => ({ ...p, promote_from_previous: !p.promote_from_previous }))}
              className={`w-8 h-4 rounded-full flex items-center px-0.5 transition-colors cursor-pointer ${form.promote_from_previous ? "bg-primary" : "bg-muted border border-border"}`}
            >
              <div className={`w-3 h-3 rounded-full bg-white shadow transition-transform ${form.promote_from_previous ? "translate-x-4" : "translate-x-0"}`} />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">Promote from previous stage</p>
              <p className="text-xs text-muted-foreground">
                {form.promote_from_previous
                  ? "Reads the frozen package list from the prior stage's latest successful run."
                  : "Resolves fresh available patches on this stage's devices."}
              </p>
            </div>
          </label>

          {/* Auto-reboot */}
          <label className="flex items-center gap-3 cursor-pointer select-none">
            <div
              onClick={() => setForm(p => ({ ...p, auto_reboot: !p.auto_reboot }))}
              className={`w-8 h-4 rounded-full flex items-center px-0.5 transition-colors cursor-pointer ${form.auto_reboot ? "bg-sky-500" : "bg-muted border border-border"}`}
            >
              <div className={`w-3 h-3 rounded-full bg-white shadow transition-transform ${form.auto_reboot ? "translate-x-4" : "translate-x-0"}`} />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">Reboot if needed</p>
              <p className="text-xs text-muted-foreground">
                {form.auto_reboot
                  ? "Devices requiring a reboot after patching will be restarted automatically."
                  : "Devices requiring a reboot will be flagged but not restarted."}
              </p>
            </div>
          </label>

          {/* Scope */}
          {!form.promote_from_previous && (
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Patch scope</label>
              <div className="flex gap-1 bg-muted rounded-lg p-0.5 w-fit">
                {["security", "all", "custom"].map(s => (
                  <button
                    key={s}
                    onClick={() => setForm(p => ({ ...p, patch_scope: s }))}
                    className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${form.patch_scope === s ? "bg-background text-foreground shadow-sm border border-border/60" : "text-muted-foreground hover:text-foreground"}`}
                  >
                    {SCOPE_LABELS[s]}
                  </button>
                ))}
              </div>
              {form.patch_scope === "custom" && (
                <input
                  value={form.custom_packages}
                  onChange={e => setForm(p => ({ ...p, custom_packages: e.target.value }))}
                  placeholder="nginx, openssl, curl  (comma-separated)"
                  className="mt-2 w-full bg-muted border border-border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary"
                />
              )}
            </div>
          )}

          {/* Notifications */}
          <div className="space-y-4 pt-1 border-t border-border">
            <p className="text-xs font-semibold text-foreground pt-1">Notifications</p>

            {/* AI Beautify toggle */}
            <label className="flex items-center gap-3 cursor-pointer select-none">
              <div
                onClick={() => setAiBeautify(v => !v)}
                className={`w-8 h-4 rounded-full flex items-center px-0.5 transition-colors cursor-pointer ${aiBeautify ? "bg-violet-500" : "bg-muted border border-border"}`}
              >
                <div className={`w-3 h-3 rounded-full bg-white shadow transition-transform ${aiBeautify ? "translate-x-4" : "translate-x-0"}`} />
              </div>
              <div>
                <p className="text-sm font-medium text-foreground">Beautify with AI</p>
                <p className="text-xs text-muted-foreground">
                  Passes the raw patch summary through AI to generate a clean, human-readable ops report before sending.
                </p>
              </div>
            </label>

            {/* Slack */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-foreground">Slack</span>
                <button
                  type="button"
                  onClick={() => setNotifications(n => ({ ...n, slack: { ...n.slack, enabled: !n.slack.enabled } }))}
                  className={`w-9 h-5 rounded-full transition-colors relative ${notifications.slack.enabled ? "bg-emerald-500" : "bg-muted border border-border"}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${notifications.slack.enabled ? "translate-x-4" : ""}`} />
                </button>
              </div>
              {notifications.slack.enabled && (
                <input
                  value={notifications.slack.webhook_url ?? ""}
                  onChange={e => setNotifications(n => ({ ...n, slack: { ...n.slack, webhook_url: e.target.value } }))}
                  placeholder="https://hooks.slack.com/services/…"
                  className="w-full rounded-lg border border-border bg-muted px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/50"
                />
              )}
            </div>

            {/* Teams */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-foreground">Microsoft Teams</span>
                <button
                  type="button"
                  onClick={() => setNotifications(n => ({ ...n, teams: { ...n.teams, enabled: !n.teams.enabled } }))}
                  className={`w-9 h-5 rounded-full transition-colors relative ${notifications.teams.enabled ? "bg-emerald-500" : "bg-muted border border-border"}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${notifications.teams.enabled ? "translate-x-4" : ""}`} />
                </button>
              </div>
              {notifications.teams.enabled && (
                <input
                  value={notifications.teams.webhook_url ?? ""}
                  onChange={e => setNotifications(n => ({ ...n, teams: { ...n.teams, webhook_url: e.target.value } }))}
                  placeholder="https://outlook.office.com/webhook/…"
                  className="w-full rounded-lg border border-border bg-muted px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/50"
                />
              )}
            </div>

            {/* Jira */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-foreground">Jira (create issue)</span>
                <button
                  type="button"
                  onClick={() => setNotifications(n => ({ ...n, jira: { ...n.jira, enabled: !n.jira.enabled } }))}
                  className={`w-9 h-5 rounded-full transition-colors relative ${notifications.jira.enabled ? "bg-emerald-500" : "bg-muted border border-border"}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${notifications.jira.enabled ? "translate-x-4" : ""}`} />
                </button>
              </div>
              {notifications.jira.enabled && (
                <div className="space-y-2">
                  {(
                    [
                      { label: "Base URL",     key: "base_url",     placeholder: "https://yourorg.atlassian.net" },
                      { label: "Project Key",  key: "project_key",  placeholder: "OPS" },
                      { label: "Issue Type",   key: "issue_type",   placeholder: "Task" },
                      { label: "Email",        key: "email",        placeholder: "ops@yourorg.com" },
                    ] as { label: string; key: keyof NotificationChannel; placeholder: string }[]
                  ).map(({ label, key, placeholder }) => (
                    <div key={key}>
                      <label className="block text-xs text-muted-foreground mb-1">{label}</label>
                      <input
                        value={(notifications.jira as unknown as Record<string, string>)[key] ?? ""}
                        onChange={e => setNotifications(n => ({ ...n, jira: { ...n.jira, [key]: e.target.value } }))}
                        placeholder={placeholder}
                        className="w-full rounded-lg border border-border bg-muted px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/50"
                      />
                    </div>
                  ))}
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">API Token</label>
                    <input
                      type="password"
                      value={notifications.jira.api_token ?? ""}
                      onChange={e => setNotifications(n => ({ ...n, jira: { ...n.jira, api_token: e.target.value } }))}
                      placeholder="••••••••••••"
                      className="w-full rounded-lg border border-border bg-muted px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/50"
                    />
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="flex gap-2 justify-end pt-1">
            <button onClick={() => { setShowCreate(false); resetForm(); }} className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground">Cancel</button>
            <button
              onClick={createSchedule}
              disabled={saving || !form.pipeline_id || !form.stage_id}
              className="px-4 py-1.5 bg-primary text-primary-foreground rounded-lg text-sm font-medium disabled:opacity-40 hover:bg-primary/90 transition-colors"
            >
              {saving ? "Saving…" : "Create Schedule"}
            </button>
          </div>
        </div>
      )}

      {schedules.length === 0 ? (
        <div className="border border-dashed border-border rounded-xl p-14 text-center">
          <Clock className="w-8 h-8 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-sm font-medium text-foreground mb-1">No schedules</p>
          <p className="text-xs text-muted-foreground">Create a schedule to automate patch maintenance windows.</p>
        </div>
      ) : (
        <div className="rounded-xl border border-border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr className="text-muted-foreground text-xs uppercase">
                <th className="px-4 py-3 text-left">Pipeline / Stage</th>
                <th className="px-4 py-3 text-left">Schedule</th>
                <th className="px-4 py-3 text-left">Scope</th>
                <th className="px-4 py-3 text-left">Next run</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {schedules.map(s => (
                <tr key={s.id} className="border-t border-border hover:bg-muted/30 transition-colors">
                  <td className="px-4 py-3">
                    <div className="font-medium text-foreground">{getPipelineName(s.pipeline_id)}</div>
                    <div className="text-xs text-muted-foreground">{getStageName(s.pipeline_id, s.stage_id)}</div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-foreground">{describeSchedule(s.cron_expr, s.week_of_month, s.timezone)}</div>
                    <div className="flex items-center gap-1 mt-0.5 flex-wrap">
                      {s.promote_from_previous && (
                        <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 bg-amber-500/10 border border-amber-500/20 rounded text-amber-500">
                          promotes from previous
                        </span>
                      )}
                      {s.auto_reboot && (
                        <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 bg-sky-500/10 border border-sky-500/20 rounded text-sky-400">
                          auto-reboot
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground text-xs">
                    {s.promote_from_previous ? <span className="italic">inherited</span> : (SCOPE_LABELS[s.patch_scope] ?? s.patch_scope)}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground text-xs">
                    {s.next_run_at ? new Date(s.next_run_at).toLocaleString() : <span className="italic">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2 justify-end">
                      <button
                        onClick={() => toggleSchedule(s.id)}
                        title={s.enabled ? "Disable" : "Enable"}
                        className="text-muted-foreground hover:text-foreground transition-colors"
                      >
                        {s.enabled ? <ToggleRight className="w-5 h-5 text-primary" /> : <ToggleLeft className="w-5 h-5" />}
                      </button>
                      <button
                        onClick={() => deleteSchedule(s.id)}
                        disabled={deleting === s.id}
                        className="p-1 text-muted-foreground/40 hover:text-red-400 transition-colors disabled:opacity-40"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
