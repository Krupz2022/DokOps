export interface TopoNode {
  id: string;
  kind: "Node" | "Namespace" | "Service" | "Pod";
  name: string;
  namespace?: string;
  health: "healthy" | "warning" | "critical" | "unknown";
  cpu?: number;
  memory?: number;
  // react-force-graph adds these at runtime
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

export interface TopoEdge {
  source: string;
  target: string;
  kind: "hosts" | "routes" | "owns";
}

export interface TopologySnapshot {
  nodes: TopoNode[];
  edges: TopoEdge[];
  version: number;
  mock: boolean;
}

export interface NodeDetail {
  id: string;
  kind: string;
  name: string;
  namespace?: string;
  health: string;
  events: string;
  details: string;
  restart_count: number;
  mock: boolean;
}

export type ViewMode = "physical" | "logical";

export const HEALTH_COLOR: Record<string, string> = {
  healthy: "#22c55e",
  warning: "#f59e0b",
  critical: "#ef4444",
  unknown: "#6b7280",
};

export const NODE_RADIUS: Record<string, number> = {
  Node: 14,
  Namespace: 12,
  Service: 10,
  Pod: 7,
};

export const NODE_BADGE: Record<string, string> = {
  Node: "N",
  Namespace: "NS",
  Service: "S",
  Pod: "P",
};
