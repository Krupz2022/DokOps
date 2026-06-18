import { useState } from "react";
import api from "../lib/api";
import { useToast } from "../context/ToastContext";
import { Button } from "./ui/Button";
import { Input } from "./ui/Input";
import { Modal } from "./ui/Modal";
import { Loader2, Info } from "lucide-react";

type Provider = "azure_ai_search" | "qdrant" | "pinecone" | "weaviate" | "opensearch" | "chroma";

const PROVIDER_LABELS: Record<Provider, string> = {
  azure_ai_search: "Azure AI Search",
  qdrant: "Qdrant",
  pinecone: "Pinecone",
  weaviate: "Weaviate",
  opensearch: "OpenSearch",
  chroma: "Chroma",
};

const DEFAULT_CONFIGS: Record<Provider, Record<string, string | number>> = {
  azure_ai_search: { endpoint: "", api_key: "", index_name: "", top_k: 3, semantic_config: "" },
  qdrant:          { endpoint: "", api_key: "", collection_name: "", text_field: "content", top_k: 3 },
  pinecone:        { index_host: "", api_key: "", namespace: "", metadata_text_field: "text", top_k: 3 },
  weaviate:        { endpoint: "", api_key: "", collection_name: "", text_property: "content", top_k: 3 },
  opensearch:      { endpoint: "", username: "", password: "", index_name: "", text_field: "content", top_k: 3 },
  chroma:          { endpoint: "", api_token: "", collection_name: "", top_k: 3 },
};

interface ExternalKnowledgeSource {
  id: string;
  name: string;
  provider: string;
  enabled: boolean;
  config: Record<string, string | number>;
  created_at: string;
}

interface Props {
  editing?: ExternalKnowledgeSource | null;
  onClose: () => void;
  onSaved: () => void;
}

function FieldLabel({ children, optional }: { children: React.ReactNode; optional?: boolean }) {
  return (
    <label className="mb-1 block text-xs font-medium text-slate-500 dark:text-muted-foreground">
      {children}
      {optional && <span className="ml-1 text-slate-400 dark:text-muted-foreground/60">(optional)</span>}
    </label>
  );
}

function EmbedNote() {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-amber-200 dark:border-amber-500/20 bg-amber-50 dark:bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
      <Info className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
      Query embedding uses the DokOps embedding service (Settings → AI). Ensure it is configured.
    </div>
  );
}

