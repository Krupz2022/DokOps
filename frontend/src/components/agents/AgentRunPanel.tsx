import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, SkipForward, Loader2, CheckCircle, XCircle, Clock, Wrench, Eye, ShieldAlert, SkipForward as SkipIcon } from "lucide-react";
import api, { workflowApi } from "../../lib/api";
import { useToast } from "../../context/ToastContext";
import { cn } from "../../lib/utils";

interface StepEntry {
  type: string;
  message?: string;
  tool?: string;
  run_id?: number;
  timestamp?: string;
  status?: string;
  [key: string]: unknown;
}

interface AgentRun {
  id: number;
  status: string;
  ai_summary: string | null;
  step_results: StepEntry[];
}

interface Props {
  runId: number;
  workflowId: number;
  onBack: () => void;
}

const STATUS_BADGE: Record<string, string> = {
  running:            "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/30",
  completed:          "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/30",
  failed:             "bg-destructive/10 text-destructive border-destructive/30",
  awaiting_approval:  "bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/30",
  pending:            "bg-muted text-muted-foreground border-border",
};

function StepIcon({ type }: { type: string }) {
  const cls = "w-4 h-4 shrink-0 mt-0.5";
  switch (type) {
    case "tool_call":           return <Wrench className={cn(cls, "text-primary")} />;
    case "observation":         return <Eye className={cn(cls, "text-muted-foreground")} />;
    case "awaiting_approval":   return <ShieldAlert className={cn(cls, "text-amber-500")} />;
    case "approval_skipped":    return <SkipIcon className={cn(cls, "text-muted-foreground")} />;
    case "tool_blocked":        return <XCircle className={cn(cls, "text-destructive")} />;
    case "completed":           return <CheckCircle className={cn(cls, "text-emerald-500")} />;
    case "error":               return <XCircle className={cn(cls, "text-destructive")} />;
    default:                    return <Clock className={cn(cls, "text-muted-foreground")} />;
  }
}

function formatEntry(entry: StepEntry): string {
  if (entry.message) return entry.message;
  if (entry.tool)    return `Tool: ${entry.tool}`;
  if (entry.type === "completed") return `Run ${entry.status ?? "completed"}`;
  return JSON.stringify(entry);
}

const STEP_TYPES    = new Set(["step", "tool_call", "observation", "awaiting_approval", "approval_skipped", "tool_blocked", "error", "completed"]);
const NARRATE_TYPES = new Set(["result", "model"]);

