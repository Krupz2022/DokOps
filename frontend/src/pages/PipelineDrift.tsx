import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, BarChart3, Eye, RefreshCw } from "lucide-react";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import cronstrue from "cronstrue";
import api from "../lib/api";
import { cn } from "../lib/utils";

export interface MissingAdvisory {
  key: string; advisory_id: string | null; package_name: string;
  severity: string; affected_minion_ids: string[];
}
export interface DeviceRow {
  minion_id: string; hostname: string; status: string;
  percent: number | null; matched: number;
  last_patched: string | null; missing_count: number;
}
export interface Stage {
  id: string; name: string; order: number;
  group_id: string; group_name: string | null;
  reference_stage_id: string | null; reference_stage_name: string | null;
  percent: number | null; ref_total: number; matched: number;
  devices_total: number; devices_covered: number | null;
  last_patched: string | null;
  schedule: { cron_expr: string; timezone: string; next_run_at: string | null } | null;
  missing: MissingAdvisory[];
  devices: DeviceRow[];
}
export interface DriftPayload {
  pipeline: { id: string; name: string; org_name: string | null };
  window: string;
  cadence: { week: string; advisories: number }[];
  stages: Stage[];
}

export const SEV: Record<string, string> = {
  critical: "bg-red-500/10 text-red-400 border-red-500/25",
  high:     "bg-orange-500/10 text-orange-400 border-orange-500/25",
  medium:   "bg-amber-500/10 text-amber-400 border-amber-500/25",
  low:      "bg-sky-500/10 text-sky-400 border-sky-500/25",
  none:     "bg-secondary text-muted-foreground border-border",
};

const WINDOWS = [
  { value: "latest", label: "latest run" },
  { value: "30d",    label: "last 30 days" },
  { value: "90d",    label: "last 90 days" },
  { value: "all",    label: "all time" },
];

/* Drift bands. Emerald only at 95+, because "nearly caught up" on a security
   advisory is not caught up. */
export function band(pct: number | null): { ring: string; text: string } {
  if (pct === null)  return { ring: "rgb(100 116 139)", text: "text-muted-foreground" };
  if (pct >= 95)     return { ring: "rgb(16 185 129)",  text: "text-emerald-400" };
  if (pct >= 70)     return { ring: "rgb(245 158 11)",  text: "text-amber-400" };
  return               { ring: "rgb(239 68 68)",   text: "text-red-400" };
}

