import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../lib/api";
import BulkRunModal from "../components/BulkRunModal";

interface Minion {
  id: string;
  hostname: string;
  status: "pending" | "active" | "offline";
  grains: string;
  last_seen: string | null;
}

const STATUS_DOT: Record<string, string> = {
  active:  "bg-green-500",
  pending: "bg-yellow-400",
  offline: "bg-red-500",
};

const STATUS_LABEL: Record<string, string> = {
  active:  "active",
  pending: "⏳ pending",
  offline: "offline",
};

const STATUS_TEXT: Record<string, string> = {
  active:  "text-green-400",
  pending: "text-yellow-400",
  offline: "text-red-400",
};

export default function Minions() {
  const [minions, setMinions] = useState<Minion[]>([]);
  const [loading, setLoading] = useState(true);
  const [installCmd, setInstallCmd] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const [showKeys, setShowKeys] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [keySaving, setKeySaving] = useState(false);
  const [keySaved, setKeySaved] = useState(false);
  const [keyError, setKeyError] = useState("");
  const [showRunModal, setShowRunModal] = useState(false);

  useEffect(() => {
    if (!keySaved) return;
    const timer = setTimeout(() => setKeySaved(false), 3000);
    return () => clearTimeout(timer);
  }, [keySaved]);

  async function saveKey() {
    if (!keyInput.trim()) return;
    setKeySaving(true);
    setKeyError("");
    try {
      await api.post("/ai/config", { minion_auto_accept_key: keyInput.trim() });
      setKeySaved(true);
      setKeyInput("");
    } catch {
      setKeyError("Failed to save key.");
    } finally {
      setKeySaving(false);
    }
  }

  async function handleDelete(id: string) {
    setDeleting(id);
    try {
      await api.delete(`/minions/${id}`);
      setMinions((prev) => prev.filter((m) => m.id !== id));
    } finally {
      setDeleting(null);
    }
  }

  useEffect(() => {
    api.get("/minions/").then((r) => setMinions(r.data)).finally(() => setLoading(false));
    const base = (import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1")
      .replace("/api/v1", "");
    setInstallCmd(`curl ${base}/minion/install.sh | bash -s -- --token=<key> --org="My Org" --env=qa`);
  }, []);

  function parseGrains(raw: string) {
    try { return JSON.parse(raw); } catch { return {}; }
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex justify-between items-start mb-4">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Minions</h1>
          <p className="text-muted-foreground text-sm mt-1">
            {minions.filter((m) => m.status === "active").length} active ·{" "}
            {minions.filter((m) => m.status === "pending").length} pending ·{" "}
            {minions.filter((m) => m.status === "offline").length} offline
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => { setShowKeys(v => !v); setKeyInput(""); setKeyError(""); }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm transition-colors ${showKeys ? "bg-blue-900/40 border-blue-600 text-blue-300" : "border-border text-muted-foreground hover:text-foreground"}`}
          >
            🔑 Keys
          </button>
          <button
            onClick={() => setShowRunModal(true)}
            disabled={minions.filter(m => m.status === "active").length === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-sm text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
          >
            ⚡ Run Command
          </button>
        </div>
      </div>

      {showKeys && (
        <div className="mb-4 bg-card border border-blue-900/50 rounded-lg p-4">
          <p className="text-xs text-blue-400 font-semibold uppercase mb-3">Auto-Accept Key</p>
          <div className="flex gap-2 items-center">
            <input
              type="password"
              value={keyInput}
              onChange={e => setKeyInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && saveKey()}
              placeholder="enter new key…"
              className="flex-1 bg-muted border border-border rounded-lg px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <button
              onClick={saveKey}
              disabled={keySaving || !keyInput.trim()}
              className="px-4 py-1.5 bg-primary text-primary-foreground rounded-lg text-sm disabled:opacity-40"
            >
              {keySaving ? "Saving…" : "Save"}
            </button>
          </div>
          {keySaved && <p className="text-green-400 text-xs mt-2">Key saved.</p>}
          {keyError && <p className="text-red-400 text-xs mt-2">{keyError}</p>}
          <p className="text-xs text-muted-foreground mt-2">Minions connecting with this token are auto-approved.</p>
        </div>
      )}

      {loading ? (
        <p className="text-muted-foreground">Loading...</p>
      ) : minions.length === 0 ? (
        <div className="border border-dashed border-border rounded-lg p-10 text-center text-muted-foreground">
          <p className="mb-2">No minions registered yet.</p>
          <p className="text-sm font-mono bg-muted px-3 py-2 rounded inline-block">{installCmd}</p>
        </div>
      ) : (
        <>
          <div className="rounded-lg border border-border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr className="text-muted-foreground text-xs uppercase">
                  <th className="w-4 px-4 py-3"></th>
                  <th className="px-4 py-3 text-left">Host</th>
                  <th className="px-4 py-3 text-left">OS</th>
                  <th className="px-4 py-3 text-left">Docker</th>
                  <th className="px-4 py-3 text-left">Ansible</th>
                  <th className="px-4 py-3 text-left">Last Seen</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {minions.map((m) => {
                  const g = parseGrains(m.grains);
                  return (
                    <tr key={m.id} className="border-t border-border hover:bg-muted/30 transition-colors">
                      <td className="px-4 py-3">
                        <span className={`inline-block w-2 h-2 rounded-full ${STATUS_DOT[m.status] ?? "bg-gray-500"}`} />
                      </td>
                      <td className="px-4 py-3">
                        <Link to={`/infrastructure/minions/${m.id}`} className="text-foreground hover:text-primary font-medium">
                          {m.hostname}
                        </Link>
                        <div className="text-xs text-muted-foreground font-mono">{m.id.slice(0, 8)}…</div>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{g.os ?? "—"}</td>
                      <td className="px-4 py-3 text-muted-foreground">{g.docker ? `✓ ${g.docker}` : "—"}</td>
                      <td className="px-4 py-3 text-muted-foreground">{g.ansible ? `✓` : "—"}</td>
                      <td className="px-4 py-3 text-muted-foreground text-xs">
                        {m.last_seen ? new Date(m.last_seen).toLocaleString() : "never"}
                      </td>
                      <td className={`px-4 py-3 text-xs font-medium ${STATUS_TEXT[m.status]}`}>
                        {STATUS_LABEL[m.status]}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => handleDelete(m.id)}
                          disabled={deleting === m.id}
                          className="text-xs text-red-400 hover:text-red-300 border border-red-800 hover:border-red-600 px-2 py-1 rounded transition-colors disabled:opacity-40"
                        >
                          {deleting === m.id ? "…" : "Remove"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="mt-4 bg-muted rounded-lg px-4 py-3 text-xs text-muted-foreground font-mono">
            <span className="text-foreground font-medium">Install: </span>
            {installCmd}
          </div>
        </>
      )}
      {showRunModal && (
        <BulkRunModal
          minions={minions}
          onClose={() => setShowRunModal(false)}
        />
      )}
    </div>
  );
}
