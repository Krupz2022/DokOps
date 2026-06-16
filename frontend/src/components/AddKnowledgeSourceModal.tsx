import { useState } from "react";
import api from "../lib/api";
import { useToast } from "../context/ToastContext";
import { Button } from "./ui/Button";
import { Input } from "./ui/Input";
import { Modal } from "./ui/Modal";
import { Loader2 } from "lucide-react";

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
    <Modal
      isOpen
      onClose={onClose}
      title={editing ? "Edit Knowledge Source" : "Add Knowledge Source"}
      className="max-w-lg"
      footer={
        <>
          <Button variant="outline" onClick={handleTest} disabled={testing || saving}>
            {testing && <Loader2 size={14} className="animate-spin mr-2" />}
            Test Connection
          </Button>
          <Button variant="ghost" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving && <Loader2 size={14} className="animate-spin mr-2" />}
            {editing ? "Update" : "Save"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-500 dark:text-muted-foreground">Provider</label>
          <div className="rounded-lg border border-slate-200 dark:border-border bg-slate-50 dark:bg-muted/50 px-3 py-2 text-sm text-slate-700 dark:text-slate-300">
            Azure AI Search
          </div>
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-slate-500 dark:text-muted-foreground">Name *</label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Company Wiki" />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-slate-500 dark:text-muted-foreground">Endpoint URL *</label>
          <Input
            value={config.endpoint}
            onChange={setField("endpoint")}
            placeholder="https://your-search.search.windows.net"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-slate-500 dark:text-muted-foreground">
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
          <label className="mb-1 block text-xs font-medium text-slate-500 dark:text-muted-foreground">Index Name *</label>
          <Input value={config.index_name} onChange={setField("index_name")} placeholder="company-kb" />
        </div>

        <div className="flex gap-3">
          <div className="flex-1">
            <label className="mb-1 block text-xs font-medium text-slate-500 dark:text-muted-foreground">Top-K Results</label>
            <Input
              type="number"
              min={1}
              max={10}
              value={config.top_k}
              onChange={setField("top_k")}
            />
          </div>
          <div className="flex-1">
            <label className="mb-1 block text-xs font-medium text-slate-500 dark:text-muted-foreground">
              Semantic Config{" "}
              <span className="text-slate-400 dark:text-muted-foreground/60">(optional)</span>
            </label>
            <Input
              value={config.semantic_config}
              onChange={setField("semantic_config")}
              placeholder="my-semantic-config"
            />
          </div>
        </div>
      </div>
    </Modal>
  );
}
