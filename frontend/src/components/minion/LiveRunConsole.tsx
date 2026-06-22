import { useEffect, useRef, useState } from "react";
import type { BlueprintEvent } from "../../types/blueprint";
import { resultChip } from "../../lib/blueprintView";

interface ResourceLive {
  id: string;
  status: "running" | "done";
  result: boolean | null;
  comment: string;
  lines: string[];
}

const TONE: Record<"amber" | "green" | "red", string> = {
  amber: "bg-amber-500/20 text-amber-400 border-amber-800",
  green: "bg-green-500/20 text-green-400 border-green-800",
  red: "bg-red-500/20 text-red-400 border-red-800",
};

export default function LiveRunConsole({ runId, onDone }: { runId: string; onDone: () => void }) {
  const [resources, setResources] = useState<ResourceLive[]>([]);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setResources([]);
    setError(null);
    const token = localStorage.getItem("access_token") ?? "";
    const es = new EventSource(`/api/v1/minions/blueprint/runs/${runId}/stream?token=${encodeURIComponent(token)}`);

    es.onmessage = (e) => {
      const ev = JSON.parse(e.data) as BlueprintEvent;
      setResources((prev) => {
        const next = [...prev];
        const idx = (id: string) => next.findIndex((r) => r.id === id);
        if (ev.kind === "resource_start") {
          if (idx(ev.id) === -1) next.push({ id: ev.id, status: "running", result: null, comment: "", lines: [] });
        } else if (ev.kind === "log") {
          const i = idx(ev.id);
          if (i >= 0) next[i] = { ...next[i], lines: [...next[i].lines, ev.line] };
        } else if (ev.kind === "resource_result") {
          const i = idx(ev.id);
          const patch = { status: "done" as const, result: ev.result, comment: ev.comment };
          if (i >= 0) next[i] = { ...next[i], ...patch };
          else next.push({ id: ev.id, lines: [], ...patch });
        }
        return next;
      });
      if (ev.kind === "done") { es.close(); onDone(); }
      if (ev.kind === "error") { setError(ev.message); es.close(); }
      endRef.current?.scrollIntoView({ block: "nearest" });
    };
    es.onerror = () => {
      // Transient drop: let EventSource auto-reconnect (the backend replays the buffer).
      // Only give up if the browser already closed the stream (fatal).
      if (es.readyState === EventSource.CLOSED) es.close();
    };
    return () => es.close();
  }, [runId, onDone]);

  return (
    <div className="space-y-2">
      {error && <div className="text-sm text-red-400">Run error: {error}</div>}
      {resources.length === 0 && !error && (
        <p className="text-sm text-muted-foreground">Starting run…</p>
      )}
      {resources.map((r) => {
        const chip = r.status === "running"
          ? { label: "running", tone: "amber" as const }
          : resultChip(r.result, {});
        return (
          <div key={r.id} className="border border-border rounded-lg overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-1.5 bg-card">
              <span className="font-mono text-xs text-foreground">{r.id}</span>
              <span className={`text-xs px-1.5 py-0.5 rounded border ${TONE[chip.tone]}`}>{chip.label}</span>
              {r.comment && <span className="text-xs text-muted-foreground truncate">{r.comment}</span>}
            </div>
            {r.lines.length > 0 && (
              <pre className="bg-background px-3 py-2 font-mono text-[11px] text-foreground whitespace-pre-wrap break-all max-h-64 overflow-auto">{r.lines.join("\n")}</pre>
            )}
          </div>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}
