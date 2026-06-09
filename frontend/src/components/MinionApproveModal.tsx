import { useState } from "react";
import api from "../lib/api";

interface Props {
  minionId: string;
  hostname: string;
  onClose: () => void;
  onApproved: () => void;
}

export default function MinionApproveModal({ minionId, hostname, onClose, onApproved }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function approve() {
    setLoading(true);
    setError("");
    try {
      await api.post(`/minions/${minionId}/approve`);
      onApproved();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setError(err.response?.data?.detail ?? "Failed to approve");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
      <div className="bg-card border border-border rounded-xl p-6 w-full max-w-md shadow-2xl">
        <h2 className="text-lg font-bold mb-2">Approve Minion</h2>
        <p className="text-muted-foreground text-sm mb-4">
          Allow <span className="text-foreground font-mono">{hostname}</span> to receive jobs?
          This requires God Mode.
        </p>
        {error && <p className="text-red-400 text-sm mb-3">{error}</p>}
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="px-4 py-2 rounded-lg border border-border text-sm">Cancel</button>
          <button
            onClick={approve}
            disabled={loading}
            className="px-4 py-2 rounded-lg bg-green-600 hover:bg-green-700 text-white text-sm disabled:opacity-50"
          >
            {loading ? "Approving…" : "Approve"}
          </button>
        </div>
      </div>
    </div>
  );
}
