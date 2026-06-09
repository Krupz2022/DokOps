import { useEffect, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { BarChart2, Users, Zap } from "lucide-react";
import api from "../lib/api";
import { cn } from "../lib/utils";

// ── Types ──────────────────────────────────────────────────────────────────────

interface TokenSummary {
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  total_calls: number;
  unique_users: number;
}

interface DailyPoint {
  date: string;
  tokens: number;
  calls: number;
}

interface BySource {
  source: string;
  tokens: number;
  calls: number;
  pct: number;
}

interface ByModel {
  model: string;
  tokens: number;
  calls: number;
  pct: number;
}

interface ByUser {
  user_id: number | null;
  username: string;
  tokens: number;
  calls: number;
}

interface AnalyticsData {
  summary: TokenSummary;
  daily: DailyPoint[];
  by_source: BySource[];
  by_model: ByModel[];
  by_user: ByUser[];
}

// ── Range options ──────────────────────────────────────────────────────────────

type Range = "7d" | "30d" | "90d";
const RANGES: Range[] = ["7d", "30d", "90d"];

// ── Skeleton helpers ───────────────────────────────────────────────────────────

function SkeletonBlock({ className }: { className?: string }) {
  return (
    <div className={cn("animate-pulse bg-secondary/40 rounded", className)} />
  );
}

function SkeletonChart() {
  return (
    <div className="space-y-2 p-4">
      <SkeletonBlock className="h-4 w-40" />
      <SkeletonBlock className="h-[220px] w-full rounded-xl mt-2" />
    </div>
  );
}

function SkeletonTable({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4">
      <SkeletonBlock className="h-4 w-32" />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-3 items-center py-1">
          <SkeletonBlock className="h-3 w-4" />
          <SkeletonBlock className="h-3 flex-1" />
          <SkeletonBlock className="h-3 w-14" />
          <SkeletonBlock className="h-3 w-14" />
        </div>
      ))}
    </div>
  );
}

// ── Custom tooltip for the line chart ─────────────────────────────────────────

interface TooltipPayloadItem {
  name: string;
  value: number;
  color: string;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
}

function ChartTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  const tokens = payload.find((p) => p.name === "tokens");
  const calls = payload.find((p) => p.name === "calls");
  return (
    <div className="bg-card border border-border rounded-lg px-3 py-2 shadow-lg text-xs font-mono">
      <p className="text-muted-foreground mb-1">{label}</p>
      {tokens && (
        <p className="text-foreground">
          Tokens:{" "}
          <span className="text-primary font-semibold">
            {tokens.value.toLocaleString()}
          </span>
        </p>
      )}
      {calls && (
        <p className="text-muted-foreground">
          Calls: <span className="text-foreground">{calls.value}</span>
        </p>
      )}
    </div>
  );
}

// ── Source pct bar ─────────────────────────────────────────────────────────────

function PctBar({ pct }: { pct: number }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="inline-block h-1.5 rounded-full bg-primary/20 w-16 relative overflow-hidden">
        <span
          className="absolute inset-y-0 left-0 rounded-full bg-primary transition-all duration-500"
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </span>
      <span className="text-[10px] font-mono text-muted-foreground">
        {pct.toFixed(1)}%
      </span>
    </span>
  );
}

// ── Card wrapper ───────────────────────────────────────────────────────────────

