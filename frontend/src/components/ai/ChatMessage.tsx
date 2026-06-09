import React, { useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { AlertTriangle, Orbit, Terminal, Copy, Check, Cpu, RotateCcw } from "lucide-react";
import { cn } from "../../lib/utils";
import type { ChatMessageData } from "../../context/ChatContext";
import { useChatContext } from "../../context/ChatContext";
import { useAppContext } from "../../context/AppContext";

/* ── Code block with copy button ──────────────────────────── */
function CodeBlock({ children }: { children?: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  const preRef = useRef<HTMLPreElement>(null);

  // Extract language label from child <code className="language-yaml">
  let language = "";
  React.Children.forEach(children, (child) => {
    if (React.isValidElement(child)) {
      const cls = (child.props as { className?: string }).className ?? "";
      const m = cls.match(/language-(\w+)/);
      if (m) language = m[1];
    }
  });

  const handleCopy = async () => {
    const text = preRef.current?.textContent ?? "";
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };

  return (
    <div className="my-4 rounded-xl overflow-hidden border border-white/8 not-prose">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-[hsl(222_50%_3%)] border-b border-white/5">
        <span className="text-[10px] font-mono text-slate-500 uppercase tracking-widest select-none">
          {language || "code"}
        </span>
        <button
          onClick={handleCopy}
          className={cn(
            "flex items-center gap-1.5 text-[11px] font-mono px-2.5 py-1 rounded-md transition-all duration-150",
            copied
              ? "text-green-400 bg-green-400/10"
              : "text-slate-400 hover:text-slate-200 bg-white/5 hover:bg-white/10"
          )}
        >
          {copied
            ? <Check className="w-3 h-3" />
            : <Copy className="w-3 h-3" />}
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>

      {/* Code */}
      <pre
        ref={preRef}
        className="bg-[hsl(222_50%_3%)] px-5 py-4 text-[13px] font-mono leading-relaxed text-slate-200 overflow-x-auto m-0 rounded-none"
      >
        {children}
      </pre>
    </div>
  );
}

/* ── Message action buttons (copy + regenerate) ────────────── */
function MessageActions({
  content,
  isLast,
  onRegenerate,
}: {
  content: string;
  isLast?: boolean;
  onRegenerate?: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };

  return (
    <div className="flex items-center gap-0.5 mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
      <button
        onClick={handleCopy}
        title={copied ? "Copied!" : "Copy message"}
        className={cn(
          "w-6 h-6 flex items-center justify-center rounded-md transition-colors",
          copied
            ? "text-green-400"
            : "text-muted-foreground/50 hover:text-muted-foreground hover:bg-muted/60"
        )}
      >
        {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
      </button>
      {isLast && onRegenerate && (
        <button
          onClick={onRegenerate}
          title="Regenerate response"
          className="w-6 h-6 flex items-center justify-center rounded-md text-muted-foreground/50 hover:text-muted-foreground hover:bg-muted/60 transition-colors"
        >
          <RotateCcw className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}

interface ChatMessageProps {
  message: ChatMessageData;
  isLast?: boolean;
  onRegenerate?: () => void;
}

export function ChatMessage({ message, isLast, onRegenerate }: ChatMessageProps) {
  /* ── Compaction banner ─────────────────────────────────── */
  if (message.message_type === "compaction_banner") {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-primary/5 border border-primary/15 rounded-lg my-1 mx-auto max-w-sm">
        <span className="text-primary text-xs">◈</span>
        <span className="text-muted-foreground text-xs">{message.content}</span>
      </div>
    );
  }

  /* ── Model badge ───────────────────────────────────────── */
  if (message.message_type === "model") {
    return (
      <div className="flex items-center gap-1.5 px-1 py-0.5">
        <Cpu className="w-3 h-3 text-muted-foreground/40 flex-shrink-0" />
        <span className="text-[10px] font-mono text-muted-foreground/40">{message.content}</span>
      </div>
    );
  }

  /* ── Individual step fallback ──────────────────────────── */
  if (message.message_type === "step") {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 bg-muted/20 border border-border/50 rounded-md text-muted-foreground text-xs font-mono">
        <span className="text-muted-foreground/50">›</span>
        <span>{message.content}</span>
      </div>
    );
  }

  /* ── User message ──────────────────────────────────────── */
  if (message.role === "user") {
    return (
      <div className="flex justify-end fade-up">
        <div className={cn(
          "max-w-[72%] px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap",
          "rounded-2xl rounded-br-sm",
          "bg-primary text-primary-foreground",
          "dark:shadow-[0_0_18px_hsl(191_89%_55%_/_0.2),0_2px_8px_hsl(0_0%_0%_/_0.3)]"
        )}>
          {message.content}
        </div>
      </div>
    );
  }

  /* ── Assistant message ─────────────────────────────────── */
  return (
    <div className="group flex gap-3 items-start fade-up">
      {/* Avatar */}
      <div className={cn(
        "w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5",
        "bg-gradient-to-br from-cyan-400 to-sky-600",
        "shadow-sm shadow-cyan-500/20"
      )}>
        <Orbit className="w-3.5 h-3.5 text-white" strokeWidth={2} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 pt-0.5">
        {message.content === "" ? (
          /* Thinking dots */
          <div className="flex items-center gap-1 py-1">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce"
                style={{ animationDelay: `${i * 0.15}s`, animationDuration: "0.9s" }}
              />
            ))}
          </div>
        ) : message.message_type === "pending_op" ? (
          <PendingOpCard raw={message.content} />
        ) : (
          <>
            <div className={cn(
              "prose prose-sm dark:prose-invert max-w-none text-foreground",
              "[&_code:not(pre_code)]:bg-primary/10 [&_code:not(pre_code)]:text-primary",
              "[&_code:not(pre_code)]:px-1.5 [&_code:not(pre_code)]:py-0.5 [&_code:not(pre_code)]:rounded [&_code:not(pre_code)]:text-xs [&_code:not(pre_code)]:font-mono",
              "[&_p]:text-sm [&_p]:leading-relaxed [&_p]:mb-3 last:[&_p]:mb-0",
              "[&_ul]:text-sm [&_ol]:text-sm [&_li]:leading-relaxed",
              "[&_strong]:text-foreground [&_strong]:font-semibold",
              "[&_h1]:text-base [&_h2]:text-sm [&_h3]:text-sm",
              "[&_blockquote]:border-l-2 [&_blockquote]:border-primary/40 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground"
            )}>
              <ReactMarkdown components={{ pre: CodeBlock }}>
                {message.content}
              </ReactMarkdown>
            </div>
            <MessageActions
              content={message.content}
              isLast={isLast}
              onRegenerate={onRegenerate}
            />
          </>
        )}
      </div>
    </div>
  );
}

/* ── StepGroup — terminal-style agent trace ────────────────── */
export interface StepGroupProps {
  steps: ChatMessageData[];
  isActive: boolean;
}

export function StepGroup({ steps, isActive }: StepGroupProps) {
  const [open, setOpen] = React.useState(false);

  return (
    <div className="flex gap-3 items-start fade-up">
      {/* Avatar aligned with assistant messages */}
      <div className={cn(
        "w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5",
        "bg-gradient-to-br from-cyan-400 to-sky-600",
        "shadow-sm shadow-cyan-500/20"
      )}>
        <Terminal className="w-3.5 h-3.5 text-white" strokeWidth={2} />
      </div>

      <div className="flex-1 min-w-0">
        <button
          onClick={() => setOpen((v) => !v)}
          className={cn(
            "group w-full text-left flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl transition-all duration-150",
            "border border-border/60 bg-muted/30 hover:bg-muted/50",
            "dark:bg-[hsl(222_44%_6%_/_0.5)] dark:hover:bg-[hsl(222_44%_8%_/_0.6)]",
            isActive && "border-primary/20 dark:bg-primary/5"
          )}
        >
          {isActive ? (
            <span className="w-3.5 h-3.5 rounded-full border-2 border-primary/30 border-t-primary animate-spin flex-shrink-0" />
          ) : (
            <span className={cn(
              "text-[10px] transition-transform duration-150 flex-shrink-0 text-muted-foreground/60",
              open ? "rotate-90" : "rotate-0"
            )}>▶</span>
          )}
          <span className={cn(
            "text-xs font-medium font-mono",
            isActive ? "text-primary animate-pulse" : "text-muted-foreground"
          )}>
            {isActive ? "Agent working…" : `${steps.length} tool call${steps.length !== 1 ? "s" : ""}`}
          </span>
          {!isActive && (
            <span className="ml-auto text-[10px] text-muted-foreground/40 group-hover:text-muted-foreground/60 transition-colors">
              {open ? "collapse" : "expand"}
            </span>
          )}
        </button>

        {open && (
          <div className={cn(
            "mt-1.5 rounded-xl border border-border/50 overflow-hidden",
            "bg-[hsl(222_50%_3%_/_0.8)] dark:shadow-[inset_0_1px_0_hsl(0_0%_100%_/_0.03)]"
          )}>
            {steps.map((s, idx) => (
              <div
                key={s.id}
                className={cn(
                  "flex items-start gap-3 px-4 py-2.5 text-xs font-mono",
                  "text-muted-foreground/70 border-b border-border/30 last:border-0"
                )}
              >
                <span className="text-primary/40 flex-shrink-0 select-none mt-px">
                  {String(idx + 1).padStart(2, "0")}
                </span>
                <span className="leading-relaxed break-words">{s.content}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── PendingOpCard — unchanged logic, refined visuals ──────── */
function PendingOpCard({ raw }: { raw: string }) {
  let op: Record<string, unknown> = {};
  try { op = JSON.parse(raw); } catch {
    return <p className="text-sm text-muted-foreground">{raw}</p>;
  }

  const { sendMessage, activeConversationId } = useChatContext();
  const { godModeActive } = useAppContext();
  const isGodMode = godModeActive;
  const [status, setStatus] = React.useState<"pending" | "approved" | "rejected" | "loading">("pending");
  const [resultMsg, setResultMsg] = React.useState<string>("");

  const riskLevel = String(op.risk_level ?? "low").toUpperCase();
  const riskColor =
    riskLevel === "HIGH"   ? "text-red-300 bg-red-900/40 border-red-800/50" :
    riskLevel === "MEDIUM" ? "text-amber-300 bg-amber-900/40 border-amber-800/50" :
                             "text-green-300 bg-green-900/40 border-green-800/50";

  const toolInputs = (op.tool_inputs ?? {}) as Record<string, string>;
  const namespace = toolInputs.namespace || "";
  const toolName = String(op.tool_name ?? "");
  const rawResource = toolInputs.deployment_name || toolInputs.configmap_name || toolInputs.secret_name || toolInputs.name || toolInputs.node_name || toolInputs.namespace || toolInputs.pod_name || "";
  const healthCheckTarget = toolInputs.deployment_name ||
    toolInputs.configmap_name || toolInputs.secret_name || toolInputs.name ||
    toolInputs.node_name ||
    (toolInputs.pod_name ? toolInputs.pod_name.split("-").slice(0, -2).join("-") : "") ||
    toolInputs.namespace;

  const handleApprove = async () => {
    if (status !== "pending") return;
    setStatus("loading");
    const token = localStorage.getItem("access_token");
    try {
      const res = await fetch(
        `${import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1"}/operations/pending/${op.id}/approve`,
        { method: "POST", headers: { Authorization: `Bearer ${token}` } }
      );
      const data = await res.json();
      if (!res.ok) {
        // Backend rejected (e.g. God Mode not active) — show the reason, stay pending
        const errDetail = data?.detail ?? data?.result?.error ?? "Operation was blocked by the server.";
        setResultMsg(errDetail);
        setStatus("rejected");
        return;
      }
      const result = data.result;
      const msg = result?.data
        ? typeof result.data === "string" ? result.data : JSON.stringify(result.data)
        : result?.error ?? "Operation executed.";
      setResultMsg(msg);
      setStatus("approved");

      if (activeConversationId && toolName) {
        let followUp: string;
        if (toolName.startsWith("mcp__")) {
          followUp = `The MCP tool '${toolName}' was approved and executed. The result is:\n\n${msg}\n\nAll tools have been called. Please summarize this result clearly for the user.`;
        } else {
          const nsHint = namespace ? ` in namespace ${namespace}` : "";
          const followUpMap: Record<string, string> = {
            delete_deployment: `The deployment '${healthCheckTarget}'${nsHint} has been deleted successfully. Use search_pods to verify no pods remain and report the result.`,
            delete_namespace: `The namespace '${healthCheckTarget}' has been deleted successfully. Use get_cluster_health to verify it no longer exists and report the result.`,
            drain_node: `Node '${healthCheckTarget}' has been drained successfully. Use get_node_status to verify it is cordoned and report where evicted pods were rescheduled.`,
            cordon_node: `Node '${healthCheckTarget}' has been cordoned successfully. Use get_node_status to verify its schedulable status and report the result.`,
            restart_pod: `The pod has been restarted successfully. Use get_deployment_status for deployment '${healthCheckTarget}'${nsHint} to verify replicas are ready and report the result.`,
            rollback_deployment: `Deployment '${healthCheckTarget}'${nsHint} has been rolled back successfully. Use get_deployment_status to verify all replicas are running the previous version.`,
            patch_deployment_resources: `Resources for '${healthCheckTarget}'${nsHint} have been patched successfully. Use get_deployment_status to verify replicas are ready and report the result.`,
            scale_deployment: `Deployment '${healthCheckTarget}'${nsHint} has been scaled successfully. Use get_deployment_status to verify the new replica count and report the result.`,
            create_namespace: `Namespace '${healthCheckTarget}' has been created successfully. Now proceed with the original request and deploy the application into this namespace.`,
            deploy_application: `Application '${healthCheckTarget}'${nsHint} has been deployed successfully. Use get_deployment_status to verify replicas are ready and report the status.`,
            update_configmap: `ConfigMap '${healthCheckTarget}'${nsHint} has been updated successfully. Use get_configmap to verify the new values and report the result.`,
            patch_secret: `Secret '${healthCheckTarget}'${nsHint} has been patched successfully. Use get_secret_metadata (without revealing values) to verify it exists and report the result.`,
            patch_deployment_env: `Env var in deployment '${healthCheckTarget}'${nsHint} has been updated successfully. Use get_deployment_status to verify the rolling restart completed and report the result.`,
            apply_manifest: `The manifest has been applied to the cluster successfully. Use get_deployment_status or get_pod_status to verify the resources are running and report the result.`,
            uncordon_node: `Node '${healthCheckTarget}' has been uncordoned successfully. Use get_node_status to verify it is schedulable and report the result.`,
          };
          followUp = followUpMap[toolName] ?? `The ${toolName} operation on '${healthCheckTarget}'${nsHint} completed successfully. Use read-only tools to verify the result and report.`;
        }
        setTimeout(() => sendMessage(followUp), 2000);
      }
    } catch { setStatus("pending"); }
  };

  const handleReject = async () => {
    if (status !== "pending") return;
    setStatus("loading");
    const token = localStorage.getItem("access_token");
    try {
      await fetch(
        `${import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1"}/operations/pending/${op.id}/reject`,
        { method: "POST", headers: { Authorization: `Bearer ${token}` } }
      );
      setStatus("rejected");
    } catch { setStatus("pending"); }
  };

  return (
    <div className={cn(
      "rounded-xl border p-4 space-y-3",
      "bg-amber-950/20 border-amber-800/40",
      "dark:shadow-[0_0_20px_hsl(38_92%_50%_/_0.08)]"
    )}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-amber-400 font-semibold text-sm">Pending Operation</span>
          {toolName && (
            <span className="font-mono text-xs text-amber-300/60 bg-amber-900/30 px-2 py-0.5 rounded">
              {toolName}
            </span>
          )}
        </div>
        <span className={cn("text-xs px-2.5 py-0.5 rounded-full border font-mono font-medium", riskColor)}>
          {riskLevel}
        </span>
      </div>

      {rawResource && (
        <p className="text-xs text-amber-300/70 font-mono">
          {rawResource}{namespace ? <> · <span className="text-amber-300/50">{namespace}</span></> : ""}
        </p>
      )}

      <p className="text-sm text-amber-200/75 leading-relaxed">
        {String(op.confirmation_message ?? "")}
      </p>

      {status === "approved" ? (
        <div className="space-y-1 pt-1">
          <p className="text-xs text-green-400 font-medium flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-green-400 flex-shrink-0" />
            Approved — operation executed
          </p>
          {resultMsg && <p className="text-xs text-green-300/60 font-mono pl-3">{resultMsg}</p>}
        </div>
      ) : status === "rejected" ? (
        <div className="space-y-1 pt-1">
          <p className="text-xs text-red-400/80 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-red-400/60 flex-shrink-0" />
            Rejected — no action taken
          </p>
          {resultMsg && <p className="text-xs text-red-300/60 font-mono pl-3">{resultMsg}</p>}
        </div>
      ) : (
        <div className="space-y-2.5 pt-1">
          {!isGodMode && (
            <div className="flex items-center gap-1.5 text-xs text-amber-400/80 bg-amber-900/20 border border-amber-800/30 rounded-lg px-3 py-2">
              <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
              <span>God Mode is not enabled — approval is blocked. Enable it in the top bar first.</span>
            </div>
          )}
          <div className="flex gap-2">
            <button
              onClick={handleApprove}
              disabled={status === "loading" || !isGodMode}
              className={cn(
                "px-4 py-1.5 rounded-lg text-xs font-medium transition-all",
                "bg-green-700 hover:bg-green-600 text-white",
                "disabled:opacity-40 disabled:cursor-not-allowed",
                "dark:shadow-[0_0_10px_hsl(142_71%_45%_/_0.25)] dark:hover:shadow-[0_0_14px_hsl(142_71%_45%_/_0.35)]"
              )}
            >
              {status === "loading" ? "…" : "✓ Approve"}
            </button>
            <button
              onClick={handleReject}
              disabled={status === "loading"}
              className="px-4 py-1.5 rounded-lg text-xs text-muted-foreground bg-muted hover:bg-muted/80 disabled:opacity-40 transition-colors"
            >
              ✕ Reject
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
