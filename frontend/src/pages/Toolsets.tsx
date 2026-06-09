import { useState, useEffect, useRef } from "react";
import { CLIToolsTab } from "./CLIToolsTab";
import {
    Wrench,
    Plus,
    Save,
    ShieldCheck,
    AlertCircle,
    Info,
    ChevronRight,
    Search,
    Trash2,
    Key,
    Eye,
    EyeOff,
    Upload,
    FileJson,
    CheckCircle2,
    RefreshCw,
    Lock,
    Zap,
    ChevronDown,
} from "lucide-react";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { Modal } from "../components/ui/Modal";
import { SkeletonCard } from "../components/ui/Skeleton";
import { EmptyState } from "../components/ui/EmptyState";
import { useToast } from "../context/ToastContext";
import { useConfirm } from "../context/ConfirmContext";
import api from "../lib/api";

interface Toolset {
    id: string;
    [key: string]: any;
}

interface EnvVar {
    key: string;
    value_masked: string;
}

interface BuiltInTool {
    name: string;
    description: string;
    inputs: string[];
    operation_type: string;
    requires_confirmation: boolean;
    risk_level: string;
}

interface ServiceTool {
    name: string;
    description: string;
    god_mode: boolean;
    script?: string;
    command?: string;
}

interface ServiceToolset {
    id: string;
    builtin: boolean;
    [key: string]: any;
}

interface MCPToolItem {
    id: string;
    server_id: string;
    name: string;
    description: string;
    input_schema: string;
    confirmation_override: boolean | null;
    namespaced_name: string;
    requires_confirmation: boolean;
    server_name?: string;
}

interface MCPServerSummary {
    id: string;
    name: string;
    is_connected: boolean;
    tools: MCPToolItem[];
}

