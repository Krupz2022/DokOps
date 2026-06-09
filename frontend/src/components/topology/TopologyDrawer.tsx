import { useEffect, useState } from "react";
import { X, Terminal, MessageSquare, AlertCircle } from "lucide-react";
import { cn } from "../../lib/utils";
import type { TopoNode, NodeDetail } from "../../lib/topology";
import { HEALTH_COLOR } from "../../lib/topology";
import api from "../../lib/api";

interface Props {
  node: TopoNode | null;
  clusterContext?: string;
  onClose: () => void;
  onAskAI: (prompt: string) => void;
}

export function TopologyDrawer({ node, clusterContext, onClose, onAskAI }: Props) {
  const [detail, setDetail] = useState<NodeDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!node) return;
    fetchDetail();
  }, [node?.id]);

  const fetchDetail = async () => {
    if (!node) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (node.namespace) params.set("namespace", node.namespace);
      if (clusterContext) params.set("cluster_context", clusterContext);
      const res = await api.get(`/topology/node/${node.kind}/${node.name}?${params}`);
      setDetail(res.data as NodeDetail);
    } catch {
      setError("Failed to load details. Check connection.");
    } finally {
      setLoading(false);
    }
  };

  if (!node) return null;

  const color = HEALTH_COLOR[node.health] || HEALTH_COLOR.unknown;

  return (
    <div
      className={cn(
        "fixed right-0 top-0 h-full w-80 z-50 glass border-l border-border",
        "flex flex-col shadow-2xl transition-transform duration-300",
        node ? "translate-x-0" : "translate-x-full"
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-2.5 min-w-0">
          <div
            className="w-2.5 h-2.5 rounded-full flex-shrink-0"
            style={{ background: color, boxShadow: `0 0 8px ${color}` }}
          />
          <div className="min-w-0">
            <p className="text-sm font-medium text-foreground truncate">{node.name}</p>
            <p className="text-[10px] font-mono text-muted-foreground">{node.kind}{node.namespace ? ` · ${node.namespace}` : ""}</p>
          </div>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors flex-shrink-0">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {detail?.mock && (
          <div className="flex items-center gap-1.5 text-amber-400 text-xs font-mono px-2 py-1.5 rounded border border-amber-400/30 bg-amber-400/10">
            <AlertCircle className="w-3 h-3 flex-shrink-0" />
            Mock Mode — no live cluster
          </div>
        )}

        {/* Health */}
        <div>
          <p className="text-[10px] font-mono text-muted-foreground/50 uppercase tracking-widest mb-1">Health</p>
          <span
            className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-semibold capitalize"
            style={{ color, border: `1px solid ${color}40`, background: `${color}15` }}
          >
            {node.health}
          </span>
        </div>

        {/* Loading skeleton */}
        {loading && (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-4 rounded bg-secondary/40 animate-pulse" />
            ))}
          </div>
        )}

        {error && (
          <div className="text-xs text-red-400 flex items-center gap-1.5">
            <AlertCircle className="w-3 h-3" />
            {error}
            <button onClick={fetchDetail} className="underline hover:no-underline ml-1">
              Retry
            </button>
          </div>
        )}

        {detail && !loading && (
          <>
            {/* Details text */}
            <div>
              <p className="text-[10px] font-mono text-muted-foreground/50 uppercase tracking-widest mb-1">Details</p>
              <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap break-all bg-secondary/20 rounded p-2">
                {detail.details}
              </pre>
            </div>

            {/* Events */}
            {detail.events && (
              <div>
                <p className="text-[10px] font-mono text-muted-foreground/50 uppercase tracking-widest mb-1">Events</p>
                <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap break-all bg-secondary/20 rounded p-2 max-h-32 overflow-y-auto">
                  {detail.events}
                </pre>
              </div>
            )}

            {/* Restart count */}
            {node.kind === "Pod" && (
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground font-mono">Restarts</span>
                <span className={cn("font-mono font-semibold", detail.restart_count > 0 ? "text-amber-400" : "text-emerald-400")}>
                  {detail.restart_count}
                </span>
              </div>
            )}
          </>
        )}
      </div>

      {/* Actions */}
      <div className="flex-shrink-0 border-t border-border p-3 flex gap-2">
        {node.kind === "Pod" && (
          <button
            onClick={() => window.dispatchEvent(new CustomEvent("topology:view-logs", { detail: { namespace: node.namespace, pod: node.name } }))}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-xs border border-border text-muted-foreground hover:text-foreground hover:bg-secondary/40 transition-colors"
          >
            <Terminal className="w-3 h-3" />
            View Logs
          </button>
        )}
        <button
          onClick={() => onAskAI(`Diagnose ${node.kind.toLowerCase()} "${node.name}"${node.namespace ? ` in namespace "${node.namespace}"` : ""}`)}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-xs bg-primary/20 border border-primary/40 text-primary hover:bg-primary/30 transition-colors"
        >
          <MessageSquare className="w-3 h-3" />
          Ask AI
        </button>
      </div>
    </div>
  );
}
