import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, BarChart3, Eye, RefreshCw } from "lucide-react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import cronstrue from "cronstrue";
import api from "../lib/api";
import { cn } from "../lib/utils";

interface MissingAdvisory {
  key: string; advisory_id: string | null; package_name: string;
  severity: string; affected_minion_ids: string[];
}
interface DeviceRow {
  minion_id: string; hostname: string; status: string;
  percent: number | null; matched: number;
  last_patched: string | null; missing_count: number;
}
interface Stage {
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
interface DriftPayload {
  pipeline: { id: string; name: string; org_name: string | null };
  window: string;
  cadence: { week: string; advisories: number }[];
  stages: Stage[];
}

const SEV: Record<string, string> = {
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
function band(pct: number | null): { ring: string; text: string } {
  if (pct === null)  return { ring: "rgb(100 116 139)", text: "text-muted-foreground" };
  if (pct >= 95)     return { ring: "rgb(16 185 129)",  text: "text-emerald-400" };
  if (pct >= 70)     return { ring: "rgb(245 158 11)",  text: "text-amber-400" };
  return               { ring: "rgb(239 68 68)",   text: "text-red-400" };
}

function ago(iso: string | null): string {
  if (!iso) return "never";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "1d ago";
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

function cron(s: Stage["schedule"]): string {
  if (!s) return "manual";
  const tz = s.timezone && s.timezone !== "UTC" ? ` ${s.timezone}` : "";
  try { return cronstrue.toString(s.cron_expr, { verbose: false }) + tz; }
  catch { return s.cron_expr + tz; }
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
  const [nonce, setNonce] = useState(0);

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
  }, [pipelineId, window_, nonce]);

  const stage = useMemo(
    () => data?.stages.find(s => s.id === selected) ?? null,
    [data, selected],
  );

  const hostnames = useMemo(
    () => new Map(stage?.devices.map(d => [d.minion_id, d.hostname]) ?? []),
    [stage],
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
              onClick={() => setNonce(n => n + 1)}
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
            {data.cadence.some(c => c.advisories > 0) && (
              <div className="ml-auto shrink-0 w-56 pl-6">
                <p className="text-[10px] font-mono uppercase tracking-[0.16em] text-muted-foreground/70 mb-1">
                  advisories / week
                </p>
                <div className="h-16">
                  {/* Bars, not an area: weekly counts are discrete buckets, and
                      interpolating between them draws a ramp through values that
                      never existed. With a mostly-quiet pipeline that ramp is the
                      whole picture, so the mark type is the difference between
                      honest and misleading. */}
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data.cadence} margin={{ top: 2, right: 0, bottom: 0, left: 0 }} barCategoryGap={2}>
                      {/* Hidden, but it is what makes the tooltip say "2026-07-20"
                          instead of the array index. */}
                      <XAxis dataKey="week" hide />
                      <Tooltip
                        cursor={{ fill: "rgb(148 163 184 / 0.08)" }}
                        contentStyle={{
                          background: "rgb(2 6 23)", border: "1px solid rgb(51 65 85)",
                          borderRadius: 8, fontSize: 11, padding: "4px 8px",
                        }}
                        labelStyle={{ color: "rgb(148 163 184)" }}
                        itemStyle={{ color: "rgb(226 232 240)" }}
                      />
                      <Bar
                        dataKey="advisories" fill="rgb(56 189 248)"
                        radius={[2, 2, 0, 0]} isAnimationActive={false}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </div>

          {stage && (
            <div className="px-6 pb-6">
              <div className="flex flex-wrap items-baseline gap-2 mb-3">
                <span className="text-sm font-semibold">{stage.name}</span>
                <span className="text-xs text-muted-foreground">
                  {stage.reference_stage_name
                    ? `reference ${stage.reference_stage_name} · ${stage.missing.length} of ${stage.ref_total} advisories missing on at least one device`
                    : "baseline stage — nothing upstream to compare against"}
                </span>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Devices, worst first (server-sorted). */}
                <div className="bg-card border border-border rounded-xl dark:glass overflow-hidden">
                  <p className="text-[10px] font-mono font-semibold uppercase tracking-[0.16em] text-muted-foreground/70 px-4 py-2.5 border-b border-border">
                    Devices
                  </p>
                  {stage.devices.length === 0 ? (
                    <p className="text-xs text-muted-foreground px-4 py-6">
                      This stage's group has no devices.
                    </p>
                  ) : (
                    <div className="max-h-[46vh] overflow-y-auto">
                      <table className="w-full text-xs">
                        <tbody>
                          {stage.devices.map(d => (
                            <tr key={d.minion_id} className="border-b border-border/50 last:border-0">
                              <td className="px-4 py-2 font-medium truncate max-w-[180px]">{d.hostname}</td>
                              <td className={cn("px-2 py-2 tabular-nums font-semibold w-14 text-right", band(d.percent).text)}>
                                {d.percent === null ? "—" : `${d.percent}%`}
                              </td>
                              <td className="px-2 py-2 text-muted-foreground tabular-nums whitespace-nowrap">
                                {ago(d.last_patched)}
                              </td>
                              <td className="px-4 py-2 text-right whitespace-nowrap">
                                {d.missing_count === 0
                                  ? <span className="text-emerald-400">✓</span>
                                  : <span className="text-muted-foreground tabular-nums">{d.missing_count} missing</span>}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>

                {/* Missing advisories, severity-first (server-sorted). */}
                <div className="bg-card border border-border rounded-xl dark:glass overflow-hidden">
                  <p className="text-[10px] font-mono font-semibold uppercase tracking-[0.16em] text-muted-foreground/70 px-4 py-2.5 border-b border-border">
                    Missing advisories
                  </p>
                  {stage.missing.length === 0 ? (
                    <p className="text-xs text-muted-foreground px-4 py-6">
                      {stage.reference_stage_id === null
                        ? "Baseline stage — nothing upstream to compare against."
                        : stage.ref_total === 0
                        ? "No reference run to compare against yet."
                        : stage.devices_total === 0
                        ? "This stage's group has no devices."
                        : "Every device here carries everything the reference stage applied."}
                    </p>
                  ) : (
                    <div className="max-h-[46vh] overflow-y-auto divide-y divide-border/50">
                      {stage.missing.map(m => (
                        <div key={m.key} className="px-4 py-2.5">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className={cn("inline-flex items-center rounded-sm border px-1.5 py-0.5 font-mono text-[11px] font-medium", SEV[m.severity] ?? SEV.none)}>
                              {m.severity}
                            </span>
                            <span className="font-mono text-[11px] text-foreground/90">
                              {m.advisory_id ?? m.package_name}
                            </span>
                            {m.advisory_id && (
                              <span className="text-[11px] text-muted-foreground">{m.package_name}</span>
                            )}
                          </div>
                          <p className="text-[11px] text-muted-foreground mt-1 truncate"
                             title={m.affected_minion_ids.map(id => hostnames.get(id) ?? id).join(", ")}>
                            {m.affected_minion_ids.length} device{m.affected_minion_ids.length === 1 ? "" : "s"} behind
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
