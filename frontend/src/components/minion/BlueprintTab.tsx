import { useEffect, useState } from "react";
import { ChevronUp, ChevronDown } from "lucide-react";
import api from "../../lib/api";
import { useAppContext } from "../../context/AppContext";
import { useToast } from "../../context/ToastContext";
import { useConfirm } from "../../context/ConfirmContext";
import BlueprintResultTable from "./BlueprintResultTable";
import LiveRunConsole from "./LiveRunConsole";
import { dryRunWarning } from "../../lib/blueprintView";
import type { CompiledBlueprint, ResourceResult, BlueprintRun, RunResponse } from "../../types/blueprint";

export default function BlueprintTab({ minionId }: { minionId: string }) {
  const { godModeActive } = useAppContext();
  const { toast } = useToast();
  const { confirm } = useConfirm();

  const [compiled, setCompiled] = useState<CompiledBlueprint | null>(null);
  const [results, setResults] = useState<ResourceResult[] | null>(null);
  const [runs, setRuns] = useState<BlueprintRun[]>([]);
  const [running, setRunning] = useState(false);
  const [hasDryRun, setHasDryRun] = useState(false);
  const [liveRunId, setLiveRunId] = useState<string | null>(null);
  // Run-order + selection: `order` holds resource ids in run order, `checked` which run.
  const [order, setOrder] = useState<string[]>([]);
  const [checked, setChecked] = useState<Set<string>>(new Set());

  async function loadPreview() {
    try {
      const r = await api.get(`/minions/${minionId}/blueprint`);
      const data = r.data as CompiledBlueprint;
      setCompiled(data);
      const ids = data.resources.map((res) => res.id);
      setOrder(ids);
      setChecked(new Set(ids));
    } catch {
      setCompiled({ resources: [], sources: {} });
      setOrder([]);
      setChecked(new Set());
    }
  }

  function toggle(id: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }
  function move(idx: number, dir: -1 | 1) {
    setOrder((prev) => {
      const j = idx + dir;
      if (j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[idx], next[j]] = [next[j], next[idx]];
      return next;
    });
  }
  const selectedIds = order.filter((id) => checked.has(id));
  async function loadRuns() {
    try {
      const r = await api.get(`/minions/${minionId}/blueprint/runs`);
      setRuns((r.data as BlueprintRun[]).slice(-10).reverse());
    } catch { /* ignore */ }
  }
  useEffect(() => {
    loadPreview();
    loadRuns();
    api.get(`/minions/${minionId}/blueprint/runs`)
      .then((r) => {
        const runs = r.data as BlueprintRun[];
        const active = runs.find((x) => x.status === "running");
        if (active) { setRunning(true); setLiveRunId(active.id); }
      })
      .catch(() => { /* ignore */ });
  }, [minionId]);

  async function fetchRunResults(runId: string) {
    try {
      const r = await api.get(`/minions/blueprint/runs/${runId}`);
      setResults((r.data as { results: ResourceResult[] }).results ?? []);
    } catch {
      toast("Failed to load run results", "error");
    }
  }

  async function runBlueprint(test: boolean) {
    setRunning(true);
    setResults(null);
    try {
      const r = await api.post(`/minions/${minionId}/blueprint/run`, { test, resource_ids: selectedIds });
      const { run_id } = r.data as RunResponse;
      if (test) setHasDryRun(true);
      setLiveRunId(run_id);          // → LiveRunConsole streams it
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: string } }; message?: string };
      if (err.response?.status === 403) toast("God Mode required to apply", "error");
      else toast(err.response?.data?.detail ?? err.message ?? "Run failed", "error");
      setRunning(false);
    }
  }

  async function handleRunDone() {
    setRunning(false);
    if (liveRunId) {
      await fetchRunResults(liveRunId);   // settle into the persisted result table
      setLiveRunId(null);
    }
    loadRuns();
  }

  async function handleApply() {
    const ok = await confirm({
      title: "Apply blueprint",
      description: `This will reconcile ${minionId} to its blueprint and may change packages, files, and services. ${dryRunWarning(hasDryRun)}`.trim(),
      variant: "danger",
      confirmLabel: "Apply",
    });
    if (ok) runBlueprint(false);
  }

  const resourceCount = compiled?.resources.length ?? 0;

  return (
    <div className="space-y-6">
      {/* Compiled preview */}
      <div className="bg-card border border-border rounded-xl p-4">
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-xs text-muted-foreground uppercase tracking-wider">Compiled Blueprint</h2>
          <button onClick={loadPreview} className="text-xs text-muted-foreground hover:text-foreground">refresh</button>
        </div>
        {resourceCount === 0 ? (
          <p className="text-sm text-muted-foreground mt-2">No blueprints assigned to this minion.</p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground mb-3">Pick which resources run and in what order. Top runs first.</p>
            <div className="space-y-1">
              {order.map((id, i) => {
                const res = compiled!.resources.find((r) => r.id === id);
                if (!res) return null;
                const on = checked.has(id);
                return (
                  <div key={id} className={`flex items-center gap-3 text-sm py-1.5 px-2 rounded-lg border ${on ? "border-border bg-muted/20" : "border-transparent opacity-50"}`}>
                    <input type="checkbox" checked={on} onChange={() => toggle(id)} className="accent-primary shrink-0" />
                    <span className="text-muted-foreground font-mono text-xs w-5 text-right shrink-0">{i + 1}</span>
                    <span className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground w-16 text-center shrink-0">{res.type}</span>
                    <span className="font-mono text-foreground flex-1 truncate">{res.id}</span>
                    {typeof res.name === "string" && <span className="text-muted-foreground text-xs truncate">{res.name}</span>}
                    <div className="flex items-center shrink-0">
                      <button onClick={() => move(i, -1)} disabled={i === 0} title="Move up"
                        className="p-0.5 text-muted-foreground hover:text-foreground disabled:opacity-30"><ChevronUp className="w-4 h-4" /></button>
                      <button onClick={() => move(i, 1)} disabled={i === order.length - 1} title="Move down"
                        className="p-0.5 text-muted-foreground hover:text-foreground disabled:opacity-30"><ChevronDown className="w-4 h-4" /></button>
                    </div>
                  </div>
                );
              })}
            </div>
            {Object.keys(compiled!.sources).length > 0 && (
              <div className="text-xs text-muted-foreground pt-2">
                sources: {Object.keys(compiled!.sources).join(", ")}
              </div>
            )}
          </>
        )}
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => runBlueprint(true)}
          disabled={running || selectedIds.length === 0}
          className="px-3 py-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 text-sm font-medium disabled:opacity-50"
        >
          {running ? "Running…" : `Dry-run${selectedIds.length && selectedIds.length !== resourceCount ? ` (${selectedIds.length})` : ""}`}
        </button>
        <button
          onClick={handleApply}
          disabled={running || selectedIds.length === 0 || !godModeActive}
          title={godModeActive ? "Apply blueprint" : "Enable God Mode to apply"}
          className="px-3 py-1.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium disabled:opacity-50"
        >
          {`Apply${selectedIds.length && selectedIds.length !== resourceCount ? ` (${selectedIds.length})` : ""}`}
        </button>
        {!godModeActive && <span className="text-xs text-muted-foreground">Enable God Mode to apply</span>}
      </div>

      {/* Results */}
      {liveRunId ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <h2 className="text-xs text-muted-foreground uppercase tracking-wider mb-2">Live run</h2>
          <LiveRunConsole runId={liveRunId} onDone={handleRunDone} />
        </div>
      ) : results && (
        <div className="bg-card border border-border rounded-xl p-4">
          <h2 className="text-xs text-muted-foreground uppercase tracking-wider mb-2">Result</h2>
          <BlueprintResultTable results={results} />
        </div>
      )}

      {/* Run history */}
      <div className="bg-card border border-border rounded-xl p-4">
        <h2 className="text-xs text-muted-foreground uppercase tracking-wider mb-3">Run History</h2>
        {runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">No runs yet.</p>
        ) : (
          <div className="space-y-1">
            {runs.map((run) => (
              <button
                key={run.id}
                onClick={() => fetchRunResults(run.id)}
                className="w-full flex items-center gap-3 text-sm py-1 hover:bg-muted/40 rounded px-1 text-left"
              >
                <span className={`text-xs px-1.5 py-0.5 rounded ${run.status === "done" ? "bg-green-500/20 text-green-400" : run.status === "failed" ? "bg-red-500/20 text-red-400" : "bg-muted text-muted-foreground"}`}>{run.status}</span>
                <span className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">{run.test ? "dry-run" : "apply"}</span>
                <span className="text-muted-foreground text-xs flex-1">{new Date(run.created_at).toLocaleString()}</span>
                <span className="text-muted-foreground text-xs">{run.actor}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