export default function AgentRunPanel({ runId, workflowId, onBack }: Props) {
  const { toast } = useToast();
  const [stepEntries,    setStepEntries]    = useState<StepEntry[]>([]);
  const [narrateEntries, setNarrateEntries] = useState<StepEntry[]>([]);
  const [status,         setStatus]         = useState<string>("running");
  const [summary,        setSummary]        = useState<string | null>(null);
  const [awaitingApproval, setAwaitingApproval] = useState<{ tool: string } | null>(null);
  const [actioning,      setActioning]      = useState(false);
  const stepsBottomRef   = useRef<HTMLDivElement>(null);
  const narrateBottomRef = useRef<HTMLDivElement>(null);

  const pushEvent = (event: StepEntry) => {
    if (STEP_TYPES.has(event.type)) {
      setStepEntries((prev) => [...prev, event]);
    }
    if (NARRATE_TYPES.has(event.type)) {
      setNarrateEntries((prev) => [...prev, event]);
    }
  };

  useEffect(() => {
    api.get(`/workflows/runs/${runId}`).then((res) => {
      const run: AgentRun = res.data;
      setStatus(run.status);
      setSummary(run.ai_summary);
      const all = run.step_results ?? [];
      setStepEntries(all.filter((e) => STEP_TYPES.has(e.type)));
      setNarrateEntries(all.filter((e) => NARRATE_TYPES.has(e.type)));
      if (run.status === "awaiting_approval") {
        const pending = all.slice().reverse().find((e) => e.type === "awaiting_approval");
        if (pending?.tool) setAwaitingApproval({ tool: pending.tool as string });
      }
    }).catch(() => {});

    let es: EventSource | null = null;
    let cancelled = false;

    workflowApi.issueStreamTicket(runId).then(({ data }) => {
      if (cancelled) return;
      const source = new EventSource(workflowApi.streamUrl(runId, data.ticket));
      es = source;
      source.onmessage = (e) => {
        try {
          const event: StepEntry = JSON.parse(e.data);
          if (event.type === "ping") return;
          pushEvent(event);
          if (event.type === "awaiting_approval" && event.tool) {
            setAwaitingApproval({ tool: event.tool as string });
            setStatus("awaiting_approval");
          }
          if (event.type === "step") {
            setAwaitingApproval(null);
            setStatus("running");
          }
          if (event.type === "result") setSummary(event.message ?? null);
          if (event.type === "completed") {
            setStatus(event.status ?? "completed");
            source.close();
          }
        } catch { /* ignore */ }
      };
      source.onerror = () => source.close();
    }).catch(() => {});

    return () => { cancelled = true; es?.close(); };
  }, [runId]);

  useEffect(() => { stepsBottomRef.current?.scrollIntoView({ behavior: "smooth" }); },   [stepEntries]);
  useEffect(() => { narrateBottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [narrateEntries]);

  const handleApprove = async () => {
    setActioning(true);
    try {
      await api.post(`/workflows/${workflowId}/runs/${runId}/approve`);
      setAwaitingApproval(null);
      setStatus("running");
      toast("Action approved", "success");
    } catch {
      toast("Failed to approve", "error");
    } finally { setActioning(false); }
  };

  const handleSkip = async () => {
    setActioning(true);
    try {
      await api.post(`/workflows/${workflowId}/runs/${runId}/skip`);
      setAwaitingApproval(null);
      setStatus("running");
      toast("Action skipped", "success");
    } catch {
      toast("Failed to skip", "error");
    } finally { setActioning(false); }
  };

  const isLive = status === "running" || status === "awaiting_approval" || status === "pending";

  return (
    <div className="flex flex-col h-full gap-4">
      {/* Top bar */}
      <div className="flex items-center justify-between flex-shrink-0">
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-muted-foreground hover:text-foreground text-sm transition-colors"
        >
          <ArrowLeft size={16} />
          Back
        </button>
        <div className="flex items-center gap-3">
          <span className="text-muted-foreground text-sm">Run #{runId}</span>
          <span className={cn("px-3 py-1 rounded-full text-xs font-medium border capitalize", STATUS_BADGE[status] ?? STATUS_BADGE.pending)}>
            {isLive && <Loader2 className="inline w-3 h-3 mr-1 animate-spin" />}
            {status}
          </span>
        </div>
      </div>

      {/* Approval banner */}
      {awaitingApproval && (
        <div className="flex items-center justify-between gap-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 flex-shrink-0">
          <div>
            <p className="text-amber-600 dark:text-amber-300 text-sm font-medium">Approval required</p>
            <p className="text-amber-600/70 dark:text-amber-400/70 text-xs mt-0.5">
              Agent wants to run <span className="font-mono font-semibold">{awaitingApproval.tool}</span>
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleApprove}
              disabled={actioning}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 border border-emerald-500/30 text-xs font-medium hover:bg-emerald-500/30 disabled:opacity-50 transition-colors"
            >
              <Check className="w-3.5 h-3.5" />
              Approve
            </button>
            <button
              onClick={handleSkip}
              disabled={actioning}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-secondary text-muted-foreground border border-border text-xs font-medium hover:bg-secondary/80 disabled:opacity-50 transition-colors"
            >
              <SkipForward className="w-3.5 h-3.5" />
              Skip
            </button>
          </div>
        </div>
      )}

      {/* Two-panel body */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[1fr_1fr] gap-4 min-h-0">
        {/* Left: Steps / tool events */}
        <div className="bg-card border border-border rounded-xl p-4 flex flex-col min-h-0">
          <h3 className="text-foreground text-sm font-semibold mb-3">Steps</h3>
          <div className="overflow-y-auto space-y-2 flex-1">
            {stepEntries.length === 0 && isLive && (
              <p className="text-muted-foreground text-xs animate-pulse">Starting agent…</p>
            )}
            {stepEntries.length === 0 && !isLive && (
              <p className="text-muted-foreground text-xs">No step events recorded.</p>
            )}
            {stepEntries.map((entry, i) => (
              <div
                key={i}
                className="flex items-start gap-3 bg-background border border-border rounded-lg px-3 py-2"
              >
                <StepIcon type={entry.type} />
                <div className="flex-1 min-w-0">
                  <p className={cn(
                    "text-xs leading-relaxed break-words",
                    entry.type === "tool_blocked"       ? "text-destructive" :
                    entry.type === "awaiting_approval"  ? "text-amber-600 dark:text-amber-400" :
                    entry.type === "completed"          ? "text-emerald-700 dark:text-emerald-400" :
                    "text-foreground/80"
                  )}>
                    {formatEntry(entry)}
                  </p>
                </div>
                {entry.timestamp && (
                  <span className="text-muted-foreground/50 text-xs shrink-0">
                    {new Date(entry.timestamp as string).toLocaleTimeString()}
                  </span>
                )}
              </div>
            ))}
            <div ref={stepsBottomRef} />
          </div>
        </div>

        {/* Right: AI Narration */}
        <div className="bg-card border border-border rounded-xl p-4 flex flex-col min-h-0">
          <h3 className="text-foreground text-sm font-semibold mb-3">AI Narration</h3>
          <div className="overflow-y-auto flex-1 space-y-2">
            {narrateEntries.length === 0 && !summary && isLive && (
              <p className="text-muted-foreground text-xs animate-pulse">Waiting for narration…</p>
            )}
            {narrateEntries.length === 0 && !summary && !isLive && (
              <p className="text-muted-foreground text-xs">No narration recorded.</p>
            )}
            {/* Show persisted summary when viewing a completed historical run */}
            {narrateEntries.length === 0 && summary && (
              <div className="text-foreground/80 text-xs bg-muted/40 border border-border rounded-lg px-3 py-2 leading-relaxed whitespace-pre-wrap">
                {summary}
              </div>
            )}
            {narrateEntries.map((entry, i) => (
              <div
                key={i}
                className="text-foreground/80 text-xs bg-muted/40 border border-border rounded-lg px-3 py-2 leading-relaxed"
              >
                {formatEntry(entry)}
              </div>
            ))}
            {/* Append summary as final entry during a live run */}
            {narrateEntries.length > 0 && summary && (
              <div className="text-foreground/80 text-xs bg-muted/40 border border-border rounded-lg px-3 py-2 leading-relaxed whitespace-pre-wrap">
                {summary}
              </div>
            )}
            <div ref={narrateBottomRef} />
          </div>
        </div>
      </div>
    </div>
  );
}
