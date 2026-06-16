import { useState } from "react";
import api from "../lib/api";
import { useToast } from "../context/ToastContext";
import { Button } from "./ui/Button";
import { Input } from "./ui/Input";
import { X, Loader2 } from "lucide-react";

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

interface Props {
  editing?: ExternalKnowledgeSource | null;
  onClose: () => void;
  onSaved: () => void;
}

const DEFAULT_CONFIG: AzureConfig = {
  endpoint: "",
  api_key: "",
  index_name: "",
  top_k: 3,
  semantic_config: "",
};

export default function AddKnowledgeSourceModal({ editing, onClose, onSaved }: Props) {
  const { toast } = useToast();
  const [name, setName] = useState(editing?.name ?? "");
  const [config, setConfig] = useState<AzureConfig>(
    editing ? { ...DEFAULT_CONFIG, ...editing.config, api_key: "" } : DEFAULT_CONFIG
  );
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  const setField = (key: keyof AzureConfig) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setConfig((c) => ({ ...c, [key]: key === "top_k" ? Number(e.target.value) : e.target.value }));

  async function handleTest() {
    if (!config.endpoint || !config.index_name) {
      toast("Fill in Endpoint and Index Name before testing.", "error");
      return;
    }
    setTesting(true);
    try {
      await api.post("/knowledge-sources/test-config", config);
      toast("Connection successful!", "success");
    } catch (err: any) {
      toast(err?.response?.data?.detail ?? "Connection failed.", "error");
    } finally {
      setTesting(false);
    }
  }

  async function handleSave() {
    if (!name || !config.endpoint || !config.api_key || !config.index_name) {
      toast("Name, Endpoint, API Key, and Index Name are required.", "error");
      return;
    }
    setSaving(true);
    try {
      const payload = { name, provider: "azure_ai_search", config };
      if (editing) {
        await api.put(`/knowledge-sources/${editing.id}`, payload);
      } else {
        await api.post("/knowledge-sources", payload);
      }
      toast(`Knowledge source ${editing ? "updated" : "created"}.`, "success");
      onSaved();
      onClose();
    } catch (err: any) {
      toast(err?.response?.data?.detail ?? "Save failed.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative w-full max-w-lg rounded-xl border border-white/10 bg-zinc-900 p-6 shadow-2xl">
        <button onClick={onClose} className="absolute right-4 top-4 text-zinc-400 hover:text-white">
          <X size={18} />
        </button>

        <h2 className="mb-5 text-lg font-semibold text-white">
          {editing ? "Edit Knowledge Source" : "Add Knowledge Source"}
        </h2>

        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-zinc-400">Provider</label>
            <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-300">
              Azure AI Search
            </div>
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-zinc-400">Name *</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Company Wiki" />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-zinc-400">Endpoint URL *</label>
            <Input
              value={config.endpoint}
              onChange={setField("endpoint")}
              placeholder="https://your-search.search.windows.net"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-zinc-400">
              API Key *{editing && " (leave blank to keep existing)"}
            </label>
            <Input
              type="password"
              value={config.api_key}
              onChange={setField("api_key")}
              placeholder={editing ? "••••••" : "your-api-key"}
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-zinc-400">Index Name *</label>
            <Input value={config.index_name} onChange={setField("index_name")} placeholder="company-kb" />
          </div>

          <div className="flex gap-3">
            <div className="flex-1">
              <label className="mb-1 block text-xs font-medium text-zinc-400">Top-K Results</label>
              <Input
                type="number"
                min={1}
                max={10}
                value={config.top_k}
                onChange={setField("top_k")}
              />
            </div>
            <div className="flex-1">
              <label className="mb-1 block text-xs font-medium text-zinc-400">
                Semantic Config <span className="text-zinc-500">(optional)</span>
              </label>
              <Input
                value={config.semantic_config}
                onChange={setField("semantic_config")}
                placeholder="my-semantic-config"
              />
            </div>
          </div>
        </div>

        <div className="mt-6 flex items-center justify-between gap-3">
          <Button variant="outline" onClick={handleTest} disabled={testing || saving}>
            {testing && <Loader2 size={14} className="animate-spin mr-2" />}
            Test Connection
          </Button>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving && <Loader2 size={14} className="animate-spin mr-2" />}
              {editing ? "Update" : "Save"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
