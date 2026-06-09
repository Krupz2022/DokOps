import { useEffect, useRef, useState } from "react";
import { CheckCircle, Clock, Loader, XCircle, ArrowLeft } from "lucide-react";
import type { StepResult, WorkflowSSEEvent } from "../../types/workflow";
import { workflowApi } from "../../lib/api";

interface Props {
  runId: number;
  onBack: () => void;
}

type RunStatus = "running" | "completed" | "failed";

const STATUS_ICON: Record<StepResult["status"], React.ReactNode> = {
  pending: <Clock size={16} className="text-muted-foreground" />,
  running: <Loader size={16} className="text-blue-500 animate-spin" />,
  passed:  <CheckCircle size={16} className="text-emerald-500" />,
  failed:  <XCircle size={16} className="text-destructive" />,
  skipped: <Clock size={16} className="text-muted-foreground" />,
};

const STATUS_BADGE: Record<RunStatus, string> = {
  running:   "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/30",
  completed: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/30",
  failed:    "bg-destructive/10 text-destructive border-destructive/30",
};

export function WorkflowExecutionView({ runId, onBack }: Props) {
  const [stepResults, setStepResults] = useState<StepResult[]>([]);
  const [messages, setMessages] = useState<string[]>([]);
  const [status, setStatus] = useState<RunStatus>("running");
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Load initial step results from the run snapshot
  useEffect(() => {
    workflowApi.getRun(runId).then((res) => {
      setStepResults(res.data.step_results);
      if (res.data.status === "completed" || res.data.status === "failed") {
        setStatus(res.data.status as RunStatus);
      }
      if (res.data.ai_summary) {
        setAiSummary(res.data.ai_summary);
      }
    }).catch(console.error);
  }, [runId]);

  // Auto-scroll messages to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // SSE connection via fetch + ReadableStream (supports Authorization header)
  useEffect(() => {
    const token = localStorage.getItem("access_token");
    const url = workflowApi.streamUrl(runId);
    let cancelled = false;

    const connect = async () => {
      const resp = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const reader = resp.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (!cancelled) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const event: WorkflowSSEEvent = JSON.parse(line.slice(6));
              handleEvent(event);
            } catch {
              // ignore malformed JSON
            }
          }
        }
      }
    };

    connect().catch(console.error);
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const handleEvent = (event: WorkflowSSEEvent) => {
    if (event.type === "step_update" && event.step_id && event.status) {
      setStepResults((prev) =>
        prev.map((sr) =>
          sr.step_id === event.step_id
            ? { ...sr, status: event.status as StepResult["status"] }
            : sr
        )
      );
    }

    if ((event.type === "step" || event.type === "result") && event.message) {
      setMessages((prev) => [...prev, event.message!]);
    }

    if (event.type === "completed") {
      setStatus(event.error ? "failed" : "completed");
      if (event.message) {
        setMessages((prev) => [...prev, event.message!]);
      }
      // Re-fetch final step states — SSE step_update for the last step can
      // arrive after or be lost before the completed event closes the stream.
      workflowApi.getRun(runId).then((res) => {
        setStepResults(res.data.step_results);
      }).catch(() => {});
    }

    if (event.type === "error" && event.error) {
      setStatus("failed");
      setMessages((prev) => [...prev, `Error: ${event.error}`]);
    }
  };

  return (
    <div className="flex flex-col h-full gap-4">
      {/* Top bar */}
      <div className="flex items-center justify-between">
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-muted-foreground hover:text-foreground text-sm transition-colors"
        >
          <ArrowLeft size={16} />
          Back
        </button>
        <div className="flex items-center gap-3">
          <span className="text-muted-foreground text-sm">Run #{runId}</span>
          <span
            className={`px-3 py-1 rounded-full text-xs font-medium border capitalize ${STATUS_BADGE[status]}`}
          >
            {status}
          </span>
        </div>
      </div>

      {/* Two-panel body */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[1fr_1fr] gap-4 min-h-0">
        {/* Left: Steps */}
        <div className="bg-card border border-border rounded-xl p-4 flex flex-col min-h-0">
          <h3 className="text-foreground text-sm font-semibold mb-3">Steps</h3>
          <div className="overflow-y-auto space-y-2 flex-1">
            {stepResults.length === 0 && (
              <p className="text-muted-foreground text-xs">Waiting for steps…</p>
            )}
            {stepResults.map((sr) => (
              <div
                key={sr.step_id}
                className="flex items-start gap-3 bg-background border border-border rounded-lg px-3 py-2"
              >
                <span className="mt-0.5 shrink-0">{STATUS_ICON[sr.status]}</span>
                <div className="flex-1 min-w-0">
                  <div className="text-foreground text-xs font-medium truncate">{sr.step_name}</div>
                  {sr.status === "failed" && sr.error && (
                    <div className="text-destructive text-xs mt-0.5 break-words">{sr.error}</div>
                  )}
                </div>
                <span className="text-muted-foreground text-xs capitalize shrink-0">{sr.status}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: AI Narration */}
        <div className="bg-card border border-border rounded-xl p-4 flex flex-col min-h-0">
          <h3 className="text-foreground text-sm font-semibold mb-3">AI Narration</h3>
          <div className="overflow-y-auto flex-1 space-y-2">
            {messages.length === 0 && !aiSummary && (
              <p className="text-muted-foreground text-xs">Waiting for narration…</p>
            )}
            {messages.length === 0 && aiSummary && (
              <div className="text-foreground/80 text-xs bg-muted/40 border border-border rounded-lg px-3 py-2 leading-relaxed whitespace-pre-wrap">
                {aiSummary}
              </div>
            )}
            {messages.map((msg, i) => (
              <div
                key={i}
                className="text-foreground/80 text-xs bg-muted/40 border border-border rounded-lg px-3 py-2 leading-relaxed"
              >
                {msg}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>
      </div>
    </div>
  );
}
