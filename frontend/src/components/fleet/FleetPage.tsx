import * as React from "react";
import { useState } from "react";
import { Check, Copy, type LucideIcon } from "lucide-react";
import { cn } from "../../lib/utils";

/* ──────────────────────────────────────────────────────────────────────────
   Fleet scaffold — one shared visual language for the whole Fleet section.
   Every Fleet page opens with the same command bar: an icon chip + title +
   one-line purpose on the left, a vitals readout (LED stat pills) + actions
   on the right. Quiet, consistent, recognizable.
   ────────────────────────────────────────────────────────────────────────── */

/* Shared form-control class so every Fleet input/select/textarea matches. */
export const fieldCls =
  "w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground " +
  "placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-primary " +
  "focus:border-primary transition-colors";

/* Mono uppercase eyebrow used for section labels across Fleet. */
export function Eyebrow({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <p className={cn("text-[10px] font-mono font-semibold uppercase tracking-[0.16em] text-muted-foreground/70", className)}>
      {children}
    </p>
  );
}

interface FleetPageProps {
  icon: LucideIcon;
  title: string;
  subtitle: string;
  vitals?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}

export function FleetPage({ icon: Icon, title, subtitle, vitals, actions, children }: FleetPageProps) {
  return (
    <div className="p-6 fade-up">
      <header className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div className="flex items-start gap-3 min-w-0">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 mt-0.5 bg-gradient-to-br from-cyan-400 to-sky-600 shadow-lg shadow-cyan-500/25 dark:logo-glow">
            <Icon className="w-5 h-5 text-white" strokeWidth={2} />
          </div>
          <div className="min-w-0">
            <h1 className="text-2xl font-bold text-foreground leading-tight tracking-tight">{title}</h1>
            <p className="text-sm text-muted-foreground mt-0.5 max-w-xl">{subtitle}</p>
          </div>
        </div>
        {actions && <div className="flex items-center gap-2 flex-shrink-0">{actions}</div>}
      </header>

      {vitals && <div className="flex flex-wrap gap-2.5 mb-6">{vitals}</div>}

      {children}
    </div>
  );
}

/* ── Vitals stat pill ──────────────────────────────────────────────────────
   Compact LED-accented count. Optional onClick turns it into a filter chip
   (active prop draws the cyan ring).                                          */
type Tone = "cyan" | "green" | "amber" | "red" | "blue" | "purple" | "slate";

const TONE_BAR: Record<Tone, string> = {
  cyan: "stat-card-cyan",
  green: "stat-card-green",
  amber: "stat-card-amber",
  red: "stat-card-red",
  blue: "stat-card-blue",
  purple: "stat-card-purple",
  slate: "",
};

interface FleetStatProps {
  value: React.ReactNode;
  label: string;
  tone?: Tone;
  active?: boolean;
  onClick?: () => void;
}

export function FleetStat({ value, label, tone = "cyan", active, onClick }: FleetStatProps) {
  const interactive = !!onClick;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!interactive}
      className={cn(
        "stat-card flex items-baseline gap-2.5 bg-card border rounded-lg pl-4 pr-5 py-2.5 text-left",
        "dark:glass transition-all duration-150",
        TONE_BAR[tone],
        active ? "border-primary/50 dark:shadow-glow-sm" : "border-border",
        interactive && "hover:border-primary/40 cursor-pointer",
        !interactive && "cursor-default",
      )}
    >
      <span className="text-2xl font-bold tabular-nums leading-none text-foreground">{value}</span>
      <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground leading-none">{label}</span>
    </button>
  );
}

/* ── Minion status — single source of truth for active/pending/offline ────── */
const MINION_DOT: Record<string, string> = {
  active: "bg-emerald-500 shadow-[0_0_6px_rgb(52_211_153_/_0.8)] dot-pulse",
  pending: "bg-amber-400 shadow-[0_0_5px_rgb(245_158_11_/_0.7)] dot-pulse",
  offline: "bg-red-500 shadow-[0_0_5px_rgb(239_68_68_/_0.6)]",
};
const MINION_TAG: Record<string, string> = {
  active: "tag-green",
  pending: "tag-amber",
  offline: "tag-red",
};

export function MinionStatusDot({ status, className }: { status: string; className?: string }) {
  return <span className={cn("inline-block w-2 h-2 rounded-full flex-shrink-0", MINION_DOT[status] ?? "bg-slate-500", className)} />;
}

export function MinionStatusTag({ status }: { status: string }) {
  return (
    <span className={cn("tag", MINION_TAG[status] ?? "")}>
      <span className={cn("w-1.5 h-1.5 rounded-full", MINION_DOT[status]?.split(" ")[0] ?? "bg-slate-500")} />
      {status}
    </span>
  );
}

/* ── CopyBlock — mono snippet with a copy button (install commands, tokens) ── */
export function CopyBlock({ value, label, className }: { value: string; label?: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked — silently ignore, the text is still selectable */
    }
  }
  return (
    <div className={className}>
      {label && <Eyebrow className="mb-1.5">{label}</Eyebrow>}
      <div className="flex items-stretch gap-2">
        <code className="flex-1 bg-background border border-border rounded-lg px-3 py-2 font-mono text-[11px] text-foreground/90 break-all leading-relaxed">
          {value}
        </code>
        <button
          onClick={copy}
          title="Copy"
          className="flex-shrink-0 w-9 grid place-items-center rounded-lg border border-border bg-card text-muted-foreground hover:text-primary hover:border-primary/40 transition-colors"
        >
          {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
        </button>
      </div>
    </div>
  );
}

/* ── Surface — the one card style for Fleet panels ────────────────────────── */
export function Surface({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("bg-card border border-border rounded-xl dark:glass", className)}>{children}</div>
  );
}
