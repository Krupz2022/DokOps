import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Server, Zap, Trash2 } from "lucide-react";
import api from "../lib/api";
import BulkRunModal from "../components/BulkRunModal";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import {
  FleetPage, FleetStat, MinionStatusTag, MinionStatusDot,
  Surface, CopyBlock,
} from "../components/fleet/FleetPage";

interface Minion {
  id: string;
  hostname: string;
  status: "pending" | "active" | "offline";
  grains: string;
  last_seen: string | null;
}

type Filter = "all" | "active" | "pending" | "offline";

export default function Minions() {
  const [minions, setMinions] = useState<Minion[]>([]);
  const [loading, setLoading] = useState(true);
  const [installCmd, setInstallCmd] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const [showRunModal, setShowRunModal] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");

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

  const counts = {
    active: minions.filter((m) => m.status === "active").length,
    pending: minions.filter((m) => m.status === "pending").length,
    offline: minions.filter((m) => m.status === "offline").length,
  };
  const visible = filter === "all" ? minions : minions.filter((m) => m.status === filter);

  return (
    <FleetPage
      icon={Server}
      title="Minions"
      subtitle="Every machine enrolled in the fleet — health, platform, and last contact."
      vitals={
        <>
          <FleetStat value={minions.length} label="total" tone="cyan"
            active={filter === "all"} onClick={() => setFilter("all")} />
          <FleetStat value={counts.active} label="active" tone="green"
            active={filter === "active"} onClick={() => setFilter("active")} />
          <FleetStat value={counts.pending} label="pending" tone="amber"
            active={filter === "pending"} onClick={() => setFilter("pending")} />
          <FleetStat value={counts.offline} label="offline" tone="red"
            active={filter === "offline"} onClick={() => setFilter("offline")} />
        </>
      }
      actions={
        <Button
          size="sm"
          onClick={() => setShowRunModal(true)}
          disabled={counts.active === 0}
        >
          <Zap className="w-3.5 h-3.5" /> Run command
        </Button>
      }
    >
      {loading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : minions.length === 0 ? (
        <Surface className="p-2">
          <EmptyState
            icon={Server}
            title="No minions enrolled"
            description="Run the install command on a machine to enroll it into the fleet."
          />
          <div className="px-5 pb-5 -mt-2 max-w-3xl mx-auto">
            <CopyBlock label="Install command" value={installCmd} />
          </div>
        </Surface>
      ) : (
        <>
          <Surface className="overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground border-b border-border dark:[border-bottom-color:hsl(191_89%_55%_/_0.07)]">
                  <th className="px-4 py-3 font-medium">Host</th>
                  <th className="px-4 py-3 font-medium">OS</th>
                  <th className="px-4 py-3 font-medium">Docker</th>
                  <th className="px-4 py-3 font-medium">Ansible</th>
                  <th className="px-4 py-3 font-medium">Last seen</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {visible.map((m) => {
                  const g = parseGrains(m.grains);
                  return (
                    <tr key={m.id} className="border-t border-border/70 hover:bg-secondary/40 transition-colors group">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2.5">
                          <MinionStatusDot status={m.status} />
                          <div className="min-w-0">
                            <Link
                              to={`/infrastructure/minions/${m.id}`}
                              className="text-foreground hover:text-primary font-medium"
                            >
                              {m.hostname}
                            </Link>
                            <div className="text-[11px] text-muted-foreground font-mono">{m.id.slice(0, 8)}…</div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{g.os ?? "—"}</td>
                      <td className="px-4 py-3 text-muted-foreground font-mono text-xs">{g.docker ? g.docker : "—"}</td>
                      <td className="px-4 py-3 text-muted-foreground">{g.ansible ? "yes" : "—"}</td>
                      <td className="px-4 py-3 text-muted-foreground text-xs font-mono">
                        {m.last_seen ? new Date(m.last_seen).toLocaleString() : "never"}
                      </td>
                      <td className="px-4 py-3"><MinionStatusTag status={m.status} /></td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => handleDelete(m.id)}
                          disabled={deleting === m.id}
                          title="Remove minion"
                          className="opacity-0 group-hover:opacity-100 focus:opacity-100 inline-flex items-center justify-center w-7 h-7 rounded-md text-muted-foreground hover:text-red-400 hover:bg-red-500/10 transition-all disabled:opacity-40"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-10 text-center text-sm text-muted-foreground">
                      No {filter} minions.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </Surface>

          <CopyBlock label="Install command" value={installCmd} className="mt-4" />
        </>
      )}

      {showRunModal && (
        <BulkRunModal minions={minions} onClose={() => setShowRunModal(false)} />
      )}
    </FleetPage>
  );
}
