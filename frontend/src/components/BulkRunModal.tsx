import { useEffect, useState } from "react";
import api from "../lib/api";

interface Minion {
  id: string;
  hostname: string;
  status: string;
}

type JobStatus = "idle" | "running" | "done" | "failed";

interface JobState {
  status: JobStatus;
  stdout: string;
  exit_code: number | null;
}

interface Props {
  minions: Minion[];
  onClose: () => void;
}

const STATUS_ICON: Record<JobStatus, string> = {
  idle: "○",
  running: "↻",
  done: "✓",
  failed: "✗",
};

const STATUS_COLOR: Record<JobStatus, string> = {
  idle: "text-muted-foreground",
  running: "text-yellow-400",
  done: "text-green-400",
  failed: "text-red-400",
};

export default function BulkRunModal({ minions, onClose }: Props) {
  const activeMinions = minions.filter((m) => m.status === "active");
  const [checked, setChecked] = useState<Set<string>>(
    new Set(activeMinions.map((m) => m.id))
  );
  const [cmd, setCmd] = useState("");
  const [jobs, setJobs] = useState<Map<string, JobState>>(new Map());
  const [selectedMinion, setSelectedMinion] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (selectedMinion && !activeMinions.find((m) => m.id === selectedMinion)) {
      setSelectedMinion(null);
    }
  }, [activeMinions, selectedMinion]);

  useEffect(() => {
    setChecked((prev) => {
      const activeIds = new Set(activeMinions.map((m) => m.id));
      const filtered = new Set([...prev].filter((id) => activeIds.has(id)));
      return filtered.size === prev.size ? prev : filtered;
    });
  }, [activeMinions]);

  function setJobState(id: string, update: Partial<JobState>) {
    setJobs((prev) => {
      const next = new Map(prev);
      const current = prev.get(id) ?? { status: "idle" as JobStatus, stdout: "", exit_code: null };
      next.set(id, { ...current, ...update });
      return next;
    });
  }

  async function handleRun() {
    if (!cmd.trim() || checked.size === 0 || running) return;
    setRunning(true);
    const ids = [...checked];
    ids.forEach((id) => setJobState(id, { status: "running", stdout: "", exit_code: null }));

    await Promise.allSettled(
      ids.map(async (id) => {
        try {
          const res = await api.post(`/minions/${id}/jobs`, {
            command: cmd.trim(),
            actor: "ui",
          });
          setJobState(id, {
            status: res.data.exit_code === 0 ? "done" : "failed",
            stdout: res.data.stdout ?? "",
            exit_code: res.data.exit_code,
          });
        } catch {
          setJobState(id, { status: "failed", stdout: "Connection error or command rejected.", exit_code: -1 });
        }
      })
    );
    setRunning(false);
  }

  function toggleCheck(id: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  const jobList = [...jobs.values()];
  const doneCount = jobList.filter((j) => j.status === "done").length;
  const failedCount = jobList.filter((j) => j.status === "failed").length;
  const totalRan = jobList.length;
  const allDone = totalRan > 0 && doneCount + failedCount === totalRan;

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-card border border-border rounded-xl w-full max-w-4xl shadow-2xl flex flex-col max-h-[85vh]">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
          <h2 className="text-lg font-bold">Run Command</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xl leading-none">✕</button>
        </div>

        {/* Command input */}
        <div className="px-6 py-3 border-b border-border flex gap-3 shrink-0">
          <input
            className="flex-1 bg-muted border border-border rounded-lg px-3 py-2 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-primary"
            placeholder="docker ps"
            value={cmd}
            onChange={(e) => setCmd(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleRun()}
            autoFocus
            disabled={running}
          />
          <button
            onClick={handleRun}
            disabled={running || !cmd.trim() || checked.size === 0}
            className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium disabled:opacity-40 transition-opacity"
          >
            {running ? "Running…" : "Run"}
          </button>
        </div>

        {/* Body */}
        <div className="flex flex-1 overflow-hidden">

          {/* Left: minion list */}
          <div className="w-[35%] border-r border-border flex flex-col overflow-hidden">
            <div className="px-4 py-2 border-b border-border flex items-center gap-2 shrink-0">
              <input
                type="checkbox"
                checked={checked.size === activeMinions.length && activeMinions.length > 0}
                onChange={(e) =>
                  setChecked(e.target.checked ? new Set(activeMinions.map((m) => m.id)) : new Set())
                }
                className="rounded"
                disabled={running}
              />
              <span className="text-xs text-muted-foreground uppercase font-semibold tracking-wide">
                {checked.size} / {activeMinions.length} selected
              </span>
            </div>
            <div className="overflow-y-auto flex-1">
              {activeMinions.map((m) => {
                const job = jobs.get(m.id);
                const jStatus: JobStatus = job?.status ?? "idle";
                return (
                  <div
                    key={m.id}
                    onClick={() => setSelectedMinion(m.id)}
                    className={`flex items-center gap-3 px-4 py-3 cursor-pointer border-b border-border hover:bg-muted/30 transition-colors ${
                      selectedMinion === m.id ? "bg-muted/50" : ""
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked.has(m.id)}
                      onChange={() => toggleCheck(m.id)}
                      onClick={(e) => e.stopPropagation()}
                      disabled={running}
                      className="rounded"
                    />
                    <span className={`text-sm font-mono shrink-0 ${STATUS_COLOR[jStatus]}`}>
                      {STATUS_ICON[jStatus]}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">{m.hostname}</div>
                      {job?.exit_code !== null && (
                        <div className="text-xs text-muted-foreground">exit: {job!.exit_code}</div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Right: output */}
          <div className="flex-1 flex flex-col overflow-hidden">
            {!selectedMinion ? (
              <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
                Select a minion to view output
              </div>
            ) : (
              <>
                <div className="px-4 py-2 border-b border-border text-xs text-muted-foreground font-mono shrink-0">
                  {activeMinions.find((m) => m.id === selectedMinion)?.hostname}
                </div>
                <pre className="flex-1 overflow-y-auto p-4 font-mono text-xs text-foreground bg-muted/10 whitespace-pre-wrap break-all">
                  {(() => {
                    const job = jobs.get(selectedMinion);
                    if (!job || job.status === "idle") return "Not yet run.";
                    if (job.status === "running") return "Running…";
                    return job.stdout || "(no output)";
                  })()}
                </pre>
              </>
            )}
          </div>
        </div>

        {/* Footer */}
        {totalRan > 0 && (
          <div className="px-6 py-3 border-t border-border text-xs text-muted-foreground shrink-0 flex items-center justify-between">
            <span>
              {doneCount + failedCount}/{totalRan} complete
              {failedCount > 0 && <span className="text-red-400 ml-2">· {failedCount} failed</span>}
              {allDone && failedCount === 0 && <span className="text-green-400 ml-2">· all succeeded</span>}
            </span>
            {allDone && (
              <button onClick={onClose} className="text-xs text-muted-foreground hover:text-foreground border border-border px-3 py-1 rounded-lg">
                Close
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
