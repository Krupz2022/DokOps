import { useEffect, useState } from "react";
import api from "../../lib/api";
import { useAppContext } from "../../context/AppContext";
import { useToast } from "../../context/ToastContext";
import { useConfirm } from "../../context/ConfirmContext";
import BlueprintResultTable from "./BlueprintResultTable";
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

  async function loadPreview() {
    try {
      const r = await api.get(`/minions/${minionId}/blueprint`);
      setCompiled(r.data as CompiledBlueprint);
    } catch {
      setCompiled({ resources: [], sources: {} });
    }
  }
  async function loadRuns() {
    try {
      const r = await api.get(`/minions/${minionId}/blueprint/runs`);
      setRuns((r.data as BlueprintRun[]).slice(-10).reverse());
    } catch { /* ignore */ }
  }
  useEffect(() => { loadPreview(); loadRuns(); }, [minionId]);

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
      const r = await api.post(`/minions/${minionId}/blueprint/run`, { test });
      const { run_id } = r.data as RunResponse;
      await fetchRunResults(run_id);
      if (test) setHasDryRun(true);
      loadRuns();
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: string } }; message?: string };
      if (err.response?.status === 403) toast("God Mode required to apply", "error");
      else toast(err.response?.data?.detail ?? err.message ?? "Run failed", "error");
    } finally {
      setRunning(false);
    }
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
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs text-muted-foreground uppercase tracking-wider">Compiled Blueprint</h2>
          <button onClick={loadPreview} className="text-xs text-muted-foreground hover:text-foreground">refresh</button>
        </div>
        {resourceCount === 0 ? (
          <p className="text-sm text-muted-foreground">No blueprints assigned to this minion.</p>
        ) : (
          <div className="space-y-1">
            {compiled!.resources.map((res) => (
              <div key={res.id} className="flex items-center gap-3 text-sm py-1">
                <span className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground w-16 text-center shrink-0">{res.type}</span>
                <span className="font-mono text-foreground">{res.id}</span>
                {typeof res.name === "string" && <span className="text-muted-foreground text-xs">{res.name}</span>}
              </div>
            ))}
            {Object.keys(compiled!.sources).length > 0 && (
              <div className="text-xs text-muted-foreground pt-2">
                sources: {Object.keys(compiled!.sources).join(", ")}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => runBlueprint(true)}
          disabled={running || resourceCount === 0}
          className="px-3 py-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 text-sm font-medium disabled:opacity-50"
        >
          {running ? "Running…" : "Dry-run"}
        </button>
        <button
          onClick={handleApply}
          disabled={running || resourceCount === 0 || !godModeActive}
          title={godModeActive ? "Apply blueprint" : "Enable God Mode to apply"}
          className="px-3 py-1.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium disabled:opacity-50"
        >
          Apply
        </button>
        {!godModeActive && <span className="text-xs text-muted-foreground">Enable God Mode to apply</span>}
      </div>

      {/* Results */}
      {results && (
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