export function ago(iso: string | null): string {
  if (!iso) return "never";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "1d ago";
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

function cron(s: Stage["schedule"]): string {
  if (!s) return "manual";
  try { return cronstrue.toString(s.cron_expr, { verbose: false }); }
  catch { return s.cron_expr; }
}

/* Drift ring — conic-gradient, no chart library. A recharts RadialBarChart for
   one number is ~40 lines of config for a worse result. */
function Ring({ pct }: { pct: number | null }) {
  const { ring, text } = band(pct);
  const deg = pct === null ? 0 : (pct / 100) * 360;
  return (
    <div
      className="w-20 h-20 rounded-full grid place-items-center transition-[background] duration-700"
      style={{ background: `conic-gradient(${ring} ${deg}deg, rgb(100 116 139 / 0.15) 0deg)` }}
    >
      <div className="w-[68px] h-[68px] rounded-full bg-card grid place-items-center">
        <span className={cn("text-lg font-bold tabular-nums", text)}>
          {pct === null ? "—" : `${pct}%`}
        </span>
      </div>
    </div>
  );
}

export default function PipelineDrift() {
  const { pipelineId } = useParams<{ pipelineId: string }>();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const window_ = params.get("window") ?? "latest";

  const [data, setData] = useState<DriftPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    api.get<DriftPayload>(`/patches/pipelines/${pipelineId}/drift`, { params: { window: window_ } })
      .then(r => {
        if (!live) return;
        setData(r.data);
        // Land on the first stage that is actually behind; baseline and
        // no-reference stages have nothing to show below.
        const behind = r.data.stages.find(s => s.percent !== null && s.percent < 100);
        setSelected(behind?.id ?? r.data.stages.at(-1)?.id ?? null);
      })
      .catch(() => live && setError("Could not load drift for this pipeline."))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [pipelineId, window_]);

  const stage = useMemo(
    () => data?.stages.find(s => s.id === selected) ?? null,
    [data, selected],
  );

  return (
    <div className="h-screen flex flex-col bg-background text-foreground">
      <header className="glass-header flex items-center gap-3 px-5 h-12 flex-shrink-0 border-b border-border">
        <button
          onClick={() => navigate("/patching/pipelines")}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="w-4 h-4" /> Pipelines
        </button>
        <span className="text-border select-none">/</span>
        <div className="flex items-center gap-2 min-w-0">
          <BarChart3 className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold truncate">{data?.pipeline.name ?? "…"}</span>
          {data?.pipeline.org_name && (
            <span className="text-sm text-muted-foreground font-mono truncate">· {data.pipeline.org_name}</span>
          )}
        </div>

        <select
          value={window_}
          onChange={e => setParams({ window: e.target.value })}
          className="ml-auto bg-background border border-border rounded-md px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        >
          {WINDOWS.map(w => <option key={w.value} value={w.value}>compare to: {w.label}</option>)}
        </select>
        <span className="flex items-center gap-1.5 text-[11px] font-semibold tracking-wide px-2.5 py-1 rounded-md border bg-primary/10 text-primary border-primary/30">
          <Eye className="w-3.5 h-3.5" /> READ-ONLY
        </span>
      </header>

      {loading && (
        <div className="flex-1 grid place-items-center text-muted-foreground text-sm">
          <span className="flex items-center gap-2"><RefreshCw className="w-4 h-4 animate-spin" /> Loading drift…</span>
        </div>
      )}

      {!loading && error && (
        <div className="flex-1 grid place-items-center">
          <div className="bg-card border border-border rounded-xl p-6 text-center">
            <p className="text-sm text-red-400 mb-3">{error}</p>
            <button
              onClick={() => setParams({ window: window_ })}
              className="px-3 py-1.5 bg-primary text-primary-foreground rounded-lg text-sm font-medium"
            >Retry</button>
          </div>
        </div>
      )}

      {!loading && !error && data && data.stages.length === 0 && (
        <div className="flex-1 grid place-items-center text-center">
          <div>
            <p className="text-sm text-muted-foreground mb-3">This pipeline has no stages yet.</p>
            <button
              onClick={() => navigate("/patching/pipelines")}
              className="px-3 py-1.5 bg-primary text-primary-foreground rounded-lg text-sm font-medium"
            >Add a stage</button>
          </div>
        </div>
      )}

      {!loading && !error && data && data.stages.length > 0 && (
        <div className="flex-1 overflow-y-auto">
          {/* ── Stage train ── */}
          <div className="flex items-start gap-2 px-6 py-6 overflow-x-auto">
            {data.stages.map((s, i) => (
              <div key={s.id} className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => setSelected(s.id)}
                  className={cn(
                    "w-40 rounded-xl border p-4 text-center transition-all bg-card dark:glass",
                    selected === s.id
                      ? "border-primary/50 dark:shadow-glow-sm"
                      : "border-border hover:border-primary/30",
                  )}
                >
                  <div className="grid place-items-center mb-3"><Ring pct={s.percent} /></div>
                  <p className="text-sm font-semibold truncate">{s.name}</p>
                  <p className="text-[11px] text-muted-foreground truncate">{s.group_name ?? "no group"}</p>
                  <p className="text-[11px] text-muted-foreground mt-2 tabular-nums">
                    {s.devices_covered === null
                      ? `${s.devices_total} dev`
                      : `${s.devices_covered}/${s.devices_total} dev`}
                  </p>
                  <p className="text-[11px] text-muted-foreground tabular-nums">{ago(s.last_patched)}</p>
                  <p className="text-[10px] text-muted-foreground/70 mt-1 truncate" title={cron(s.schedule)}>
                    {cron(s.schedule)}
                  </p>
                </button>
                {i < data.stages.length - 1 && (
                  <span className="text-muted-foreground/30 text-lg select-none">▶</span>
                )}
              </div>
            ))}

            {/* Cadence — the one genuine chart on the page. */}
            {data.cadence.length > 1 && (
              <div className="ml-auto shrink-0 w-56 pl-6">
                <p className="text-[10px] font-mono uppercase tracking-[0.16em] text-muted-foreground/70 mb-1">
                  advisories / week
                </p>
                <div className="h-16">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={data.cadence} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
                      <defs>
                        <linearGradient id="cadence" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="rgb(56 189 248)" stopOpacity={0.5} />
                          <stop offset="100%" stopColor="rgb(56 189 248)" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <Area
                        type="monotone" dataKey="advisories"
                        stroke="rgb(56 189 248)" strokeWidth={1.5}
                        fill="url(#cadence)" isAnimationActive={false}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </div>

          {/* Task 4 fills this in. */}
          {stage && <div className="px-6 pb-6" data-stage={stage.id} />}
        </div>
      )}
    </div>
  );
}