export default function Toolsets() {
    const { toast } = useToast();
    const { confirm } = useConfirm();

    const [toolsets, setToolsets] = useState<Toolset[]>([]);
    const [builtinTools, setBuiltinTools] = useState<BuiltInTool[]>([]);
    const [serviceToolsets, setServiceToolsets] = useState<ServiceToolset[]>([]);
    const [activeTab, setActiveTab] = useState<"custom" | "service" | "builtin" | "mcp" | "cli">("custom");
    const [serviceSearchQuery, setServiceSearchQuery] = useState("");
    const [expandedService, setExpandedService] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [searchQuery, setSearchQuery] = useState("");
    
    // Editor state
    const [isEditing, setIsEditing] = useState(false);
    const [editId, setEditId] = useState("");
    const [editContent, setEditContent] = useState("");
    const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "success" | "error">("idle");

    // Env vars state
    const [envVars, setEnvVars] = useState<EnvVar[]>([]);
    const [newEnvKey, setNewEnvKey] = useState("");
    const [newEnvValue, setNewEnvValue] = useState("");
    const [envSaving, setEnvSaving] = useState(false);
    const [showEnvValue, setShowEnvValue] = useState(false);

    const [builtinSearchQuery, setBuiltinSearchQuery] = useState("");
    const [mcpServers, setMcpServers] = useState<MCPServerSummary[]>([]);
    const [mcpSearchQuery, setMcpSearchQuery] = useState("");
    const [mcpRefreshingId, setMcpRefreshingId] = useState<string | null>(null);

    // Bulk import state
    const [isBulkImportOpen, setIsBulkImportOpen] = useState(false);
    const [bulkJson, setBulkJson] = useState("");
    const [bulkResult, setBulkResult] = useState<{imported: number; errors: string[]} | null>(null);
    const [bulkImporting, setBulkImporting] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        fetchToolsets();
        fetchEnvVars();
        fetchMcpTools();
    }, []);

    const fetchToolsets = async () => {
        try {
            setLoading(true);
            const [tsRes, biRes, svcRes] = await Promise.all([
                api.get("/tools/toolsets"),
                api.get("/tools/builtin"),
                api.get("/tools/builtin-toolsets"),
            ]);
            setToolsets(tsRes.data);
            setBuiltinTools(biRes.data);
            setServiceToolsets(svcRes.data as ServiceToolset[]);
            setError(null);
        } catch (err: any) {
            setError(err.response?.data?.detail || "Failed to load toolsets");
        } finally {
            setLoading(false);
        }
    };

    const fetchEnvVars = async () => {
        try {
            const res = await api.get("/tools/env-vars");
            setEnvVars(res.data);
        } catch (err) {
            console.error("Failed to load env vars", err);
        }
    };

    const fetchMcpTools = async () => {
        try {
            const serversRes = await api.get("/mcp/servers");
            const svrList = serversRes.data as Array<{ id: string; name: string; is_connected: boolean }>;
            const summaries: MCPServerSummary[] = await Promise.all(
                svrList.map(async (s) => {
                    try {
                        const toolsRes = await api.get(`/mcp/servers/${s.id}/tools`);
                        return {
                            id: s.id,
                            name: s.name,
                            is_connected: s.is_connected,
                            tools: (toolsRes.data as MCPToolItem[]).map(t => ({ ...t, server_name: s.name })),
                        };
                    } catch {
                        return { id: s.id, name: s.name, is_connected: s.is_connected, tools: [] };
                    }
                })
            );
            setMcpServers(summaries);
        } catch { /* silently fail */ }
    };

    const handleAddEnvVar = async () => {
        if (!newEnvKey.trim() || !newEnvValue.trim()) return;
        setEnvSaving(true);
        try {
            await api.post("/tools/env-vars", { key: newEnvKey, value: newEnvValue });
            setNewEnvKey("");
            setNewEnvValue("");
            fetchEnvVars();
        } catch (err: any) {
            toast(err.response?.data?.detail || "Failed to save variable", "error");
        } finally {
            setEnvSaving(false);
        }
    };

    const handleDeleteEnvVar = async (key: string) => {
        const ok = await confirm({
            title: "Delete Variable",
            description: `Delete variable ${key}? This cannot be undone.`,
            variant: "danger",
            confirmLabel: "Delete",
        });
        if (!ok) return;
        try {
            await api.delete(`/tools/env-vars/${key}`);
            fetchEnvVars();
        } catch (err: any) {
            toast(err.response?.data?.detail || "Failed to delete variable", "error");
        }
    };

    const handleBulkImport = async () => {
        if (!bulkJson.trim()) return;
        setBulkImporting(true);
        setBulkResult(null);
        try {
            // Handle .env format (KEY=VALUE per line)
            let parsed: Record<string, string>;
            const trimmed = bulkJson.trim();
            if (trimmed.startsWith("{")) {
                parsed = JSON.parse(trimmed);
            } else {
                // .env format
                parsed = {};
                trimmed.split("\n").forEach(line => {
                    const l = line.trim();
                    if (!l || l.startsWith("#")) return;
                    const eqIdx = l.indexOf("=");
                    if (eqIdx > 0) {
                        const key = l.slice(0, eqIdx).trim();
                        let val = l.slice(eqIdx + 1).trim();
                        // Strip surrounding quotes
                        if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
                            val = val.slice(1, -1);
                        }
                        parsed[key] = val;
                    }
                });
            }
            const res = await api.post("/tools/env-vars/bulk", parsed);
            setBulkResult({ imported: res.data.imported, errors: res.data.errors || [] });
            fetchEnvVars();
        } catch (err: any) {
            setBulkResult({ imported: 0, errors: [err.response?.data?.detail || "Invalid JSON format"] });
        } finally {
            setBulkImporting(false);
        }
    };

    const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
            setBulkJson(ev.target?.result as string || "");
            setBulkResult(null);
        };
        reader.readAsText(file);
        // Reset so same file can be re-uploaded
        e.target.value = "";
    };

    const handleSave = async () => {
        if (!editId || !editContent) return;
        try {
            setSaveStatus("saving");
            await api.post(`/tools/toolsets/${editId}`, editContent, {
                headers: { "Content-Type": "text/plain" }
            });
            setSaveStatus("success");
            setTimeout(() => setSaveStatus("idle"), 3000);
            fetchToolsets();
            setIsEditing(false);
        } catch (err) {
            setSaveStatus("error");
        }
    };

    const openCreateModal = () => {
        setEditId("new_toolset");
        setEditContent(`my_custom_toolset:
  description: "Custom tools for Kubernetes inspection"
  tools:
    - name: fetch_logs
      description: "Fetch recent logs for the target pod"
      command: "kubectl logs {{ name }} -n {{ namespace }} --tail=100"
    - name: check_disk
      description: "Check disk space inside the container"
      script: |
        kubectl exec {{ name }} -n {{ namespace }} -- df -h`);
        setIsEditing(true);
    };

    const openEditModal = async (ts: Toolset) => {
        setEditId(ts.id);
        try {
            const res = await api.get(`/tools/toolsets/${ts.id}/raw`);
            setEditContent(res.data);
        } catch (e) {
            setEditContent("# Error loading YAML - check backend connection");
        }
        setIsEditing(true);
    };

    const filteredToolsets = toolsets
        .filter(ts => {
            const name = Object.keys(ts).find(k => k !== "id") || "";
            return name.toLowerCase().includes(searchQuery.toLowerCase());
        })
        .sort((a, b) => {
            // helm_toolset appears first as the featured default
            if (a.id === "helm_toolset") return -1;
            if (b.id === "helm_toolset") return 1;
            return a.id.localeCompare(b.id);
        });

    return (
        <div className="flex flex-col h-full">
            {/* Header */}
            <div className="flex-shrink-0 px-6 py-4 flex items-center justify-between border-b border-border/60">
                <div>
                    <h1 className="text-base font-semibold text-foreground tracking-tight">Toolsets</h1>
                    <p className="text-xs text-muted-foreground font-mono mt-0.5">AI tool configurations and environment variables</p>
                </div>
                <Button onClick={openCreateModal} size="sm" className="h-8">
                    <Plus className="w-4 h-4 mr-1.5" />
                    New Toolset
                </Button>
            </div>
            <div className="flex-1 overflow-y-auto p-6">
            <div className="space-y-6">

            {/* Error */}
            {error && (
                <div className="p-4 border border-red-200 dark:border-red-800 rounded-lg bg-red-50 dark:bg-red-950/40 text-red-800 dark:text-red-400 flex items-center gap-3">
                    <AlertCircle className="w-5 h-5" />
                    <p className="text-sm font-medium">{error}</p>
                </div>
            )}

            {/* Info Banner */}
            <div className="p-3 bg-primary/5 rounded-lg border border-primary/15">
                <div className="flex gap-3 items-start">
                    <Info className="w-4 h-4 text-primary/70 mt-0.5 flex-shrink-0" />
                    <p className="text-xs text-muted-foreground leading-relaxed">
                        Toolsets map any shell-invocable command — <code className="bg-primary/10 text-primary px-1 rounded font-mono">kubectl</code>, <code className="bg-primary/10 text-primary px-1 rounded font-mono">helm</code>, <code className="bg-primary/10 text-primary px-1 rounded font-mono">bash</code>, or any CLI — to natural language tools the AI agent can invoke.
                        Use <code className="bg-primary/10 text-primary px-1 rounded font-mono">$VAR_NAME</code> in commands to reference environment variables defined below.
                    </p>
                </div>
            </div>

            {/* ─── Environment Variables Section ─── */}
            <Card>
                <CardHeader className="flex flex-row items-center justify-between pb-2">
                    <CardTitle className="text-lg font-bold flex items-center gap-2">
                        <Key className="w-5 h-5 text-primary" />
                        Environment Variables
                    </CardTitle>
                    <div className="flex items-center gap-2">
                        <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded border">
                            {envVars.length} defined
                        </span>
                        <Button size="sm" variant="outline" onClick={() => { setIsBulkImportOpen(true); setBulkJson(""); setBulkResult(null); }} className="h-7 text-xs">
                            <Upload className="w-3 h-3 mr-1" />
                            Import
                        </Button>
                    </div>
                </CardHeader>
                <CardContent>
                    <p className="text-xs text-muted-foreground mb-4">
                        These variables are injected into all toolset commands at runtime. Use <code className="bg-muted px-1 rounded">$VAR_NAME</code> syntax in your YAML commands.
                    </p>

                    {/* Existing Vars Table */}
                    {envVars.length > 0 && (
                        <table className="w-full text-sm mb-4">
                            <thead className="border-b">
                                <tr>
                                    <th className="p-3 text-left text-xs font-semibold text-muted-foreground uppercase">Variable</th>
                                    <th className="p-3 text-left text-xs font-semibold text-muted-foreground uppercase">Value</th>
                                    <th className="p-3 text-right text-xs font-semibold text-muted-foreground uppercase">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {envVars.map(ev => (
                                    <tr key={ev.key} className="border-b hover:bg-muted/50">
                                        <td className="p-3 font-mono text-xs font-semibold">${ev.key}</td>
                                        <td className="p-3 font-mono text-xs text-muted-foreground">{ev.value_masked}</td>
                                        <td className="p-3 text-right">
                                            <Button size="sm" variant="destructive" onClick={() => handleDeleteEnvVar(ev.key)}>
                                                <Trash2 className="w-3 h-3" />
                                            </Button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}

                    {/* Add New Var Form */}
                    <div className="flex gap-2 items-end">
                        <div className="flex-1 space-y-1">
                            <label className="text-[10px] font-bold uppercase text-muted-foreground">Name</label>
                            <Input 
                                placeholder="KUBE_CONTEXT" 
                                value={newEnvKey} 
                                onChange={e => setNewEnvKey(e.target.value.replace(/\s+/g, "_").toUpperCase())}
                                className="font-mono text-sm"
                            />
                        </div>
                        <div className="flex-[2] space-y-1">
                            <label className="text-[10px] font-bold uppercase text-muted-foreground">Value</label>
                            <div className="relative">
                                <Input 
                                    type={showEnvValue ? "text" : "password"} 
                                    placeholder="my-cluster-context" 
                                    value={newEnvValue} 
                                    onChange={e => setNewEnvValue(e.target.value)}
                                    className="font-mono text-sm !pr-12"
                                />
                                <button 
                                    type="button"
                                    onClick={() => setShowEnvValue(!showEnvValue)} 
                                    className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                                >
                                    {showEnvValue ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                                </button>
                            </div>
                        </div>
                        <Button onClick={handleAddEnvVar} disabled={envSaving || !newEnvKey.trim() || !newEnvValue.trim()}>
                            <Plus className="w-4 h-4 mr-1" />
                            Add
                        </Button>
                    </div>
                </CardContent>
            </Card>

            {/* Bulk Import Modal */}
            <Modal isOpen={isBulkImportOpen} onClose={() => setIsBulkImportOpen(false)} title="Import Environment Variables" className="max-w-xl">
                <div className="space-y-4 pt-2">
                    <p className="text-sm text-muted-foreground">
                        Paste JSON or <code className="bg-muted px-1 rounded">.env</code> format below, or upload a file.
                    </p>

                    {/* Format reference */}
                    <div className="grid grid-cols-2 gap-3 bg-muted/30 p-3 rounded-lg border border-dashed">
                        <div className="space-y-1">
                            <h4 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">JSON Format</h4>
                            <pre className="text-[11px] text-primary bg-primary/5 p-2 rounded border border-primary/10">{`{\n  "DB_HOST": "prod-db.aws.com",\n  "DB_PASS": "s3cr3t",\n  "API_KEY": "abc123"\n}`}</pre>
                        </div>
                        <div className="space-y-1">
                            <h4 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">.env Format</h4>
                            <pre className="text-[11px] text-primary bg-primary/5 p-2 rounded border border-primary/10">{`DB_HOST=prod-db.aws.com\nDB_PASS="s3cr3t"\nAPI_KEY=abc123\n# Comments are ignored`}</pre>
                        </div>
                    </div>

                    {/* File upload */}
                    <div className="flex gap-2 items-center">
                        <input ref={fileInputRef} type="file" accept=".json,.env,.txt" className="hidden" onChange={handleFileUpload} />
                        <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()} className="text-xs">
                            <FileJson className="w-3 h-3 mr-1" />
                            Upload .json / .env file
                        </Button>
                        {bulkJson && <span className="text-xs text-muted-foreground">Content loaded ✓</span>}
                    </div>

                    {/* Textarea */}
                    <textarea
                        className="w-full h-48 p-4 border rounded-lg font-mono text-xs bg-muted/20 focus:ring-2 focus:ring-primary focus:outline-none transition-all"
                        placeholder='{\n  "KUBE_CONTEXT": "prod-cluster",\n  "DB_PASSWORD": "my-secret-pass"\n}'
                        value={bulkJson}
                        onChange={e => { setBulkJson(e.target.value); setBulkResult(null); }}
                        spellCheck={false}
                    />

                    {/* Result */}
                    {bulkResult && (
                        <div className={`p-3 rounded-lg text-sm flex items-start gap-2 ${
                            bulkResult.errors.length > 0 && bulkResult.imported === 0
                                ? "bg-red-50 dark:bg-red-950/40 text-red-800 dark:text-red-400 border border-red-200 dark:border-red-800"
                                : "bg-green-50 dark:bg-green-950/40 text-green-800 dark:text-green-400 border border-green-200 dark:border-green-800"
                        }`}>
                            {bulkResult.imported > 0 ? (
                                <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
                            ) : (
                                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                            )}
                            <div>
                                <p className="font-medium">{bulkResult.imported} variable(s) imported.</p>
                                {bulkResult.errors.map((err, i) => <p key={i} className="text-xs opacity-80">{err}</p>)}
                            </div>
                        </div>
                    )}

                    {/* Actions */}
                    <div className="flex justify-end gap-3 pt-2">
                        <Button variant="ghost" onClick={() => setIsBulkImportOpen(false)}>Cancel</Button>
                        <Button onClick={handleBulkImport} disabled={bulkImporting || !bulkJson.trim()}>
                            {bulkImporting ? "Importing..." : "Import Variables"}
                        </Button>
                    </div>
                </div>
            </Modal>

            {/* Tabs */}
            <div className="border-b border-border flex gap-0 -mb-px">
                {(["custom", "service", "builtin", "mcp", "cli"] as const).map((tab, i) => {
                    const labels = ["Custom Toolsets", "Service Toolsets", "Built-in Tools", "MCP Tools", "CLI Tools"];
                    const isActive = activeTab === tab;
                    return (
                        <button
                            key={tab}
                            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                                isActive
                                    ? "border-primary text-primary"
                                    : "border-transparent text-muted-foreground hover:text-foreground"
                            }`}
                            onClick={() => { setActiveTab(tab); if (tab === "mcp") fetchMcpTools(); }}
                        >
                            {labels[i]}
                            {tab === "service" && serviceToolsets.length > 0 && (
                                <span className="ml-1.5 text-[9px] bg-cyan-500/15 text-cyan-400 border border-cyan-500/20 px-1 py-0.5 rounded font-mono">
                                    {serviceToolsets.length}
                                </span>
                            )}
                        </button>
                    );
                })}
            </div>

            {/* Custom Toolsets View */}
            {activeTab === "custom" && (
                <div className="space-y-6 pt-4">
                    {/* Search */}
                    <div className="relative w-64">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                        <Input 
                            className="pl-10"
                            placeholder="Search toolsets..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                        />
                    </div>

                    {/* Toolset Grid */}
                    {loading ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                            {[1, 2, 3].map(i => <SkeletonCard key={i} />)}
                        </div>
                    ) : filteredToolsets.length === 0 ? (
                        <EmptyState
                            icon={Wrench}
                            title="No toolsets found"
                            description="Get started by creating your first custom toolset."
                            actionLabel="Create Toolset"
                            onAction={openCreateModal}
                        />
                    ) : (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                            {filteredToolsets.map((ts) => {
                                const toolsetName = Object.keys(ts).find(k => k !== "id") || "Unknown";
                                const data = ts[toolsetName];
                                const isDefault = ts.id === "helm_toolset";
                                const hasDestructive = data?.tools?.some((t: any) =>
                                    t.description?.toUpperCase().includes("DESTRUCTIVE")
                                );
                                return (
                                    <Card key={ts.id} className="hover:shadow-md transition-shadow relative overflow-hidden">
                                        {isDefault && (
                                            <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-cyan-400 via-primary to-sky-500" />
                                        )}
                                        <CardHeader className="flex flex-row items-center justify-between pb-2 pt-4">
                                            <div className="flex items-center gap-2 min-w-0">
                                                <CardTitle className="text-lg font-bold truncate">
                                                    {toolsetName.replace(/_/g, " ")}
                                                </CardTitle>
                                                {isDefault && (
                                                    <span className="shrink-0 text-[9px] font-bold uppercase tracking-wider text-primary bg-primary/10 border border-primary/20 px-1.5 py-0.5 rounded font-mono">
                                                        default
                                                    </span>
                                                )}
                                            </div>
                                            <span className="shrink-0 text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded border ml-2">
                                                {ts.id}.yaml
                                            </span>
                                        </CardHeader>
                                        <CardContent>
                                            <p className="text-sm text-muted-foreground mb-3 h-10 line-clamp-2">
                                                {data?.description || "No description provided."}
                                            </p>

                                            {/* Badges */}
                                            {hasDestructive && (
                                                <div className="flex items-center gap-2 mb-3">
                                                    <span className="inline-flex items-center gap-1 text-[9px] font-semibold uppercase tracking-wider text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-950/30 border border-orange-200 dark:border-orange-800/50 px-1.5 py-0.5 rounded">
                                                        <AlertCircle className="w-2.5 h-2.5" />
                                                        Has Destructive Ops
                                                    </span>
                                                </div>
                                            )}

                                            <div className="space-y-1 mb-4">
                                                {data?.tools?.slice(0, 3).map((tool: any, idx: number) => (
                                                    <div key={idx} className="text-xs bg-primary/5 text-primary p-2 rounded flex items-center gap-2 border border-primary/10">
                                                        <span className="w-4 h-4 bg-primary text-primary-foreground rounded-full flex items-center justify-center text-[8px] font-bold">{idx+1}</span>
                                                        <span className="font-medium">{tool.name}</span>
                                                    </div>
                                                ))}
                                                {data?.tools?.length > 3 && (
                                                    <p className="text-[10px] text-muted-foreground pl-1">+{data.tools.length - 3} more tools</p>
                                                )}
                                            </div>

                                            <Button
                                                variant="outline"
                                                onClick={() => openEditModal(ts)}
                                                className="w-full"
                                            >
                                                Manage Toolset
                                                <ChevronRight className="w-4 h-4 ml-2 opacity-50" />
                                            </Button>
                                        </CardContent>
                                    </Card>
                                );
                            })}
                        </div>
                    )}
                </div>
            )}

            {/* Service Toolsets View */}
            {activeTab === "service" && (() => {
                const SERVICE_ICONS: Record<string, string> = {
                    rabbitmq: "/service-icons/rabbitmq.svg",
                    redis: "/service-icons/redis.svg",
                    postgres: "/service-icons/postgres.svg",
                    couchdb: "/service-icons/couchdb.svg",
                    mongodb: "/service-icons/mongodb.svg",
                    mysql: "/service-icons/mysql.svg",
                };
                const filtered = serviceToolsets.filter(ts => {
                    const svcName = Object.keys(ts).find(k => k !== "id" && k !== "builtin") || "";
                    return !serviceSearchQuery ||
                        svcName.toLowerCase().includes(serviceSearchQuery.toLowerCase()) ||
                        (ts[svcName]?.description || "").toLowerCase().includes(serviceSearchQuery.toLowerCase());
                });
                return (
                    <div className="space-y-4 pt-4">
                        <div className="flex items-center justify-between gap-4">
                            <div className="flex items-center gap-2">
                                <p className="text-sm text-muted-foreground">
                                    Read-only service toolsets shipped with DokOps. Credentials are resolved from <span className="font-mono text-xs bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 px-1 rounded">$VAULT:service:*</span> at runtime.
                                </p>
                                <span className="flex items-center gap-1 text-[10px] text-cyan-400 bg-cyan-500/10 border border-cyan-500/20 px-2 py-0.5 rounded-full font-medium shrink-0">
                                    <Zap className="w-2.5 h-2.5" /> Always active
                                </span>
                            </div>
                            <div className="relative w-56 flex-shrink-0">
                                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                                <Input className="pl-10" placeholder="Search services..." value={serviceSearchQuery} onChange={e => setServiceSearchQuery(e.target.value)} />
                            </div>
                        </div>

                        {loading ? (
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {[1,2,3,4].map(i => <SkeletonCard key={i} />)}
                            </div>
                        ) : (
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {filtered.map(ts => {
                                    const svcName = Object.keys(ts).find(k => k !== "id" && k !== "builtin") || ts.id;
                                    const data = ts[svcName] || {};
                                    const tools: ServiceTool[] = data.tools || [];
                                    const godModeTools = tools.filter(t => t.god_mode);
                                    const isExpanded = expandedService === ts.id;
                                    return (
                                        <Card key={ts.id} className="overflow-hidden">
                                            <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-cyan-500/60 to-blue-500/60" />
                                            <CardHeader className="pb-2 pt-4">
                                                <div className="flex items-center justify-between">
                                                    <div className="flex items-center gap-2">
                                                        {(() => { const ic = SERVICE_ICONS[ts.id]; return ic?.startsWith("/") ? <img src={ic} alt={ts.id} className="w-6 h-6 object-contain" /> : <span className="text-xl">{ic || "🔧"}</span>; })()}
                                                        <CardTitle className="text-base font-bold capitalize">{svcName}</CardTitle>
                                                        <span className="text-[9px] font-mono bg-secondary text-muted-foreground border border-border px-1.5 py-0.5 rounded">
                                                            {ts.id}.yaml
                                                        </span>
                                                    </div>
                                                    <div className="flex items-center gap-1.5">
                                                        {godModeTools.length > 0 && (
                                                            <span className="flex items-center gap-1 text-[9px] font-semibold uppercase text-orange-400 bg-orange-500/10 border border-orange-500/20 px-1.5 py-0.5 rounded">
                                                                <AlertCircle className="w-2.5 h-2.5" /> {godModeTools.length} god mode
                                                            </span>
                                                        )}
                                                        <span className="text-[9px] bg-secondary text-muted-foreground border border-border px-1.5 py-0.5 rounded font-mono">
                                                            {tools.length} tools
                                                        </span>
                                                    </div>
                                                </div>
                                            </CardHeader>
                                            <CardContent>
                                                <p className="text-xs text-muted-foreground mb-3 line-clamp-2">{data.description}</p>

                                                {/* Vault credential hint */}
                                                <div className="flex items-center gap-1.5 mb-3 p-2 rounded-md bg-secondary/50 border border-border">
                                                    <Lock className="w-3 h-3 text-cyan-400 shrink-0" />
                                                    <span className="text-[10px] font-mono text-muted-foreground truncate">
                                                        $VAULT:{ts.id}:host · $VAULT:{ts.id}:username · $VAULT:{ts.id}:password
                                                    </span>
                                                </div>

                                                {/* Tool list toggle */}
                                                <button
                                                    onClick={() => setExpandedService(isExpanded ? null : ts.id)}
                                                    className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors mb-2"
                                                >
                                                    <ChevronDown className={`w-3.5 h-3.5 transition-transform ${isExpanded ? "rotate-180" : ""}`} />
                                                    {isExpanded ? "Hide" : "Show"} tools
                                                </button>

                                                {isExpanded && (
                                                    <div className="space-y-1">
                                                        {tools.map(tool => (
                                                            <div key={tool.name} className={`flex items-start gap-2 text-xs p-2 rounded border ${
                                                                tool.god_mode
                                                                    ? "bg-orange-500/5 border-orange-500/20"
                                                                    : "bg-primary/5 border-primary/10"
                                                            }`}>
                                                                <span className={`shrink-0 mt-0.5 ${tool.god_mode ? "text-orange-400" : "text-primary"}`}>
                                                                    {tool.god_mode ? <ShieldCheck className="w-3 h-3" /> : <Zap className="w-3 h-3" />}
                                                                </span>
                                                                <div className="min-w-0">
                                                                    <span className={`font-mono font-semibold ${tool.god_mode ? "text-orange-400" : "text-primary"}`}>
                                                                        {tool.name}
                                                                    </span>
                                                                    <p className="text-muted-foreground text-[10px] mt-0.5 leading-relaxed">{tool.description}</p>
                                                                </div>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </CardContent>
                                        </Card>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                );
            })()}

            {/* Built-in Tools View */}
            {activeTab === "builtin" && (
                <div className="space-y-6 pt-4">
                    <div className="flex items-center justify-between gap-4">
                        <p className="text-sm text-muted-foreground">
                            These are the native Kubernetes tools instantly available to the Global AI Agent. Write operations will prompt you for secure confirmation before executing.
                        </p>
                        <div className="relative w-64 flex-shrink-0">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                            <Input
                                className="pl-10"
                                placeholder="Search built-in tools..."
                                value={builtinSearchQuery}
                                onChange={(e) => setBuiltinSearchQuery(e.target.value)}
                            />
                        </div>
                    </div>
                    {loading ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                            {[1, 2, 3, 4, 5, 6].map(i => <SkeletonCard key={i} />)}
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                            {builtinTools.filter(t =>
                                !builtinSearchQuery ||
                                t.name.toLowerCase().includes(builtinSearchQuery.toLowerCase()) ||
                                t.description.toLowerCase().includes(builtinSearchQuery.toLowerCase())
                            ).map((tool) => (
                                <Card key={tool.name} className="hover:shadow-md transition-shadow relative overflow-hidden">
                                    {tool.requires_confirmation && (
                                        <div className="absolute top-0 right-0 p-1.5 bg-orange-100 dark:bg-orange-950/40 text-orange-800 dark:text-orange-400 rounded-bl-lg flex items-center gap-1 border-b border-l border-orange-200 dark:border-orange-800 shadow-sm z-10">
                                            <ShieldCheck className="w-3 h-3" />
                                            <span className="text-[9px] font-bold uppercase tracking-wider">Requires Confirmation</span>
                                        </div>
                                    )}
                                    <CardHeader className="pb-2 relative pt-6 text-left">
                                        <CardTitle className="text-base font-bold flex items-center gap-2 text-foreground">
                                            {tool.name}
                                        </CardTitle>
                                    </CardHeader>
                                    <CardContent>
                                        <p className="text-xs text-muted-foreground mb-4 line-clamp-2 h-8">
                                            {tool.description}
                                        </p>
                                        <div className="flex flex-wrap gap-1 mt-auto">
                                            {tool.inputs && tool.inputs.length > 0 ? (
                                                tool.inputs.map(input => (
                                                    <span key={input} className="text-[9px] font-mono bg-muted/50 text-muted-foreground px-1.5 py-0.5 rounded border border-border">
                                                        {input}
                                                    </span>
                                                ))
                                            ) : (
                                                <span className="text-[9px] font-mono text-muted-foreground italic">No inputs required</span>
                                            )}
                                        </div>
                                    </CardContent>
                                </Card>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* MCP Tools View */}
            {activeTab === "mcp" && (
                <div className="space-y-6 pt-4">
                    <div className="flex items-center gap-3">
                        <Input
                            placeholder="Search MCP tools..."
                            value={mcpSearchQuery}
                            onChange={e => setMcpSearchQuery(e.target.value)}
                            className="max-w-xs"
                        />
                    </div>

                    {mcpServers.length === 0 ? (
                        <div className="text-center py-12">
                            <p className="text-slate-500 dark:text-muted-foreground text-sm">
                                No MCP servers configured.{" "}
                                <a href="/mcp-servers" className="text-blue-500 hover:underline">
                                    Configure MCP Servers →
                                </a>
                            </p>
                        </div>
                    ) : (
                        mcpServers.map(server => {
                            const filtered = server.tools.filter(t =>
                                !mcpSearchQuery ||
                                t.name.toLowerCase().includes(mcpSearchQuery.toLowerCase()) ||
                                t.description.toLowerCase().includes(mcpSearchQuery.toLowerCase())
                            );
                            if (filtered.length === 0 && mcpSearchQuery) return null;

                            return (
                                <div key={server.id}>
                                    <div className="flex items-center justify-between mb-3">
                                        <div className="flex items-center gap-2">
                                            <h3 className="font-semibold text-slate-800 dark:text-foreground">{server.name}</h3>
                                            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${server.is_connected ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" : "bg-slate-100 text-slate-500 dark:bg-muted dark:text-muted-foreground"}`}>
                                                {server.is_connected ? `${filtered.length} tools` : "disconnected"}
                                            </span>
                                        </div>
                                        <button
                                            className="text-slate-400 hover:text-blue-500 transition-colors disabled:opacity-40"
                                            disabled={mcpRefreshingId === server.id}
                                            onClick={async () => {
                                                setMcpRefreshingId(server.id);
                                                try {
                                                    await api.post(`/mcp/servers/${server.id}/refresh`);
                                                    await fetchMcpTools();
                                                    toast("Tools refreshed", "success");
                                                } catch {
                                                    toast("Refresh failed", "error");
                                                } finally {
                                                    setMcpRefreshingId(null);
                                                }
                                            }}
                                            title="Refresh tools from this server"
                                        >
                                            <RefreshCw className={`w-4 h-4 ${mcpRefreshingId === server.id ? "animate-spin" : ""}`} />
                                        </button>
                                    </div>

                                    {filtered.length === 0 && !mcpSearchQuery ? (
                                        <p className="text-sm text-slate-400 dark:text-muted-foreground italic pl-2">
                                            No tools discovered yet. Connect the server to fetch tools.
                                        </p>
                                    ) : (
                                        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                                            {filtered.map(tool => (
                                                <Card key={tool.id}>
                                                    <CardContent className="p-4 space-y-2">
                                                        <p className="font-mono text-xs font-semibold text-blue-600 dark:text-blue-400 break-all">{tool.namespaced_name}</p>
                                                        <p className="text-sm text-slate-600 dark:text-muted-foreground">{tool.description}</p>
                                                        <div className="flex items-center justify-between gap-2 pt-1">
                                                            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 dark:bg-muted text-slate-600 dark:text-muted-foreground">
                                                                {server.name}
                                                            </span>
                                                            <select
                                                                className="text-xs border rounded px-2 py-1 bg-background"
                                                                value={
                                                                    tool.confirmation_override === null ? "auto"
                                                                    : tool.confirmation_override ? "always"
                                                                    : "never"
                                                                }
                                                                onChange={async (e) => {
                                                                    const val = e.target.value;
                                                                    const override = val === "auto" ? null : val === "always";
                                                                    try {
                                                                        await api.put(`/mcp/servers/${server.id}/tools/${tool.name}/override`, {
                                                                            confirmation_override: override,
                                                                        });
                                                                        await fetchMcpTools();
                                                                        toast("Override saved", "success");
                                                                    } catch {
                                                                        toast("Failed to save override", "error");
                                                                    }
                                                                }}
                                                            >
                                                                <option value="auto">Auto</option>
                                                                <option value="always">Always confirm</option>
                                                                <option value="never">Never confirm</option>
                                                            </select>
                                                        </div>
                                                        {tool.requires_confirmation && (
                                                            <p className="text-xs text-amber-600 dark:text-amber-400">Requires confirmation</p>
                                                        )}
                                                    </CardContent>
                                                </Card>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            );
                        })
                    )}
                </div>
            )}

            {/* CLI Tools View */}
            {activeTab === "cli" && (
                <div className="pt-4">
                    <CLIToolsTab />
                </div>
            )}

            {/* Editor Modal */}
            <Modal isOpen={isEditing} onClose={() => setIsEditing(false)} title={`${editId === "new_toolset" ? "Create" : "Edit"} AI Toolset ⚙️`} className="max-w-3xl">
                <div className="space-y-6 pt-4">
                    <div className="grid grid-cols-1 gap-4">
                        {/* Toolset ID */}
                        <div className="space-y-2">
                            <label className="text-sm font-semibold text-foreground">Toolset ID (Filename)</label>
                            <Input 
                                placeholder="e.g. kubernetes_base" 
                                value={editId} 
                                onChange={e => setEditId(e.target.value.replace(/\s+/g, "_").toLowerCase())}
                                className="font-mono text-sm"
                            />
                            <p className="text-[10px] text-muted-foreground">Saved as <code className="bg-muted px-1 rounded">{editId}.yaml</code> on the server.</p>
                        </div>

                        {/* Reference Grid */}
                        <div className="grid grid-cols-2 gap-4 bg-muted/30 p-3 rounded-lg border border-dashed">
                            <div className="space-y-1">
                                <h4 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Template Variables</h4>
                                <ul className="text-[11px] space-y-1 text-primary">
                                    <li>• <code className="bg-primary/10 px-1 rounded">{"{{ name }}"}</code> — Pod Name</li>
                                    <li>• <code className="bg-primary/10 px-1 rounded">{"{{ namespace }}"}</code> — Namespace</li>
                                    <li>• <code className="bg-primary/10 px-1 rounded">{"{{ kind }}"}</code> — Resource Kind</li>
                                </ul>
                            </div>
                            <div className="space-y-1">
                                <h4 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Environment</h4>
                                <p className="text-[10px] leading-relaxed">
                                    Env vars defined above are injected at runtime. Use <code className="bg-muted px-1 rounded">$VAR_NAME</code> in commands.
                                </p>
                                {envVars.length > 0 && (
                                    <div className="flex flex-wrap gap-1 mt-1">
                                        {envVars.map(ev => (
                                            <span key={ev.key} className="text-[9px] bg-green-100 dark:bg-green-950/40 text-green-800 dark:text-green-400 px-1.5 py-0.5 rounded font-mono">${ev.key}</span>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* YAML Editor */}
                        <div className="space-y-2">
                            <label className="text-sm font-semibold text-foreground">YAML Definition</label>
                            <textarea 
                                className="w-full h-80 p-4 border rounded-lg font-mono text-xs bg-muted/20 focus:ring-2 focus:ring-primary focus:outline-none transition-all"
                                value={editContent}
                                onChange={e => setEditContent(e.target.value)}
                                spellCheck={false}
                            />
                        </div>
                    </div>

                    {/* Status + Actions */}
                    <div className="flex items-center justify-between pt-2">
                        <div className="text-sm">
                            {saveStatus === "saving" && <span className="text-primary animate-pulse">Saving...</span>}
                            {saveStatus === "success" && <span className="text-green-600 dark:text-green-400 flex items-center gap-1"><ShieldCheck className="w-4 h-4" /> Saved!</span>}
                            {saveStatus === "error" && <span className="text-red-600 dark:text-red-400 flex items-center gap-1"><AlertCircle className="w-4 h-4" /> Error — check YAML syntax</span>}
                        </div>
                        <div className="flex gap-3">
                            <Button variant="ghost" onClick={() => setIsEditing(false)}>Cancel</Button>
                            <Button onClick={handleSave} disabled={saveStatus === "saving"}>
                                <Save className="w-4 h-4 mr-2" />
                                Save Toolset
                            </Button>
                        </div>
                    </div>
                </div>
            </Modal>
            </div>
            </div>
        </div>
    );
}
