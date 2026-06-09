import { useState } from "react";

interface Props {
  minionId: string;
  onClose: () => void;
  onJobSubmitted: (cmd: string) => void;
}

export default function MinionJobModal({ minionId, onClose, onJobSubmitted }: Props) {
  const [cmd, setCmd] = useState("");
  const [error, setError] = useState("");

  function submit() {
    if (!cmd.trim()) { setError("Command is required"); return; }
    onJobSubmitted(cmd.trim());
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
      <div className="bg-card border border-border rounded-xl p-6 w-full max-w-lg shadow-2xl">
        <h2 className="text-lg font-bold mb-2">Run Command on Minion</h2>
        <p className="text-muted-foreground text-xs mb-3 font-mono">{minionId}</p>
        <input
          className="w-full bg-muted border border-border rounded-lg px-3 py-2 font-mono text-sm mb-2 focus:outline-none focus:ring-1 focus:ring-primary"
          placeholder="docker ps -a"
          value={cmd}
          onChange={(e) => setCmd(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          autoFocus
        />
        {error && <p className="text-red-400 text-xs mb-2">{error}</p>}
        <div className="flex gap-3 justify-end mt-2">
          <button onClick={onClose} className="px-4 py-2 rounded-lg border border-border text-sm">Cancel</button>
          <button
            onClick={submit}
            className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm"
          >
            Run
          </button>
        </div>
      </div>
    </div>
  );
}