function Card({
  title,
  children,
  className,
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "bg-secondary/30 border border-border rounded-xl overflow-hidden",
        className
      )}
    >
      <div className="px-4 pt-4 pb-2">
        <h2 className="text-[10px] font-mono font-semibold text-muted-foreground/60 uppercase tracking-[0.18em]">
          {title}
        </h2>
      </div>
      {children}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function Analytics() {
  const [range, setRange] = useState<Range>("7d");
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .get<AnalyticsData>("/analytics/tokens?range=" + range)
      .then((res) => {
        if (!cancelled) setData(res.data);
      })
      .catch((err) => {
        console.error("Failed to load analytics", err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [range]);

  // Empty state check
  const isEmpty =
    !loading &&
    data !== null &&
    data.summary.total_tokens === 0 &&
    data.daily.length === 0 &&
    data.by_source.length === 0 &&
    data.by_model.length === 0 &&
    data.by_user.length === 0;

  const summary = data?.summary;

  return (
    <div className="flex flex-col h-full">
      {/* ── Page header ── */}
      <div className="flex-shrink-0 px-6 py-4 flex items-center justify-between border-b border-border/60">
        <div>
          <h1 className="text-base font-semibold text-foreground tracking-tight">
            Analytics
          </h1>
          {summary && !loading && (
            <p className="text-xs text-muted-foreground font-mono mt-0.5">
              {summary.total_tokens.toLocaleString()} tokens ·{" "}
              {summary.total_calls.toLocaleString()} calls ·{" "}
              {summary.unique_users} users
            </p>
          )}
          {loading && (
            <SkeletonBlock className="h-3 w-56 mt-1" />
          )}
        </div>

        {/* Range buttons */}
        <div className="flex items-center gap-1 p-1 bg-secondary/40 border border-border/60 rounded-lg">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={cn(
                "px-3 py-1.5 rounded-md text-xs font-mono font-medium transition-colors",
                range === r
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* ── Body ── */}
      <div className="flex-1 overflow-y-auto p-6">
        {/* Empty state */}
        {isEmpty && (
          <div className="flex flex-col items-center justify-center h-64 text-center">
            <BarChart2 className="w-10 h-10 text-muted-foreground/30 mb-3" />
            <p className="text-sm text-muted-foreground font-mono">
              No token data yet — AI calls will appear here once the system is
              used.
            </p>
          </div>
        )}

        {!isEmpty && (
          <div className="space-y-4">
            {/* ── Summary stat cards ── */}
            {!loading && summary && (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                {[
                  {
                    label: "Total Tokens",
                    value: summary.total_tokens.toLocaleString(),
                    icon: Zap,
                  },
                  {
                    label: "Input Tokens",
                    value: summary.input_tokens.toLocaleString(),
                    icon: Zap,
                  },
                  {
                    label: "Output Tokens",
                    value: summary.output_tokens.toLocaleString(),
                    icon: Zap,
                  },
                  {
                    label: "Total Calls",
                    value: summary.total_calls.toLocaleString(),
                    icon: BarChart2,
                  },
                  {
                    label: "Unique Users",
                    value: summary.unique_users.toLocaleString(),
                    icon: Users,
                  },
                ].map(({ label, value, icon: Icon }) => (
                  <div
                    key={label}
                    className="bg-secondary/30 border border-border rounded-xl p-4"
                  >
                    <p className="text-[9px] font-mono font-semibold text-muted-foreground/50 uppercase tracking-[0.18em] mb-2">
                      {label}
                    </p>
                    <div className="flex items-end justify-between">
                      <p className="text-xl font-bold text-foreground leading-none">
                        {value}
                      </p>
                      <Icon className="w-4 h-4 text-muted-foreground/40" />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Skeleton stat cards */}
            {loading && (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div
                    key={i}
                    className="bg-secondary/30 border border-border rounded-xl p-4 space-y-2"
                  >
                    <SkeletonBlock className="h-2 w-20" />
                    <SkeletonBlock className="h-6 w-16" />
                  </div>
                ))}
              </div>
            )}

            {/* ── Daily Token Usage chart ── */}
            <Card title="Daily Token Usage">
              {loading ? (
                <SkeletonChart />
              ) : (
                <div className="px-2 pb-4">
                  <ResponsiveContainer width="100%" height={220}>
                    <LineChart
                      data={data?.daily ?? []}
                      margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
                    >
                      <CartesianGrid
                        strokeDasharray="3 3"
                        stroke="hsl(var(--border))"
                        opacity={0.4}
                      />
                      <XAxis
                        dataKey="date"
                        tick={{
                          fontSize: 10,
                          fontFamily: "monospace",
                          fill: "hsl(var(--muted-foreground))",
                        }}
                        tickLine={false}
                        axisLine={false}
                        dy={6}
                      />
                      <YAxis
                        tickFormatter={(v: number) =>
                          v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v)
                        }
                        tick={{
                          fontSize: 10,
                          fontFamily: "monospace",
                          fill: "hsl(var(--muted-foreground))",
                        }}
                        tickLine={false}
                        axisLine={false}
                        width={40}
                      />
                      <Tooltip content={<ChartTooltip />} />
                      <Line
                        type="monotone"
                        dataKey="tokens"
                        stroke="hsl(var(--primary))"
                        strokeWidth={2}
                        dot={false}
                        activeDot={{ r: 4 }}
                      />
                      <Line
                        type="monotone"
                        dataKey="calls"
                        stroke="hsl(var(--muted-foreground))"
                        strokeWidth={1.5}
                        strokeDasharray="4 2"
                        dot={false}
                        activeDot={{ r: 3 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                  <div className="flex items-center gap-4 px-2 mt-1">
                    <span className="flex items-center gap-1.5 text-[10px] font-mono text-muted-foreground">
                      <span className="inline-block w-4 h-0.5 bg-primary rounded" />
                      Tokens
                    </span>
                    <span className="flex items-center gap-1.5 text-[10px] font-mono text-muted-foreground">
                      <span className="inline-block w-4 h-0.5 bg-muted-foreground/60 rounded" />
                      Calls
                    </span>
                  </div>
                </div>
              )}
            </Card>

            {/* ── Middle row: Source Breakdown + User Activity ── */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Source Breakdown */}
              <Card title="Source Breakdown">
                {loading ? (
                  <SkeletonTable />
                ) : (
                  <div className="pb-2">
                    <table className="w-full text-left">
                      <thead>
                        <tr className="border-b border-border/60">
                          {["#", "Source", "Calls", "Tokens %"].map((h) => (
                            <th
                              key={h}
                              className="px-4 py-2 text-[9px] font-mono font-semibold text-muted-foreground/50 uppercase tracking-[0.14em]"
                            >
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {(data?.by_source ?? []).map((row, i) => (
                          <tr
                            key={row.source}
                            className="border-b border-border/40 last:border-0 hover:bg-secondary/20 transition-colors"
                          >
                            <td className="px-4 py-2.5 text-[10px] font-mono text-muted-foreground/50">
                              {i + 1}
                            </td>
                            <td className="px-4 py-2.5 text-xs font-medium text-foreground capitalize">
                              {row.source}
                            </td>
                            <td className="px-4 py-2.5 text-[11px] font-mono text-muted-foreground">
                              {row.calls.toLocaleString()}
                            </td>
                            <td className="px-4 py-2.5">
                              <PctBar pct={row.pct} />
                            </td>
                          </tr>
                        ))}
                        {(data?.by_source ?? []).length === 0 && (
                          <tr>
                            <td
                              colSpan={4}
                              className="px-4 py-6 text-center text-xs font-mono text-muted-foreground/40"
                            >
                              No data
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>

              {/* User Activity */}
              <Card title="User Activity">
                {loading ? (
                  <SkeletonTable />
                ) : (
                  <div className="pb-2">
                    <table className="w-full text-left">
                      <thead>
                        <tr className="border-b border-border/60">
                          {["User", "Calls", "Tokens"].map((h) => (
                            <th
                              key={h}
                              className="px-4 py-2 text-[9px] font-mono font-semibold text-muted-foreground/50 uppercase tracking-[0.14em]"
                            >
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {(data?.by_user ?? []).map((row) => (
                          <tr
                            key={row.user_id ?? row.username}
                            className="border-b border-border/40 last:border-0 hover:bg-secondary/20 transition-colors"
                          >
                            <td className="px-4 py-2.5">
                              {row.username === "system" ? (
                                <span className="text-xs italic text-muted-foreground/60 font-mono">
                                  system
                                </span>
                              ) : (
                                <span className="text-xs font-medium text-foreground">
                                  {row.username}
                                </span>
                              )}
                            </td>
                            <td className="px-4 py-2.5 text-[11px] font-mono text-muted-foreground">
                              {row.calls.toLocaleString()}
                            </td>
                            <td className="px-4 py-2.5 text-[11px] font-mono text-muted-foreground">
                              {row.tokens.toLocaleString()}
                            </td>
                          </tr>
                        ))}
                        {(data?.by_user ?? []).length === 0 && (
                          <tr>
                            <td
                              colSpan={3}
                              className="px-4 py-6 text-center text-xs font-mono text-muted-foreground/40"
                            >
                              No data
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            </div>

            {/* ── Model Usage ── */}
            <Card title="Model Usage">
              {loading ? (
                <SkeletonTable rows={3} />
              ) : (
                <div className="pb-2">
                  <table className="w-full text-left">
                    <thead>
                      <tr className="border-b border-border/60">
                        {["#", "Model", "Calls", "Tokens", "Share"].map((h) => (
                          <th
                            key={h}
                            className="px-4 py-2 text-[9px] font-mono font-semibold text-muted-foreground/50 uppercase tracking-[0.14em]"
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(data?.by_model ?? []).map((row, i) => (
                        <tr
                          key={row.model}
                          className="border-b border-border/40 last:border-0 hover:bg-secondary/20 transition-colors"
                        >
                          <td className="px-4 py-2.5 text-[10px] font-mono text-muted-foreground/50">
                            {i + 1}
                          </td>
                          <td className="px-4 py-2.5 text-xs font-medium text-foreground font-mono">
                            {row.model}
                          </td>
                          <td className="px-4 py-2.5 text-[11px] font-mono text-muted-foreground">
                            {row.calls.toLocaleString()}
                          </td>
                          <td className="px-4 py-2.5 text-[11px] font-mono text-muted-foreground">
                            {row.tokens.toLocaleString()}
                          </td>
                          <td className="px-4 py-2.5">
                            <PctBar pct={row.pct} />
                          </td>
                        </tr>
                      ))}
                      {(data?.by_model ?? []).length === 0 && (
                        <tr>
                          <td
                            colSpan={5}
                            className="px-4 py-6 text-center text-xs font-mono text-muted-foreground/40"
                          >
                            No data
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}
