import { useRef, useCallback, useMemo, useEffect, useState } from "react";
// @ts-ignore
import ForceGraph2D from "react-force-graph-2d";
import type { TopoNode, TopoEdge, TopologySnapshot, ViewMode } from "../../lib/topology";
import { HEALTH_COLOR, NODE_RADIUS, NODE_BADGE } from "../../lib/topology";

interface Props {
  snapshot: TopologySnapshot;
  viewMode: ViewMode;
  visibleNamespaces: Set<string>;
  onNodeClick: (node: TopoNode) => void;
}

export function TopologyGraph({ snapshot, viewMode, visibleNamespaces, onNodeClick }: Props) {
  const fgRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setDimensions({ width, height });
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  const graphData = useMemo(() => {
    // Filter nodes by visible namespaces
    const filteredNodes = snapshot.nodes.filter((n) => {
      if (n.kind === "Node") return true;
      if (!n.namespace) return true;
      return visibleNamespaces.has(n.namespace);
    });

    const visibleIds = new Set(filteredNodes.map((n) => n.id));

    // Filter edges by view mode and visible nodes
    const filteredEdges = snapshot.edges.filter((e: TopoEdge) => {
      const srcId = typeof e.source === "object" ? (e.source as any).id : e.source;
      const tgtId = typeof e.target === "object" ? (e.target as any).id : e.target;
      if (!visibleIds.has(srcId) || !visibleIds.has(tgtId)) return false;
      if (viewMode === "physical") return e.kind === "hosts";
      if (viewMode === "logical") return e.kind === "owns" || e.kind === "routes";
      return true;
    });

    return { nodes: filteredNodes, links: filteredEdges };
  }, [snapshot, viewMode, visibleNamespaces]);

  const drawNode = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const n = node as TopoNode & { x: number; y: number };
      const r = NODE_RADIUS[n.kind] / Math.max(globalScale, 1);
      const color = HEALTH_COLOR[n.health] || HEALTH_COLOR["unknown"];

      // Pulsing glow for critical nodes
      let glowSize = 12;
      if (n.health === "critical") {
        glowSize = 12 + Math.sin(Date.now() / 400) * 8;
      }

      // Glow ring
      ctx.shadowColor = color;
      ctx.shadowBlur = glowSize;

      // Glassmorphism fill
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = color + "1a"; // ~10% opacity
      ctx.fill();

      // Border
      ctx.strokeStyle = color + "99"; // ~60% opacity
      ctx.lineWidth = 1.2 / globalScale;
      ctx.stroke();

      ctx.shadowBlur = 0;

      // Badge letter
      const badge = NODE_BADGE[n.kind] || "?";
      const fontSize = Math.max(r * 0.65, 3);
      ctx.font = `bold ${fontSize}px monospace`;
      ctx.fillStyle = color;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(badge, n.x, n.y);

      // Persistent name label below the node
      const labelSize = Math.max(3.5 / globalScale, 2);
      ctx.font = `${labelSize}px sans-serif`;
      ctx.fillStyle = "rgba(200,210,220,0.75)";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      const label = n.name.length > 20 ? n.name.slice(0, 18) + "…" : n.name;
      ctx.fillText(label, n.x, n.y + r + 2 / globalScale);
    },
    []
  );

  const drawLink = useCallback((link: any, ctx: CanvasRenderingContext2D) => {
    const src = link.source as { x: number; y: number };
    const tgt = link.target as { x: number; y: number };
    if (!src?.x || !tgt?.x) return;

    ctx.beginPath();
    ctx.moveTo(src.x, src.y);
    ctx.lineTo(tgt.x, tgt.y);
    ctx.strokeStyle =
      link.kind === "hosts"
        ? "rgba(59,130,246,0.25)"
        : link.kind === "routes"
        ? "rgba(34,197,94,0.2)"
        : "rgba(255,255,255,0.1)";
    ctx.lineWidth = 0.8;
    ctx.stroke();
  }, []);

  return (
    <div ref={containerRef} className="w-full h-full">
      <ForceGraph2D
        ref={fgRef}
        graphData={graphData}
        width={dimensions.width}
        height={dimensions.height}
        nodeId="id"
        nodeCanvasObject={drawNode}
        nodeCanvasObjectMode={() => "replace"}
        linkCanvasObject={drawLink}
        linkCanvasObjectMode={() => "replace"}
        onNodeClick={(node: any) => onNodeClick(node as TopoNode)}
        nodeLabel={(node: any) => `${(node as TopoNode).kind}: ${(node as TopoNode).name}`}
        backgroundColor="rgb(3,7,18)"
        linkDirectionalParticles={2}
        linkDirectionalParticleSpeed={0.003}
        linkDirectionalParticleWidth={1.5}
        warmupTicks={100}
        cooldownTicks={200}
      />
    </div>
  );
}
