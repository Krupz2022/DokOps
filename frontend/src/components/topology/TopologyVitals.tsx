import { useRef } from "react";
import type { TopoNode } from "../../lib/topology";
import { HEALTH_COLOR } from "../../lib/topology";

interface Props {
  nodes: TopoNode[];
  onSelect: (node: TopoNode) => void;
}

// Order matters: worst first, so the eye lands on trouble.
const SEVERITIES = [
  { key: "critical", label: "CRITICAL", jump: true },
  { key: "warning", label: "WARN", jump: true },
  { key: "healthy", label: "OK", jump: false },
] as const;

export function TopologyVitals({ nodes, onSelect }: Props) {
  // Remember where we are in each severity's cycle so repeated clicks walk
  // through every affected resource rather than re-selecting the first.
  const cycleRef = useRef(new Map<string, number>());

  const counts: Record<string, number> = {};
  for (const n of nodes) counts[n.health] = (counts[n.health] ?? 0) + 1;

  const jumpTo = (health: string) => {
    const matches = nodes.filter((n) => n.health === health);
    if (matches.length === 0) return;
    const next = (cycleRef.current.get(health) ?? -1) + 1;
    cycleRef.current.set(health, next);
    onSelect(matches[next % matches.length]);
  };

  return (
    <div className="absolute top-4 left-4 z-10 flex items-center gap-3 px-3 py-1.5 glass border border-border rounded-md text-xs font-mono">
      {SEVERITIES.map(({ key, label, jump }) => {
        const count = counts[key] ?? 0;
        const color = HEALTH_COLOR[key];
        const active = count > 0;
        const clickable = active && jump;
        return (
          <button
            key={key}
            disabled={!clickable}
            onClick={() => jumpTo(key)}
            title={clickable ? `Jump to next ${label.toLowerCase()} resource` : undefined}
            className={
              clickable
                ? "flex items-center gap-1.5 hover:opacity-75 transition-opacity"
                : "flex items-center gap-1.5 cursor-default"
            }
          >
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ background: color, boxShadow: active ? `0 0 6px ${color}` : "none" }}
            />
            <span style={active ? { color } : undefined} className={active ? "" : "text-muted-foreground/40"}>
              {count} {label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
