import { useRef, useCallback, useMemo, useEffect, useState } from "react";
// @ts-ignore
import ForceGraph2D from "react-force-graph-2d";
// @ts-ignore
import { forceCollide } from "d3-force-3d";
import type { TopoNode, TopoEdge, TopologySnapshot, ViewMode } from "../../lib/topology";
import { HEALTH_COLOR, NODE_RADIUS, NODE_BADGE } from "../../lib/topology";

interface Props {
  snapshot: TopologySnapshot;
  viewMode: ViewMode;
  visibleNamespaces: Set<string>;
  focusedId: string | null;
  onNodeClick: (node: TopoNode) => void;
}

// ponytail: zoom thresholds for level-of-detail. Below BADGE_SCALE only the dot
// draws; labels appear past LABEL_SCALE. Tuned by eye — bump if text feels late.
const BADGE_SCALE = 0.8;
const LABEL_SCALE = 1.6;
const POD_LABEL_SCALE = 4; // pods are dense — only name them when zoomed into a region

export function TopologyGraph({ snapshot, viewMode, visibleNamespaces, focusedId, onNodeClick }: Props) {
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

  // Keep rings from overlapping in the radial DAG layout. Registered once;
  // d3Force registration persists across graphData updates.
  useEffect(() => {
    fgRef.current?.d3Force(
      "collision",
      forceCollide((n: any) => (NODE_RADIUS[n.kind] ?? 6) + 4)
    );
  }, []);

  const graphData = useMemo(() => {
    // Each view shows only the kinds that form a connected hierarchy for it, so the
    // radial DAG produces rings instead of a blob of orphaned (edgeless) nodes.
    // physical: Node hosts Pod. logical: Namespace owns Service routes Pod.
    const kindsForView =
      viewMode === "physical"
        ? new Set(["Node", "Pod"])
        : new Set(["Namespace", "Service", "Pod"]);

    const filteredNodes = snapshot.nodes.filter((n) => {
      if (!kindsForView.has(n.kind)) return false;
      if (n.kind === "Node") return true;
      if (!n.namespace) return true;
      return visibleNamespaces.has(n.namespace);
    });

    const visibleIds = new Set(filteredNodes.map((n) => n.id));

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

  // Blast radius: focused node + its direct neighbours, and the links between them.
  // null = nothing focused (everything drawn at full strength).
  const { focusNodeIds, focusLinkSet } = useMemo(() => {
    if (!focusedId) return { focusNodeIds: null as Set<string> | null, focusLinkSet: null as Set<any> | null };
    const ids = new Set<string>([focusedId]);
    const links = new Set<any>();
    for (const l of graphData.links as any[]) {
      const s = typeof l.source === "object" ? l.source.id : l.source;
      const t = typeof l.target === "object" ? l.target.id : l.target;
      if (s === focusedId || t === focusedId) {
        ids.add(s);
        ids.add(t);
        links.add(l);
      }
    }
    return { focusNodeIds: ids, focusLinkSet: links };
  }, [focusedId, graphData]);

  const drawNode = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const n = node as TopoNode & { x: number; y: number };
      const r = NODE_RADIUS[n.kind] ?? 6;
      const color = HEALTH_COLOR[n.health] || HEALTH_COLOR["unknown"];
      const critical = n.health === "critical";

      // Outside the blast radius: render as a faint ghost so the focused
      // neighbourhood reads clearly. No badge, no label.
      if (focusNodeIds && !focusNodeIds.has(n.id)) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
        ctx.fillStyle = "rgba(148,163,184,0.05)";
        ctx.fill();
        ctx.lineWidth = 1 / globalScale;
        ctx.strokeStyle = "rgba(148,163,184,0.18)";
        ctx.stroke();
        return;
      }

      // Solid translucent fill
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = color + "33"; // ~20% opacity
      ctx.fill();

      // Ring — brighter/thicker for critical, no per-frame animation (no shadowBlur)
      ctx.lineWidth = (critical ? 2.4 : 1.3) / globalScale;
      ctx.strokeStyle = color + (critical ? "ff" : "aa");
      ctx.stroke();

      // Badge letter (LOD-gated)
      if (globalScale > BADGE_SCALE) {
        const badge = NODE_BADGE[n.kind] || "?";
        ctx.font = `bold ${r * 0.85}px monospace`;
        ctx.fillStyle = color;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(badge, n.x, n.y);
      }

      // Name label (LOD-gated). Pods are numerous with long names, so they only
      // label when zoomed well in — keeps the overview readable instead of a wall
      // of overlapping text. Node/Namespace/Service (few) label earlier.
      const labelScale = n.kind === "Pod" ? POD_LABEL_SCALE : LABEL_SCALE;
      if (globalScale > labelScale) {
        const label = n.name.length > 22 ? n.name.slice(0, 20) + "…" : n.name;
        ctx.font = `${r * 0.5}px sans-serif`;
        ctx.fillStyle = "rgba(200,210,220,0.8)";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillText(label, n.x, n.y + r + 2 / globalScale);
      }
    },
    [focusNodeIds]
  );

  const drawPointerArea = useCallback(
    (node: any, color: string, ctx: CanvasRenderingContext2D) => {
      const n = node as TopoNode & { x: number; y: number };
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(n.x, n.y, NODE_RADIUS[n.kind] ?? 6, 0, 2 * Math.PI);
      ctx.fill();
    },
    []
  );

  // Re-fit the viewport once after each (re)layout settles.
  const didFitRef = useRef(false);

  // Fly the camera to the focused node and force a repaint of the dim/highlight
  // change. Nodes are pinned (fx/fy) so reheating doesn't move anything.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    if (focusedId) {
      const n = graphData.nodes.find((x: any) => x.id === focusedId) as any;
      if (n?.x != null) fg.centerAt(n.x, n.y, 600);
    }
    fg.d3ReheatSimulation?.();
  }, [focusedId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Switching view changes the visible hierarchy entirely — unpin everything and
  // reheat so the new layout forms instead of freezing at the old positions.
  useEffect(() => {
    for (const n of snapshot.nodes as any[]) {
      n.fx = undefined;
      n.fy = undefined;
    }
    didFitRef.current = false;
    fgRef.current?.d3ReheatSimulation?.();
  }, [viewMode]); // eslint-disable-line react-hooks/exhaustive-deps

  // Pin nodes once the layout settles so later SSE merges don't disturb them.
  // New nodes (fx unset) still settle in, then get pinned on the next stop.
  const handleEngineStop = useCallback(() => {
    for (const n of graphData.nodes as any[]) {
      if (n.fx == null && n.x != null) {
        n.fx = n.x;
        n.fy = n.y;
      }
    }
    if (!didFitRef.current) {
      fgRef.current?.zoomToFit(400, 60);
      didFitRef.current = true;
    }
  }, [graphData]);

  // One-shot particle pulse along a node's links on hover (no always-on particles)
  const handleNodeHover = useCallback(
    (node: any) => {
      if (!node || !fgRef.current) return;
      for (const l of graphData.links as any[]) {
        const s = typeof l.source === "object" ? l.source.id : l.source;
        const t = typeof l.target === "object" ? l.target.id : l.target;
        if (s === node.id || t === node.id) fgRef.current.emitParticle(l);
      }
    },
    [graphData]
  );

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
        nodePointerAreaPaint={drawPointerArea}
        onNodeClick={(node: any) => onNodeClick(node as TopoNode)}
        onNodeHover={handleNodeHover}
        nodeLabel={(node: any) => `${(node as TopoNode).kind}: ${(node as TopoNode).name}`}
        linkColor={(l: any) => {
          if (focusLinkSet && !focusLinkSet.has(l)) return "rgba(148,163,184,0.05)";
          return l.kind === "hosts"
            ? "rgba(96,165,250,0.5)"
            : l.kind === "routes"
            ? "rgba(74,222,128,0.45)"
            : "rgba(148,163,184,0.4)";
        }}
        linkWidth={(l: any) => (focusLinkSet && focusLinkSet.has(l) ? 1.8 : 1.1)}
        linkDirectionalParticles={(l: any) => (focusLinkSet && focusLinkSet.has(l) ? 2 : 0)}
        linkDirectionalParticleWidth={1.8}
        linkDirectionalParticleSpeed={0.01}
        linkDirectionalParticleColor={() => "rgba(180,200,255,0.9)"}
        backgroundColor="rgb(3,7,18)"
        dagMode="radialout"
        dagLevelDistance={90}
        onDagError={() => undefined}
        warmupTicks={50}
        cooldownTicks={150}
        onEngineStop={handleEngineStop}
      />
    </div>
  );
}
