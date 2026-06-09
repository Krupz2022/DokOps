import { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { SkeletonCard, SkeletonRow } from "../components/ui/Skeleton";
import { Cpu, HardDrive, AlertTriangle, Server, Layers, Globe, BarChart3, RefreshCw } from "lucide-react";
import { useAppContext } from "../context/AppContext";
import { cn } from "../lib/utils";

interface DashboardStats {
  namespaces_count: number;
  nodes_count: number;
  status: string;
}

function AnimatedNumber({ value }: { value: number | string }) {
  const [display, setDisplay] = useState(value);
  const prevRef = useRef(value);

  useEffect(() => {
    if (prevRef.current === value || typeof value !== "number") {
      setDisplay(value);
      return;
    }
    const start = typeof prevRef.current === "number" ? prevRef.current : 0;
    const end = value;
    const duration = 600;
    const startTime = performance.now();
    const tick = (now: number) => {
      const progress = Math.min((now - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(Math.round(start + (end - start) * eased));
      if (progress < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    prevRef.current = value;
  }, [value]);

  return <>{display}</>;
}

function StatCard({
  label, value, sub, subVariant = "muted", accentClass, icon: Icon, wide = false, animateNumber = false,
}: {
  label: string;
  value: string | number;
  sub: string;
  subVariant?: "muted" | "green" | "amber" | "red" | "cyan";
  accentClass: string;
  icon: React.ElementType;
  wide?: boolean;
  animateNumber?: boolean;
}) {
  const subColor = {
    muted: "text-muted-foreground",
    green: "text-emerald-500 dark:text-emerald-400",
    amber: "text-amber-500 dark:text-amber-400",
    red: "text-red-500 dark:text-red-400",
    cyan: "text-cyan dark:text-cyan",
  }[subVariant];

  return (
    <div className={cn(
      "bg-card border border-border stat-card px-5 py-5",
      "hover:border-border/60 transition-colors duration-150",
      accentClass,
      wide && "sm:col-span-2"
    )}>
      <div className="flex items-start justify-between mb-4 pl-3">
        <p className="text-[10px] font-mono font-semibold text-muted-foreground/50 uppercase tracking-[0.18em]">
          {label}
        </p>
        <div className="w-7 h-7 rounded-lg flex items-center justify-center bg-secondary/80 border border-border/60 dark:shadow-[inset_0_1px_0_hsl(0_0%_100%_/_0.04)]">
          <Icon className="w-3.5 h-3.5 text-muted-foreground/70" />
        </div>
      </div>
      <p className={cn(
        "font-bold text-foreground leading-none tracking-tight pl-3 mb-2.5",
        wide ? "text-5xl" : "text-3xl"
      )}>
        {animateNumber && typeof value === "number"
          ? <AnimatedNumber value={value} />
          : value
        }
      </p>
      <p className={cn("text-[11px] font-medium pl-3", subColor)}>{sub}</p>
    </div>
  );
}

function NodeRow({ node }: { node: any }) {
  const cpuPct = Math.min(node.cpu_percent, 100);
  const memPct = Math.min(node.memory_percent, 100);

  const barGradient = (pct: number) =>
    pct > 80
      ? "from-red-500 to-red-400"
      : pct > 50
        ? "from-amber-500 to-amber-400"
        : "from-emerald-500 to-cyan-500";

  const barGlow = (pct: number) =>
    pct > 80
      ? "shadow-[0_0_6px_rgb(239_68_68_/_0.7)]"
      : pct > 50
        ? "shadow-[0_0_5px_rgb(245_158_11_/_0.5)]"
        : "";

  const tagClass = (pct: number) =>
    pct > 80 ? "tag tag-red" : pct > 50 ? "tag tag-amber" : "tag tag-green";

  const isCritical = cpuPct > 80 || memPct > 80;

  return (
    <div className={cn(
      "flex items-center gap-4 px-5 py-3 border-b border-border last:border-0 transition-colors",
      isCritical
        ? "hover:bg-red-500/5 dark:bg-red-500/[0.03]"
        : "hover:bg-secondary/20"
    )}>
      {/* Node name */}
      <div className="flex items-center gap-2 w-44 flex-shrink-0">
        <span
          className="w-1.5 h-1.5 rounded-full flex-shrink-0"
          style={{
            background: isCritical ? "rgb(239 68 68)" : "rgb(52 211 153)",
            boxShadow: isCritical
              ? "0 0 5px rgb(239 68 68 / 0.8)"
              : "0 0 5px rgb(52 211 153 / 0.7)",
            animation: "pulse-dot 2s ease-in-out infinite",
          }}
        />
        <Server className="w-3 h-3 text-muted-foreground flex-shrink-0" />
        <span className="text-[11px] font-mono text-foreground truncate">{node.name}</span>
      </div>

      {/* Metrics */}
      <div className="flex-1 grid grid-cols-2 gap-5">
        {/* CPU */}
        <div className="flex items-center gap-2.5">
          <Cpu className="w-3 h-3 text-muted-foreground/60 flex-shrink-0" />
          <div className="flex-1 h-1.5 bg-secondary/60 rounded-full overflow-hidden">
            <div
              className={cn("h-full bg-gradient-to-r rounded-full transition-all duration-700", barGradient(cpuPct), barGlow(cpuPct))}
              style={{ width: `${cpuPct}%` }}
            />
          </div>
          <span className={cn(tagClass(cpuPct), "min-w-[42px] text-center justify-center tabular-nums")}>
            {node.cpu_percent}%
          </span>
        </div>

        {/* Memory */}
        <div className="flex items-center gap-2.5">
          <HardDrive className="w-3 h-3 text-muted-foreground/60 flex-shrink-0" />
          <div className="flex-1 h-1.5 bg-secondary/60 rounded-full overflow-hidden">
            <div
              className={cn("h-full bg-gradient-to-r rounded-full transition-all duration-700", barGradient(memPct), barGlow(memPct))}
              style={{ width: `${memPct}%` }}
            />
          </div>
          <span className={cn(tagClass(memPct), "min-w-[42px] text-center justify-center tabular-nums")}>
            {node.memory_percent}%
          </span>
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  useAppContext();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [metrics, setMetrics] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  useEffect(() => {
    if (!localStorage.getItem("access_token")) { navigate("/login"); return; }
    fetchData();
  }, []);

  const fetchData = async () => {
    setRefreshing(true);
    try {
      const [statsRes, metricsRes] = await Promise.all([
        api.get("/dashboard/stats"),
        api.get("/dashboard/metrics"),
      ]);
      setStats(statsRes.data);
      setMetrics(metricsRes.data);
      setLastUpdated(new Date());
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const isHealthy = stats?.status?.toLowerCase() === "healthy" || stats?.status?.toLowerCase() === "ok";

  const pageHeader = (
    <div className="flex-shrink-0 px-6 py-4 flex items-center justify-between border-b border-border/60">
      <div className="flex items-center gap-3">
        <h1 className="text-base font-semibold text-foreground tracking-tight">Dashboard</h1>
        <div className="h-4 w-px bg-border" />
        <span className={cn("tag", isHealthy ? "tag-green" : stats ? "tag-amber" : "tag-cyan")}>
          <span className={cn(
            "w-1.5 h-1.5 rounded-full inline-block",
            isHealthy ? "bg-emerald-500" : stats ? "bg-amber-500" : "bg-primary"
          )} />
          {stats ? (isHealthy ? "healthy" : stats.status || "degraded") : "checking"}
        </span>
        <span className="text-[10px] font-mono text-muted-foreground/50">
          {lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
        </span>
      </div>
      <button
        onClick={fetchData}
        disabled={refreshing}
        className="flex items-center gap-1.5 text-[11px] font-medium font-mono text-muted-foreground hover:text-foreground bg-secondary/50 hover:bg-secondary transition-colors px-3 py-1.5 border border-border"
      >
        <RefreshCw className={cn("w-3 h-3", refreshing && "animate-spin")} />
        refresh
      </button>
    </div>
  );

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        {pageHeader}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}
            </div>
            <div className="bg-card border border-border overflow-hidden">
              <div className="px-5 py-4 border-b border-border">
                <div className="h-3 w-20 bg-secondary animate-pulse" />
              </div>
              {[...Array(3)].map((_, i) => <SkeletonRow key={i} />)}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {pageHeader}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="space-y-4 max-w-5xl">

          {/* Asymmetric stat grid — status gets double width */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard
              label="Cluster Status"
              value={stats?.status ?? "—"}
              sub={isHealthy ? "All systems nominal" : "Check required"}
              subVariant={isHealthy ? "green" : "amber"}
              accentClass="stat-card-green fade-up fade-up-1"
              icon={Globe}
              wide
            />
            <StatCard
              label="Nodes"
              value={stats?.nodes_count ?? "—"}
              sub="Active nodes"
              accentClass="stat-card-cyan fade-up fade-up-2"
              icon={Server}
              animateNumber
            />
            <StatCard
              label="Namespaces"
              value={stats?.namespaces_count ?? "—"}
              sub="Isolated envs"
              accentClass="stat-card-blue fade-up fade-up-3"
              icon={Layers}
              animateNumber
            />
          </div>

          {/* Metrics row */}
          <div className="fade-up fade-up-4">
            <StatCard
              label="Metrics Server"
              value={metrics?.available ? "Active" : "N/A"}
              sub={metrics?.available ? "Real-time metrics available" : "Install metrics-server to enable"}
              subVariant={metrics?.available ? "green" : "amber"}
              accentClass={cn("stat-card w-full", metrics?.available ? "stat-card-green" : "stat-card-amber")}
              icon={BarChart3}
            />
          </div>

          {/* Node health */}
          {metrics && !metrics.available ? (
            <div className="bg-card border border-border overflow-hidden fade-up">
              <div className="flex items-center gap-2.5 px-5 py-3.5 border-b border-border">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
                <h3 className="text-sm font-semibold text-foreground">Metrics Server Not Detected</h3>
                <span className="tag tag-amber ml-auto">install required</span>
              </div>
              <div className="px-5 py-4">
                <p className="text-sm text-muted-foreground mb-3 leading-relaxed">
                  Deploy the Kubernetes Metrics Server to enable real-time CPU &amp; memory visibility.
                </p>
                <div className="rounded-xl overflow-hidden border border-border/60 dark:border-white/5">
                  <div className="flex items-center justify-between px-4 py-2 bg-[hsl(222_50%_3%)] border-b border-white/5">
                    <span className="text-[10px] font-mono text-slate-500 uppercase tracking-widest">bash</span>
                  </div>
                  <pre className="bg-[hsl(222_50%_3%)] text-emerald-400 text-[11px] px-5 py-3.5 overflow-x-auto font-mono leading-relaxed m-0">
                    kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
                  </pre>
                </div>
              </div>
            </div>
          ) : metrics?.available && metrics.nodes?.length > 0 ? (
            <div className="bg-card border border-border overflow-hidden fade-up">
              <div className="flex items-center justify-between px-5 py-3.5 border-b border-border">
                <div className="flex items-center gap-2.5">
                  <h3 className="text-sm font-semibold text-foreground">Node Health</h3>
                  <span className="tag tag-green">{metrics.nodes.length} online</span>
                </div>
                <div className="flex items-center gap-4 text-[10px] text-muted-foreground font-mono">
                  <span className="flex items-center gap-1"><Cpu className="w-3 h-3" /> CPU</span>
                  <span className="flex items-center gap-1"><HardDrive className="w-3 h-3" /> MEM</span>
                </div>
              </div>
              {metrics.nodes.map((node: any) => (
                <NodeRow key={node.name} node={node} />
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
