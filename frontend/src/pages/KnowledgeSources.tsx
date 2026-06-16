import { useEffect, useState } from "react";
import api from "../lib/api";
import { Button } from "../components/ui/Button";
import { Database, Plus, Trash2, RefreshCw, ToggleLeft, ToggleRight, Pencil } from "lucide-react";
import { useToast } from "../context/ToastContext";
import { useConfirm } from "../context/ConfirmContext";
import AddKnowledgeSourceModal from "../components/AddKnowledgeSourceModal";

interface AzureConfig {
  endpoint: string;
  api_key: string;
  index_name: string;
  top_k: number;
  semantic_config: string;
}

interface ExternalKnowledgeSource {
  id: string;
  name: string;
  provider: string;
  enabled: boolean;
  config: AzureConfig;
  created_at: string;
}

export default function KnowledgeSources() {
  const { toast } = useToast();
  const { confirm } = useConfirm();
  const [sources, setSources] = useState<ExternalKnowledgeSource[]>([]);
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<ExternalKnowledgeSource | null>(null);

  async function load() {
    setLoading(true);
    try {
      const res = await api.get<ExternalKnowledgeSource[]>("/knowledge-sources");
      setSources(res.data);
    } catch {
      toast("Failed to load knowledge sources.", "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function handleToggle(source: ExternalKnowledgeSource) {
    try {
      await api.patch(`/knowledge-sources/${source.id}/toggle`, { enabled: !source.enabled });
      setSources((prev) =>
        prev.map((s) => s.id === source.id ? { ...s, enabled: !s.enabled } : s)
      );
    } catch {
      toast("Failed to update source.", "error");
    }
  }

  async function handleDelete(source: ExternalKnowledgeSource) {
    const ok = await confirm({
      title: "Delete Knowledge Source",
      description: `Delete "${source.name}"? This cannot be undone.`,
      variant: "danger",
      confirmLabel: "Delete",
    });
    if (!ok) return;
    try {
      await api.delete(`/knowledge-sources/${source.id}`);
      setSources((prev) => prev.filter((s) => s.id !== source.id));
      toast("Source deleted.", "success");
    } catch {
      toast("Failed to delete source.", "error");
    }
  }

  function openAdd() { setEditing(null); setShowModal(true); }
  function openEdit(source: ExternalKnowledgeSource) { setEditing(source); setShowModal(true); }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Database size={22} /> Knowledge Sources
          </h1>
          <p className="text-sm text-zinc-400 mt-1">
            Connect company-owned knowledge bases. DokOps retrieves context from these automatically — no indexing required.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={load} disabled={loading}>
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
          </Button>
          <Button onClick={openAdd}>
            <Plus size={15} className="mr-1" /> Add Source
          </Button>
        </div>
      </div>

      {sources.length === 0 && !loading && (
        <div className="rounded-xl border border-white/10 bg-white/5 p-10 text-center text-zinc-400">
          <Database size={36} className="mx-auto mb-3 opacity-30" />
          <p className="font-medium text-zinc-300">No external knowledge sources configured</p>
          <p className="text-sm mt-1">Add a source to let DokOps query your company's knowledge base during incident analysis.</p>
        </div>
      )}

      <div className="space-y-3">
        {sources.map((source) => (
          <div
            key={source.id}
            className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 px-5 py-4"
          >
            <div className="flex items-center gap-3">
              <Database size={18} className="text-blue-400 shrink-0" />
              <div>
                <p className="font-medium text-white">{source.name}</p>
                <p className="text-xs text-zinc-500">
                  Azure AI Search · {source.config.endpoint} · index: {source.config.index_name}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${source.enabled ? "bg-emerald-500/15 text-emerald-400" : "bg-zinc-700 text-zinc-400"}`}>
                {source.enabled ? "Enabled" : "Disabled"}
              </span>
              <button
                onClick={() => handleToggle(source)}
                className="text-zinc-400 hover:text-white transition-colors"
                title={source.enabled ? "Disable" : "Enable"}
              >
                {source.enabled ? <ToggleRight size={20} className="text-emerald-400" /> : <ToggleLeft size={20} />}
              </button>
              <button onClick={() => openEdit(source)} className="text-zinc-400 hover:text-white transition-colors">
                <Pencil size={15} />
              </button>
              <button onClick={() => handleDelete(source)} className="text-zinc-400 hover:text-red-400 transition-colors">
                <Trash2 size={15} />
              </button>
            </div>
          </div>
        ))}
      </div>

      {showModal && (
        <AddKnowledgeSourceModal
          editing={editing}
          onClose={() => setShowModal(false)}
          onSaved={load}
        />
      )}
    </div>
  );
}