export default function AddKnowledgeSourceModal({ editing, onClose, onSaved }: Props) {
  const { toast } = useToast();
  const [name, setName] = useState(editing?.name ?? "");
  const [provider, setProvider] = useState<Provider>((editing?.provider as Provider) ?? "azure_ai_search");
  const [config, setConfig] = useState<Record<string, string | number>>(
    editing ? { ...DEFAULT_CONFIGS[editing.provider as Provider], ...editing.config } : DEFAULT_CONFIGS["azure_ai_search"]
  );
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const isEditing = !!editing;

  function handleProviderChange(p: Provider) {
    setProvider(p);
    setConfig(DEFAULT_CONFIGS[p]);
  }

  function setField(key: string) {
    return (e: React.ChangeEvent<HTMLInputElement>) =>
      setConfig((c) => ({ ...c, [key]: key === "top_k" ? Number(e.target.value) : e.target.value }));
  }

  async function handleTest() {
    setTesting(true);
    try {
      await api.post("/knowledge-sources/test-config", { provider, config });
      toast("Connection successful!", "success");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast(msg ?? "Connection failed.", "error");
    } finally {
      setTesting(false);
    }
  }

  async function handleSave() {
    if (!name) { toast("Name is required.", "error"); return; }
    setSaving(true);
    try {
      const payload = { name, provider, config };
      if (editing) {
        await api.put(`/knowledge-sources/${editing.id}`, payload);
      } else {
        await api.post("/knowledge-sources", payload);
      }
      toast(`Knowledge source ${editing ? "updated" : "created"}.`, "success");
      onSaved();
      onClose();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast(msg ?? "Save failed.", "error");
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
        {/* Provider selector */}
        <div>
          <FieldLabel>Provider</FieldLabel>
          {isEditing ? (
            <div className="rounded-lg border border-slate-200 dark:border-border bg-slate-50 dark:bg-muted/50 px-3 py-2 text-sm text-slate-700 dark:text-slate-300">
              {PROVIDER_LABELS[provider]}
            </div>
          ) : (
            <select
              value={provider}
              onChange={(e) => handleProviderChange(e.target.value as Provider)}
              className="w-full rounded-lg border border-slate-200 dark:border-border bg-white dark:bg-card text-slate-900 dark:text-foreground text-sm px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50"
            >
              {(Object.keys(PROVIDER_LABELS) as Provider[]).map((p) => (
                <option key={p} value={p}>{PROVIDER_LABELS[p]}</option>
              ))}
            </select>
          )}
        </div>

        {/* Common: Name */}
        <div>
          <FieldLabel>Name *</FieldLabel>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Company Wiki" />
        </div>

        {/* Azure AI Search */}
        {provider === "azure_ai_search" && (
          <>
            <div>
              <FieldLabel>Endpoint URL *</FieldLabel>
              <Input value={String(config.endpoint ?? "")} onChange={setField("endpoint")} placeholder="https://your-search.search.windows.net" />
            </div>
            <div>
              <FieldLabel>API Key *{isEditing && " (leave blank to keep existing)"}</FieldLabel>
              <Input type="password" value={String(config.api_key ?? "")} onChange={setField("api_key")} placeholder={isEditing ? "••••••" : "your-api-key"} />
            </div>
            <div>
              <FieldLabel>Index Name(s) *</FieldLabel>
              <Input value={String(config.index_name ?? "")} onChange={setField("index_name")} placeholder="company-kb, ops-kb" />
            </div>
            <div className="flex gap-3">
              <div className="flex-1">
                <FieldLabel>Top-K Results</FieldLabel>
                <Input type="number" min={1} max={10} value={Number(config.top_k ?? 3)} onChange={setField("top_k")} />
              </div>
              <div className="flex-1">
                <FieldLabel optional>Semantic Config</FieldLabel>
                <Input value={String(config.semantic_config ?? "")} onChange={setField("semantic_config")} placeholder="my-semantic-config" />
              </div>
            </div>
          </>
        )}

        {/* Qdrant */}
        {provider === "qdrant" && (
          <>
            <EmbedNote />
            <div>
              <FieldLabel>Endpoint URL *</FieldLabel>
              <Input value={String(config.endpoint ?? "")} onChange={setField("endpoint")} placeholder="https://xyz.qdrant.tech" />
            </div>
            <div>
              <FieldLabel>API Key *{isEditing && " (leave blank to keep existing)"}</FieldLabel>
              <Input type="password" value={String(config.api_key ?? "")} onChange={setField("api_key")} placeholder={isEditing ? "••••••" : "your-api-key"} />
            </div>
            <div>
              <FieldLabel>Collection Name(s) *</FieldLabel>
              <Input value={String(config.collection_name ?? "")} onChange={setField("collection_name")} placeholder="company-kb, ops-kb" />
            </div>
            <div className="flex gap-3">
              <div className="flex-1">
                <FieldLabel>Text Field</FieldLabel>
                <Input value={String(config.text_field ?? "content")} onChange={setField("text_field")} placeholder="content" />
              </div>
              <div className="flex-1">
                <FieldLabel>Top-K Results</FieldLabel>
                <Input type="number" min={1} max={10} value={Number(config.top_k ?? 3)} onChange={setField("top_k")} />
              </div>
            </div>
          </>
        )}

        {/* Pinecone */}
        {provider === "pinecone" && (
          <>
            <EmbedNote />
            <div>
              <FieldLabel>Index Host *</FieldLabel>
              <Input value={String(config.index_host ?? "")} onChange={setField("index_host")} placeholder="https://my-index-xyz.svc.pinecone.io" />
            </div>
            <div>
              <FieldLabel>API Key *{isEditing && " (leave blank to keep existing)"}</FieldLabel>
              <Input type="password" value={String(config.api_key ?? "")} onChange={setField("api_key")} placeholder={isEditing ? "••••••" : "your-api-key"} />
            </div>
            <div className="flex gap-3">
              <div className="flex-1">
                <FieldLabel optional>Namespace</FieldLabel>
                <Input value={String(config.namespace ?? "")} onChange={setField("namespace")} placeholder="(default)" />
              </div>
              <div className="flex-1">
                <FieldLabel>Metadata Text Field</FieldLabel>
                <Input value={String(config.metadata_text_field ?? "text")} onChange={setField("metadata_text_field")} placeholder="text" />
              </div>
            </div>
            <div>
              <FieldLabel>Top-K Results</FieldLabel>
              <Input type="number" min={1} max={10} value={Number(config.top_k ?? 3)} onChange={setField("top_k")} />
            </div>
          </>
        )}

        {/* Weaviate */}
        {provider === "weaviate" && (
          <>
            <div>
              <FieldLabel>Endpoint URL *</FieldLabel>
              <Input value={String(config.endpoint ?? "")} onChange={setField("endpoint")} placeholder="https://my-cluster.weaviate.network" />
            </div>
            <div>
              <FieldLabel>API Key *{isEditing && " (leave blank to keep existing)"}</FieldLabel>
              <Input type="password" value={String(config.api_key ?? "")} onChange={setField("api_key")} placeholder={isEditing ? "••••••" : "your-api-key"} />
            </div>
            <div>
              <FieldLabel>Collection Name(s) *</FieldLabel>
              <Input value={String(config.collection_name ?? "")} onChange={setField("collection_name")} placeholder="CompanyDocs, OpsKB" />
            </div>
            <div className="flex gap-3">
              <div className="flex-1">
                <FieldLabel>Text Property *</FieldLabel>
                <Input value={String(config.text_property ?? "content")} onChange={setField("text_property")} placeholder="content" />
              </div>
              <div className="flex-1">
                <FieldLabel>Top-K Results</FieldLabel>
                <Input type="number" min={1} max={10} value={Number(config.top_k ?? 3)} onChange={setField("top_k")} />
              </div>
            </div>
          </>
        )}

        {/* OpenSearch */}
        {provider === "opensearch" && (
          <>
            <div>
              <FieldLabel>Endpoint URL *</FieldLabel>
              <Input value={String(config.endpoint ?? "")} onChange={setField("endpoint")} placeholder="https://my-opensearch.example.com" />
            </div>
            <div className="flex gap-3">
              <div className="flex-1">
                <FieldLabel>Username *</FieldLabel>
                <Input value={String(config.username ?? "")} onChange={setField("username")} placeholder="admin" />
              </div>
              <div className="flex-1">
                <FieldLabel>Password *{isEditing && " (leave blank to keep)"}</FieldLabel>
                <Input type="password" value={String(config.password ?? "")} onChange={setField("password")} placeholder={isEditing ? "••••••" : "password"} />
              </div>
            </div>
            <div>
              <FieldLabel>Index Name(s) *</FieldLabel>
              <Input value={String(config.index_name ?? "")} onChange={setField("index_name")} placeholder="company-kb, ops-kb" />
            </div>
            <div className="flex gap-3">
              <div className="flex-1">
                <FieldLabel>Text Field</FieldLabel>
                <Input value={String(config.text_field ?? "content")} onChange={setField("text_field")} placeholder="content" />
              </div>
              <div className="flex-1">
                <FieldLabel>Top-K Results</FieldLabel>
                <Input type="number" min={1} max={10} value={Number(config.top_k ?? 3)} onChange={setField("top_k")} />
              </div>
            </div>
          </>
        )}

        {/* Chroma */}
        {provider === "chroma" && (
          <>
            <div>
              <FieldLabel>Endpoint URL *</FieldLabel>
              <Input value={String(config.endpoint ?? "")} onChange={setField("endpoint")} placeholder="http://chroma-host:8000" />
            </div>
            <div>
              <FieldLabel optional>API Token</FieldLabel>
              <Input type="password" value={String(config.api_token ?? "")} onChange={setField("api_token")} placeholder="(leave blank if auth disabled)" />
            </div>
            <div>
              <FieldLabel>Collection Name(s) *</FieldLabel>
              <Input value={String(config.collection_name ?? "")} onChange={setField("collection_name")} placeholder="company-kb, ops-kb" />
            </div>
            <div>
              <FieldLabel>Top-K Results</FieldLabel>
              <Input type="number" min={1} max={10} value={Number(config.top_k ?? 3)} onChange={setField("top_k")} />
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
