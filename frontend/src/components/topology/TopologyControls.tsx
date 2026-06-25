import { useState } from "react";
import { Filter, Radio } from "lucide-react";
import { cn } from "../../lib/utils";
import type { ViewMode } from "../../lib/topology";

interface Props {
  viewMode: ViewMode;
  onViewModeChange: (mode: ViewMode) => void;
  namespaces: string[];
  visibleNamespaces: Set<string>;
  onNamespacesChange: (ns: Set<string>) => void;
  connected: boolean;
}

export function TopologyControls({
  viewMode,
  onViewModeChange,
  namespaces,
  visibleNamespaces,
  onNamespacesChange,
  connected,
}: Props) {
  const [filterOpen, setFilterOpen] = useState(false);

  const toggleNamespace = (ns: string) => {
    const next = new Set(visibleNamespaces);
    if (next.has(ns)) {
      next.delete(ns);
    } else {
      next.add(ns);
    }
    onNamespacesChange(next);
  };

  const allSelected = namespaces.length > 0 && visibleNamespaces.size === namespaces.length;
  const noneSelected = visibleNamespaces.size === 0;
  const toggleAll = () =>
    onNamespacesChange(allSelected ? new Set() : new Set(namespaces));

  return (
    <div className="absolute top-4 right-4 z-10 flex items-center gap-2">
      {/* Live indicator */}
      <div className="flex items-center gap-1.5 px-2.5 py-1.5 glass border border-border rounded-md text-xs">
        <Radio className="w-3 h-3" />
        <span
          className={cn(
            "w-1.5 h-1.5 rounded-full",
            connected
              ? "bg-emerald-400 shadow-[0_0_6px_#4ade80] animate-pulse"
              : "bg-red-400"
          )}
        />
        <span className="text-muted-foreground font-mono">
          {connected ? "LIVE" : "OFFLINE"}
        </span>
      </div>

      {/* View toggle */}
      <div className="flex glass border border-border rounded-md overflow-hidden text-xs font-mono">
        {(["physical", "logical"] as ViewMode[]).map((mode) => (
          <button
            key={mode}
            onClick={() => onViewModeChange(mode)}
            className={cn(
              "px-3 py-1.5 capitalize transition-colors",
              viewMode === mode
                ? "bg-primary/20 text-primary border-r border-border last:border-r-0"
                : "text-muted-foreground hover:text-foreground border-r border-border last:border-r-0"
            )}
          >
            {mode}
          </button>
        ))}
      </div>

      {/* Namespace filter */}
      <div className="relative">
        <button
          onClick={() => setFilterOpen((o) => !o)}
          className="flex items-center gap-1.5 px-2.5 py-1.5 glass border border-border rounded-md text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <Filter className="w-3 h-3" />
          <span className="font-mono">NS ({visibleNamespaces.size}/{namespaces.length})</span>
        </button>

        {filterOpen && (
          <div className="absolute right-0 top-full mt-1.5 glass border border-border rounded-md shadow-lg p-2 min-w-[160px] z-20">
            <p className="text-[10px] font-mono text-muted-foreground/50 uppercase tracking-widest mb-1.5 px-1">
              Namespaces
            </p>
            <label className="flex items-center gap-2 px-1 py-1 cursor-pointer hover:bg-secondary/40 rounded text-xs border-b border-border/50 mb-1">
              <input
                type="checkbox"
                checked={allSelected}
                ref={(el) => {
                  if (el) el.indeterminate = !allSelected && !noneSelected;
                }}
                onChange={toggleAll}
                className="accent-primary"
              />
              <span className="font-mono text-muted-foreground">
                {allSelected ? "Deselect all" : "Select all"}
              </span>
            </label>
            {namespaces.map((ns) => (
              <label
                key={ns}
                className="flex items-center gap-2 px-1 py-1 cursor-pointer hover:bg-secondary/40 rounded text-xs"
              >
                <input
                  type="checkbox"
                  checked={visibleNamespaces.has(ns)}
                  onChange={() => toggleNamespace(ns)}
                  className="accent-primary"
                />
                <span className="font-mono text-foreground truncate">{ns}</span>
              </label>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
