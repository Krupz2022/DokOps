import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { TopologyGraph } from "../components/topology/TopologyGraph";
import { TopologyControls } from "../components/topology/TopologyControls";
import { TopologyDrawer } from "../components/topology/TopologyDrawer";
import { TopologyVitals } from "../components/topology/TopologyVitals";
import { TopologyLegend } from "../components/topology/TopologyLegend";
import type { TopoNode, TopologySnapshot, ViewMode } from "../lib/topology";
import { useChatContext } from "../context/ChatContext";

const EMPTY_SNAPSHOT: TopologySnapshot = { nodes: [], edges: [], version: 0, mock: false };

// Reuse previous node objects by id so react-force-graph keeps their settled
// x/y/fx/fy positions instead of re-running physics from scratch each SSE tick.
export function mergeSnapshot(prev: TopologySnapshot, incoming: TopologySnapshot): TopologySnapshot {
  const prevById = new Map(prev.nodes.map((n) => [n.id, n]));
  const nodes = incoming.nodes.map((n) => {
    const existing = prevById.get(n.id) as any;
    if (!existing) return n; // new node — let the engine place it
    // Mutate existing object in place: update data fields, keep position fields.
    const { x, y, vx, vy, fx, fy } = existing;
    return Object.assign(existing, n, { x, y, vx, vy, fx, fy });
  });
  return { ...incoming, nodes };
}

export default function Topology() {
  const { startNewChat, setPanelOpen, sendMessage } = useChatContext();
  const navigate = useNavigate();
  // Cluster context is stored in localStorage by ClusterContextSelector
  const clusterContext = localStorage.getItem("clusterContext") || undefined;

  const [snapshot, setSnapshot] = useState<TopologySnapshot>(EMPTY_SNAPSHOT);
  const [connected, setConnected] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("physical");
  const [selectedNode, setSelectedNode] = useState<TopoNode | null>(null);
  const [visibleNamespaces, setVisibleNamespaces] = useState<Set<string>>(new Set());
  const [connectionError, setConnectionError] = useState(false);

  const esRef = useRef<EventSource | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryDelay = useRef(2000);

  const connect = useCallback(() => {
    if (esRef.current) esRef.current.close();

    const token = localStorage.getItem("access_token");
    if (!token) {
      navigate("/login");
      return;
    }

    const params = new URLSearchParams({ token });
    if (clusterContext) params.set("cluster_context", clusterContext);

    const apiBase = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";
    const es = new EventSource(`${apiBase}/topology/stream?${params}`);
    esRef.current = es;

    es.onopen = () => {
      setConnected(true);
      setConnectionError(false);
      retryDelay.current = 2000;
    };

    es.onmessage = (event) => {
      const data: TopologySnapshot = JSON.parse(event.data);
      setSnapshot((prev) => mergeSnapshot(prev, data));
      // Initialise all namespaces as visible on first load
      setVisibleNamespaces((prev) => {
        if (prev.size > 0) return prev;
        const ns = new Set(data.nodes.filter((n) => n.kind === "Namespace").map((n) => n.name));
        return ns.size > 0 ? ns : prev;
      });
    };

    es.onerror = () => {
      setConnected(false);
      setConnectionError(true);
      es.close();
      retryRef.current = setTimeout(() => {
        retryDelay.current = Math.min(retryDelay.current * 2, 30000);
        connect();
      }, retryDelay.current);
    };
  }, [clusterContext, navigate]);

  useEffect(() => {
    connect();
    return () => {
      esRef.current?.close();
      if (retryRef.current) clearTimeout(retryRef.current);
    };
  }, [connect]);

  // Listen for view-logs event from drawer
  useEffect(() => {
    const handler = (e: Event) => {
      const { namespace, pod } = (e as CustomEvent).detail;
      navigate(`/resources?namespace=${namespace}&pod=${pod}&tab=logs`);
    };
    window.addEventListener("topology:view-logs", handler);
    return () => window.removeEventListener("topology:view-logs", handler);
  }, [navigate]);

  const namespaceList = snapshot.nodes.filter((n) => n.kind === "Namespace").map((n) => n.name);

  const handleAskAI = async (prompt: string) => {
    const convId = await startNewChat();
    setPanelOpen(true);
    await sendMessage(prompt, convId);
  };

  return (
    <div className="relative flex-1 w-full overflow-hidden" style={{ background: "rgb(3,7,18)" }}>
      {/* Connection lost banner */}
      {connectionError && (
        <div className="absolute top-0 left-0 right-0 z-20 bg-red-500/10 border-b border-red-500/30 px-4 py-2 text-xs text-red-400 font-mono text-center">
          Connection lost — reconnecting...
        </div>
      )}

      {/* Graph canvas */}
      <TopologyGraph
        snapshot={snapshot}
        viewMode={viewMode}
        visibleNamespaces={visibleNamespaces}
        focusedId={selectedNode?.id ?? null}
        onNodeClick={setSelectedNode}
      />

      {/* Cluster health triage (top-left) */}
      <TopologyVitals nodes={snapshot.nodes} onSelect={setSelectedNode} />

      {/* Legend (bottom-left) */}
      <TopologyLegend />

      {/* Controls overlay */}
      <TopologyControls
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        namespaces={namespaceList}
        visibleNamespaces={visibleNamespaces}
        onNamespacesChange={setVisibleNamespaces}
        connected={connected}
      />

      {/* Side drawer */}
      <TopologyDrawer
        node={selectedNode}
        clusterContext={clusterContext}
        onClose={() => setSelectedNode(null)}
        onAskAI={handleAskAI}
      />
    </div>
  );
}
