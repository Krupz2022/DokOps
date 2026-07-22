import { useEffect, useRef, useState } from "react";
import { Loader2, Wrench, Eye, CheckCircle, XCircle, Cpu, X } from "lucide-react";

interface AgentEvent {
  type: string;
  message?: string;
}

// The global agentic loop streams these; we only render the informative ones.
const STEP_TYPES = new Set(["step", "model", "warning", "pending_operation"]);

function StepIcon({ type, message }: { type: string; message?: string }) {
  const cls = "w-4 h-4 shrink-0 mt-0.5";
  if (type === "model") return <Cpu className={`${cls} text-muted-foreground`} />;
  if (type === "warning") return <XCircle className={`${cls} text-amber-500`} />;
  // A "<tool> done." step reads as an observation; a "<tool>..." step is a call.
  if (message && /\bdone\.?$/.test(message)) return <Eye className={`${cls} text-muted-foreground`} />;
  return <Wrench className={`${cls} text-primary`} />;
}

export default function BlueprintTroubleshootPanel({
  runId,
  onClose,
}: {
  runId: string;
  onClose: () => void;
}) {
  const [steps, setSteps] = useState<AgentEvent[]>([]);
  const [answer, setAnswer] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setSteps([]);
    setAnswer(null);
    setDone(false);
    setError(null);
    const token = localStorage.getItem("access_token") ?? "";
    const es = new EventSource(
      `/api/v1/minions/blueprint/runs/${runId}/troubleshoot?token=${encodeURIComponent(token)}`,
    );

    es.onmessage = (e) => {
      const ev = JSON.parse(e.data) as AgentEvent;
      if (ev.type === "result") {
        // Loop may emit draft results; keep the latest as the answer.
        if (ev.message) setAnswer(ev.message);
      } else if (ev.type === "error") {
        setError(ev.message ?? "Troubleshooter failed");
        es.close();
        setDone(true);
      } else if (STEP_TYPES.has(ev.type)) {
        setSteps((prev) => [...prev, ev]);
      }
      endRef.current?.scrollIntoView({ block: "nearest" });
    };
    // Stream close = loop finished (no explicit "completed" event on this loop).
    es.onerror = () => {
      es.close();
      setDone(true);
    };
    return () => es.close();
  }, [runId]);

  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xs text-muted-foreground uppercase tracking-wider flex items-center gap-2">
          {!done ? <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" /> : <CheckCircle className="w-3.5 h-3.5 text-emerald-500" />}
          AI Troubleshooter
        </h2>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground" title="Close">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Steps */}
      <div className="space-y-1.5 max-h-64 overflow-auto mb-3">
        {steps.length === 0 && !answer && !error && (
          <p className="text-sm text-muted-foreground animate-pulse">Investigating the failure…</p>
        )}
        {steps.map((s, i) => (
          <div key={i} className="flex items-start gap-2 text-xs">
            <StepIcon type={s.type} message={s.message} />
            <span className="text-foreground/80 break-words">{s.message}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>

      {error && (
        <div className="text-sm text-red-400 border border-red-800 bg-red-500/10 rounded-lg p-3">{error}</div>
      )}

      {/* Root cause & fix */}
      {answer && (
        <div>
          <h3 className="text-xs text-muted-foreground uppercase tracking-wider mb-1.5">Root cause &amp; fix</h3>
          <div className="text-sm text-foreground bg-muted/40 border border-border rounded-lg p-3 leading-relaxed whitespace-pre-wrap break-words">
            {answer}
          </div>
        </div>
      )}
    </div>
  );
}
