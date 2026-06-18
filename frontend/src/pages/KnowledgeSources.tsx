import { useEffect, useState } from "react";
import api from "../lib/api";
import { Button } from "../components/ui/Button";
import { Card, CardContent } from "../components/ui/Card";
import { Database, Plus, Trash2, RefreshCw, ToggleLeft, ToggleRight, Pencil } from "lucide-react";
import { useToast } from "../context/ToastContext";
import { useConfirm } from "../context/ConfirmContext";
import AddKnowledgeSourceModal from "../components/AddKnowledgeSourceModal";

interface ExternalKnowledgeSource {
  id: string;
  name: string;
  provider: string;
  enabled: boolean;
  config: Record<string, string | number>;
  created_at: string;
}

const PROVIDER_LABELS: Record<string, string> = {
  azure_ai_search: "Azure AI Search",
  qdrant: "Qdrant",
  pinecone: "Pinecone",
  weaviate: "Weaviate",
  opensearch: "OpenSearch",
  chroma: "Chroma",
};

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
          <h1 className="text-2xl font-bold text-slate-900 dark:text-foreground flex items-center gap-2">
            <Database size={22} /> Knowledge Sources
          </h1>
          <p className="text-sm text-slate-500 dark:text-muted-foreground mt-1">
            Your team's knowledge, available to the AI automatically.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={load} disabled={loading}>
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
          </Button>
          <Button onClick={openAdd} className="whitespace-nowrap">
            <Plus size={15} className="mr-1" /> Add Source
          </Button>
        </div>
      </div>

      {sources.length === 0 && !loading && (
        <div className="rounded-xl border border-border bg-card p-10 text-center">
          <Database size={36} className="mx-auto mb-3 text-slate-300 dark:text-muted-foreground opacity-50" />
          <p className="font-medium text-slate-700 dark:text-foreground">No external knowledge sources configured</p>
          <p className="text-sm mt-1 text-slate-500 dark:text-muted-foreground">
            Add a source to let DokOps query your knowledge base during incident analysis.
          </p>
        </div>
      )}

      <div className="space-y-3">
        {sources.map((source) => (
          <Card key={source.id}>
            <CardContent className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Database size={18} className="text-blue-500 dark:text-blue-400 shrink-0" />
                <div>
                  <p className="font-medium text-slate-900 dark:text-foreground">{source.name}</p>
                  <p className="text-xs text-slate-500 dark:text-muted-foreground">
                    {PROVIDER_LABELS[source.provider] ?? source.provider}
                    {source.config.endpoint ? ` · ${source.config.endpoint}` : ""}
                    {source.config.index_name ? ` · index: ${source.config.index_name}` : ""}
                    {source.config.collection_name ? ` · collection: ${source.config.collection_name}` : ""}
                    {source.config.index_host ? ` · ${source.config.index_host}` : ""}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                  source.enabled
                    ? "bg-emerald-100 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
                    : "bg-slate-100 dark:bg-secondary text-slate-500 dark:text-muted-foreground"
                }`}>
                  {source.enabled ? "Enabled" : "Disabled"}
                </span>
                <button
                  onClick={() => handleToggle(source)}
                  className="text-slate-400 dark:text-muted-foreground hover:text-slate-700 dark:hover:text-foreground transition-colors"
                  title={source.enabled ? "Disable" : "Enable"}
                >
                  {source.enabled
                    ? <ToggleRight size={20} className="text-emerald-500 dark:text-emerald-400" />
                    : <ToggleLeft size={20} />}
                </button>
                <button
                  onClick={() => openEdit(source)}
                  className="text-slate-400 dark:text-muted-foreground hover:text-slate-700 dark:hover:text-foreground transition-colors"
                >
                  <Pencil size={15} />
                </button>
                <button
                  onClick={() => handleDelete(source)}
                  className="text-slate-400 dark:text-muted-foreground hover:text-red-500 dark:hover:text-red-400 transition-colors"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </CardContent>
          </Card>
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
