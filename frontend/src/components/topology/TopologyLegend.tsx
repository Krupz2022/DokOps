import { useState } from "react";
import { Info, ChevronDown } from "lucide-react";
import { HEALTH_COLOR } from "../../lib/topology";

const KINDS = [
  { badge: "N", label: "Node" },
  { badge: "NS", label: "Namespace" },
  { badge: "S", label: "Service" },
  { badge: "P", label: "Pod" },
];

const HEALTH = [
  { key: "healthy", label: "Healthy" },
  { key: "warning", label: "Warning" },
  { key: "critical", label: "Critical" },
  { key: "unknown", label: "Unknown" },
];

export function TopologyLegend() {
  const [open, setOpen] = useState(false);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="absolute bottom-4 left-4 z-10 flex items-center gap-1.5 px-2.5 py-1.5 glass border border-border rounded-md text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <Info className="w-3 h-3" />
        <span className="font-mono">Legend</span>
      </button>
    );
  }

  return (
    <div className="absolute bottom-4 left-4 z-10 glass border border-border rounded-md p-3 w-44 text-xs">
      <div className="flex items-center justify-between mb-2.5">
        <span className="font-mono text-muted-foreground/60 uppercase tracking-widest text-[10px]">Legend</span>
        <button onClick={() => setOpen(false)} className="text-muted-foreground hover:text-foreground">
          <ChevronDown className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="space-y-1.5 mb-3">
        {KINDS.map((k) => (
          <div key={k.badge} className="flex items-center gap-2">
            <span className="inline-flex items-center justify-center w-5 h-5 rounded-full border border-border font-mono text-[9px] text-muted-foreground">
              {k.badge}
            </span>
            <span className="text-muted-foreground">{k.label}</span>
          </div>
        ))}
      </div>

      <div className="space-y-1.5 border-t border-border/50 pt-2.5">
        {HEALTH.map((h) => (
          <div key={h.key} className="flex items-center gap-2">
            <span
              className="w-2.5 h-2.5 rounded-full"
              style={{ background: HEALTH_COLOR[h.key], boxShadow: `0 0 5px ${HEALTH_COLOR[h.key]}` }}
            />
            <span className="text-muted-foreground">{h.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
