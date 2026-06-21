import type { ResourceResult } from "../../types/blueprint";
import { resultChip, resultRowId, parseChanges } from "../../lib/blueprintView";

const TONE: Record<"amber" | "green" | "red", string> = {
  amber: "bg-amber-500/20 text-amber-400 border-amber-800",
  green: "bg-green-500/20 text-green-400 border-green-800",
  red: "bg-red-500/20 text-red-400 border-red-800",
};

function changeSummary(changes: Record<string, unknown> | string): string {
  const c = parseChanges(changes);
  if (Object.keys(c).length === 0) return "";
  if ("old" in c || "new" in c) return `${String(c.old ?? "—")} → ${String(c.new ?? "—")}`;
  return Object.entries(c)
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(", ");
}

export default function BlueprintResultTable({ results }: { results: ResourceResult[] }) {
  if (results.length === 0) {
    return <p className="text-sm text-muted-foreground py-4">No results.</p>;
  }
  return (
    <div className="space-y-1">
      {results.map((r) => {
        const chip = resultChip(r.result, r.changes);
        const summary = changeSummary(r.changes);
        return (
          <div key={resultRowId(r)} className="flex items-start gap-3 text-sm py-1.5 border-b border-border/50 last:border-0">
            <span className="font-mono text-foreground w-40 shrink-0 truncate">{resultRowId(r)}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded border shrink-0 ${TONE[chip.tone]}`}>{chip.label}</span>
            <div className="flex-1 min-w-0">
              {summary && <div className="font-mono text-xs text-foreground truncate">{summary}</div>}
              {r.comment && <div className="text-xs text-muted-foreground truncate">{r.comment}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
