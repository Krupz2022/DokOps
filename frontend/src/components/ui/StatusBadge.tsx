import { cn } from "../../lib/utils";

/* ── Per-status configuration ─────────────────────────────── */
interface StatusConfig {
  badge: string;   // badge background + text + border
  dot: string;     // dot color + glow
  pulse: boolean;  // whether the dot pulses
  flash?: boolean; // whether dot hard-flashes (error states)
}

const STATUS_MAP: Record<string, StatusConfig> = {
  Running: {
    badge: "bg-emerald-500/8 text-emerald-600 border-emerald-500/25 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20 dark:shadow-[0_0_10px_rgb(52_211_153_/_0.12)]",
    dot: "bg-emerald-500 shadow-[0_0_5px_rgb(52_211_153_/_0.8)]",
    pulse: true,
  },
  Succeeded: {
    badge: "bg-emerald-500/8 text-emerald-600 border-emerald-500/25 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20",
    dot: "bg-emerald-500",
    pulse: false,
  },
  CrashLoopBackOff: {
    badge: "bg-red-500/8 text-red-600 border-red-500/30 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/25 dark:shadow-[0_0_10px_rgb(239_68_68_/_0.12)]",
    dot: "bg-red-500 shadow-[0_0_5px_rgb(239_68_68_/_0.9)]",
    pulse: false,
    flash: true,
  },
  Error: {
    badge: "bg-red-500/8 text-red-600 border-red-500/30 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/25",
    dot: "bg-red-500",
    pulse: false,
    flash: true,
  },
  OOMKilled: {
    badge: "bg-red-500/8 text-red-600 border-red-500/30 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/25 dark:shadow-[0_0_10px_rgb(239_68_68_/_0.12)]",
    dot: "bg-red-500 shadow-[0_0_5px_rgb(239_68_68_/_0.9)]",
    pulse: false,
    flash: true,
  },
  ImagePullBackOff: {
    badge: "bg-red-500/8 text-red-600 border-red-500/30 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/25",
    dot: "bg-red-500",
    pulse: false,
    flash: true,
  },
  ErrImagePull: {
    badge: "bg-red-500/8 text-red-600 border-red-500/30 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/25",
    dot: "bg-red-500",
    pulse: false,
    flash: true,
  },
  Pending: {
    badge: "bg-amber-500/8 text-amber-600 border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/25 dark:shadow-[0_0_8px_rgb(245_158_11_/_0.1)]",
    dot: "bg-amber-400 shadow-[0_0_4px_rgb(245_158_11_/_0.7)]",
    pulse: true,
  },
  Terminating: {
    badge: "bg-slate-500/8 text-slate-500 border-slate-500/20 dark:bg-slate-500/10 dark:text-slate-400 dark:border-slate-500/20",
    dot: "bg-slate-400",
    pulse: true,
  },
  Unknown: {
    badge: "bg-slate-500/8 text-slate-500 border-slate-500/20 dark:bg-slate-500/10 dark:text-slate-400 dark:border-slate-500/20",
    dot: "bg-slate-400",
    pulse: false,
  },
};

const FALLBACK: StatusConfig = {
  badge: "bg-slate-500/8 text-slate-500 border-slate-500/20 dark:bg-slate-500/10 dark:text-slate-400 dark:border-slate-500/20",
  dot: "bg-slate-400",
  pulse: false,
};

interface StatusBadgeProps {
  status: string;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const cfg = STATUS_MAP[status] ?? FALLBACK;

  return (
    <span className={cn(
      "inline-flex items-center gap-1.5 border px-2 py-0.5",
      "rounded-sm font-mono text-[11px] font-medium tracking-wide",
      cfg.badge,
      className
    )}>
      {/* LED indicator dot */}
      <span className={cn(
        "w-1.5 h-1.5 rounded-full flex-shrink-0",
        cfg.dot,
        cfg.flash && "animate-[pulse-flash_1.2s_ease-in-out_infinite]",
        cfg.pulse && !cfg.flash && "dot-pulse",
      )} />
      {status}
    </span>
  );
}

/* ── StatusDot — standalone LED ───────────────────────────── */
const DOT_MAP: Record<string, string> = {
  Running:          "bg-emerald-500 shadow-[0_0_6px_rgb(52_211_153_/_0.7)]",
  Succeeded:        "bg-emerald-500",
  CrashLoopBackOff: "bg-red-500 shadow-[0_0_6px_rgb(239_68_68_/_0.8)]",
  Error:            "bg-red-500 shadow-[0_0_6px_rgb(239_68_68_/_0.8)]",
  OOMKilled:        "bg-red-500 shadow-[0_0_6px_rgb(239_68_68_/_0.8)]",
  ImagePullBackOff: "bg-red-500",
  ErrImagePull:     "bg-red-500",
  Pending:          "bg-amber-400 shadow-[0_0_5px_rgb(245_158_11_/_0.6)]",
  Terminating:      "bg-slate-400",
  Unknown:          "bg-slate-400",
};

interface StatusDotProps {
  status: string;
  className?: string;
}

export function StatusDot({ status, className }: StatusDotProps) {
  const dot = DOT_MAP[status] ?? "bg-slate-400";
  const cfg = STATUS_MAP[status] ?? FALLBACK;
  return (
    <span className={cn(
      "inline-block w-2 h-2 rounded-full flex-shrink-0",
      dot,
      cfg.flash && "animate-[pulse-flash_1.2s_ease-in-out_infinite]",
      cfg.pulse && !cfg.flash && "dot-pulse",
      className
    )} />
  );
}
