// frontend/src/pages/Clusters.tsx
import { useEffect, useState } from "react";
import { Plus, Orbit, CheckCircle2, Clock, XCircle, RefreshCw, Trash2 } from "lucide-react";
import api from "../lib/api";
import AddClusterModal from "../components/clusters/AddClusterModal";
import { cn } from "../lib/utils";
import { useAppContext } from "../context/AppContext";
import { useConfirm } from "../context/ConfirmContext";

interface Cluster {
  id: string;
  name: string;
  provider: string;
  api_server: string;
  namespace: string;
  added_by: string | null;
  created_at: string;
  last_verified: string | null;
}

const PROVIDER_LABELS: Record<string, string> = {
  aks: "Azure AKS",
  eks: "AWS EKS",
  gke: "Google GKE",
  generic: "Generic",
};

function isRecent(dt: string | null): boolean {
  if (!dt) return false;
  return Date.now() - new Date(dt).getTime() < 1000 * 60 * 60 * 24; // 24 h
}

export default function Clusters() {
  const { godModeActive } = useAppContext();
  const { confirm } = useConfirm();

  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [verifying, setVerifying] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<Cluster[]>("/clusters/");
      setClusters(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load clusters.");
    } finally {
      setLoading(false);
    }
  }

  async function deleteCluster(id: string, name: string) {
    const confirmed = await confirm({
      title: `Remove cluster "${name}"?`,
      description: "This will disconnect the cluster and remove all associated credentials. This action cannot be undone.",
      variant: "danger",
      confirmLabel: "Remove",
    });
    if (!confirmed) return;
    setDeleting(id);
    setError(null);
    try {
      await api.delete(`/clusters/${id}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove cluster.");
    } finally {
      setDeleting(null);
    }
  }

  async function verify(id: string) {
    setVerifying(id);
    setVerifyError(null);
    try {
      await api.get(`/clusters/${id}/verify`);
      await load();
    } catch (err) {
      setVerifyError(err instanceof Error ? err.message : "Connectivity check failed.");
    } finally {
      setVerifying(null);
    }
  }

  useEffect(() => { load(); }, []);

  return (
    <div className="flex flex-col h-full">
      <div className="flex-shrink-0 px-6 py-4 flex items-center justify-between border-b border-border/60">
        <div>
          <h1 className="text-base font-semibold text-foreground tracking-tight">Clusters</h1>
          {!loading && (
            <p className="text-xs text-muted-foreground font-mono mt-0.5">
              {clusters.length} cluster{clusters.length !== 1 ? "s" : ""} connected
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 bg-cyan-500 hover:bg-cyan-400 text-white text-xs font-semibold px-3 py-2 rounded-lg transition-colors shadow-lg shadow-cyan-500/20"
        >
          <Plus className="w-3.5 h-3.5" />
          Add Cluster
        </button>
      </div>

      <div className="flex-1 overflow-auto p-6">
        {error && (
          <div className="mb-4 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
            {error}
          </div>
        )}
        {verifyError && (
          <div className="mb-4 px-4 py-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 text-sm">
            {verifyError}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-20 text-muted-foreground/40 text-sm">Loading...</div>
        ) : clusters.length === 0 && !error ? (
          <div className="flex flex-col items-center justify-center py-20 gap-4">
            <Orbit className="w-10 h-10 text-muted-foreground/20" />
            <p className="text-sm text-muted-foreground/50">No clusters connected yet</p>
            <button
              type="button"
              onClick={() => setShowModal(true)}
              className="text-xs text-cyan-400 hover:text-cyan-300 underline underline-offset-2"
            >
              Add your first cluster
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {clusters.map(c => (
              <div
                key={c.id}
                className="flex items-center gap-4 bg-secondary/30 border border-border hover:border-border/80 rounded-xl px-5 py-4 transition-colors"
              >
                <div className="w-9 h-9 rounded-lg bg-cyan-500/10 flex items-center justify-center flex-shrink-0">
                  <Orbit className="w-4 h-4 text-cyan-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-foreground">{c.name}</div>
                  <div className="text-[11px] text-muted-foreground font-mono mt-0.5 truncate">{c.api_server}</div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-muted-foreground bg-secondary px-2 py-0.5 rounded font-mono">
                    {PROVIDER_LABELS[c.provider] ?? c.provider}
                  </span>
                  {c.last_verified ? (
                    isRecent(c.last_verified) ? (
                      <span className="flex items-center gap-1 text-[10px] text-emerald-400">
                        <CheckCircle2 className="w-3 h-3" />Verified
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-[10px] text-amber-400">
                        <Clock className="w-3 h-3" />Stale
                      </span>
                    )
                  ) : (
                    <span className="flex items-center gap-1 text-[10px] text-muted-foreground/40">
                      <XCircle className="w-3 h-3" />Unverified
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => verify(c.id)}
                  disabled={verifying === c.id}
                  aria-label={verifying === c.id ? `Verifying ${c.name}...` : `Verify ${c.name}`}
                  aria-busy={verifying === c.id}
                  className={cn(
                    "text-muted-foreground/40 hover:text-cyan-400 transition-colors",
                    verifying === c.id && "animate-spin text-cyan-400"
                  )}
                  title="Test connectivity"
                >
                  <RefreshCw className="w-4 h-4" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={() => deleteCluster(c.id, c.name)}
                  disabled={!godModeActive || deleting === c.id}
                  aria-label={`Remove ${c.name}`}
                  title={godModeActive ? "Remove cluster" : "Requires God Mode"}
                  className={cn(
                    "transition-colors",
                    godModeActive
                      ? "text-muted-foreground/40 hover:text-red-400"
                      : "text-muted-foreground/20 cursor-not-allowed",
                    deleting === c.id && "animate-pulse text-red-400"
                  )}
                >
                  <Trash2 className="w-4 h-4" aria-hidden="true" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {showModal && (
        <AddClusterModal
          onClose={() => setShowModal(false)}
          onAdded={() => { setShowModal(false); load(); }}
        />
      )}
    </div>
  );
}
