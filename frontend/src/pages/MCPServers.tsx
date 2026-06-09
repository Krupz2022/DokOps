// frontend/src/pages/MCPServers.tsx
import { useState, useEffect } from "react";
import { Plus, RefreshCw, Trash2, Edit2, CheckCircle2, XCircle, Loader2, Zap, Network } from "lucide-react";
import { Button } from "../components/ui/Button";
import { Card, CardContent } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { Modal } from "../components/ui/Modal";
import { useToast } from "../context/ToastContext";
import { useConfirm } from "../context/ConfirmContext";
import api from "../lib/api";

interface MCPServer {
    id: string;
    name: string;
    description: string;
    transport: "http" | "sse" | "stdio";
    url: string | null;
    command: string | null;
    args: string | null;
    auth_type: string;
    is_connected: boolean;
    last_connected_at: string | null;
}

interface MCPTool {
    id: string;
    server_id: string;
    name: string;
    description: string;
    namespaced_name: string;
    requires_confirmation: boolean;
    confirmation_override: boolean | null;
    last_synced_at: string | null;
}

const EMPTY_FORM = {
    name: "",
    description: "",
    transport: "http" as "http" | "sse" | "stdio",
    url: "",
    command: "",
    args: "",
    auth_type: "none",
    auth_value: "",
};

export default function MCPServers() {
    const { toast } = useToast();
    const { confirm } = useConfirm();

    const [servers, setServers] = useState<MCPServer[]>([]);
    const [toolCounts, setToolCounts] = useState<Record<string, number>>({});
    const [loading, setLoading] = useState(true);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingServer, setEditingServer] = useState<MCPServer | null>(null);
    const [form, setForm] = useState({ ...EMPTY_FORM });
    const [saving, setSaving] = useState(false);
    const [connectingId, setConnectingId] = useState<string | null>(null);

    useEffect(() => {
        fetchServers();
    }, []);

    const fetchServers = async () => {
        setLoading(true);
        try {
            const res = await api.get("/mcp/servers");
            const serverList: MCPServer[] = res.data;
            setServers(serverList);
            const counts: Record<string, number> = {};
            await Promise.all(
                serverList.filter(s => s.is_connected).map(async s => {
                    try {
                        const tr = await api.get(`/mcp/servers/${s.id}/tools`);
                        counts[s.id] = (tr.data as MCPTool[]).length;
                    } catch { /* ignore */ }
                })
            );
            setToolCounts(counts);
        } catch {
            toast("Failed to load MCP servers", "error");
        } finally {
            setLoading(false);
        }
    };

    const openAddModal = () => {
        setEditingServer(null);
        setForm({ ...EMPTY_FORM });
        setIsModalOpen(true);
    };

    const openEditModal = (server: MCPServer) => {
        setEditingServer(server);
        setForm({
            name: server.name,
            description: server.description,
            transport: server.transport,
            url: server.url || "",
            command: server.command || "",
            args: (() => {
                if (!server.args) return "";
                try { return JSON.parse(server.args).join(" "); }
                catch { return server.args; }
            })(),
            auth_type: server.auth_type,
            auth_value: "",
        });
        setIsModalOpen(true);
    };

    const handleSave = async () => {
        if (!form.name.trim()) {
            toast("Name is required", "error");
            return;
        }
        setSaving(true);
        try {
            const payload = {
                name: form.name,
                description: form.description,
                transport: form.transport,
                url: form.transport !== "stdio" ? form.url || null : null,
                command: form.transport === "stdio" ? form.command || null : null,
                args: form.transport === "stdio" ? form.args || null : null,
                auth_type: form.auth_type,
                auth_value: form.auth_value || null,
            };
            if (editingServer) {
                await api.put(`/mcp/servers/${editingServer.id}`, payload);
                toast("Server updated", "success");
            } else {
                const res = await api.post("/mcp/servers", payload);
                const connectResult = res.data.connect_result;
                if (connectResult?.connected) {
                    toast(`Connected — ${connectResult.tool_count} tools discovered`, "success");
                } else {
                    toast(`Saved but connection failed: ${connectResult?.error || "unknown"}`, "warning");
                }
            }
            setIsModalOpen(false);
            fetchServers();
        } catch (err: any) {
            toast(err.response?.data?.detail || "Failed to save server", "error");
        } finally {
            setSaving(false);
        }
    };

    const handleConnect = async (serverId: string) => {
        setConnectingId(serverId);
        try {
            const res = await api.post(`/mcp/servers/${serverId}/connect`);
            const result = res.data.connect_result;
            if (result?.connected) {
                toast(`Connected — ${result.tool_count} tools discovered`, "success");
            } else {
                toast(`Connection failed: ${result?.error || "unknown"}`, "error");
            }
            fetchServers();
        } catch {
            toast("Connection attempt failed", "error");
        } finally {
            setConnectingId(null);
        }
    };

    const handleRefresh = async (serverId: string) => {
        setConnectingId(serverId);
        try {
            const res = await api.post(`/mcp/servers/${serverId}/refresh`);
            const result = res.data.connect_result;
            toast(`Refreshed — ${result?.tool_count ?? 0} tools`, "success");
            fetchServers();
        } catch {
            toast("Refresh failed", "error");
        } finally {
            setConnectingId(null);
        }
    };

    const handleDelete = async (server: MCPServer) => {
        const ok = await confirm({
            title: "Delete MCP Server",
            description: `Delete "${server.name}"? All discovered tools will be removed.`,
            variant: "danger",
            confirmLabel: "Delete",
        });
        if (!ok) return;
        try {
            await api.delete(`/mcp/servers/${server.id}`);
            toast("Server deleted", "success");
            fetchServers();
        } catch {
            toast("Failed to delete server", "error");
        }
    };

    const transportBadge = (t: string) => {
        const colors: Record<string, string> = {
            http: "bg-primary/8 text-primary border border-primary/20",
            sse: "bg-emerald-500/8 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20",
            stdio: "bg-amber-500/8 text-amber-600 dark:text-amber-400 border border-amber-500/20",
        };
        return (
            <span className={`px-2 py-0.5 rounded-sm text-[10px] font-mono font-semibold uppercase ${colors[t] || "bg-secondary text-muted-foreground border border-border"}`}>
                {t}
            </span>
        );
    };

    return (
        <div className="flex flex-col h-full">
            <div className="flex-shrink-0 px-6 py-4 flex items-center justify-between border-b border-border/60">
                <div>
                    <h1 className="text-base font-semibold text-foreground tracking-tight">MCP Servers</h1>
                    <p className="text-xs text-muted-foreground font-mono mt-0.5">
                        Connect external Model Context Protocol servers to extend AI tool capabilities
                    </p>
                </div>
                <Button onClick={openAddModal} size="sm" className="h-8 px-3 text-xs gap-1.5">
                    <Plus className="w-3.5 h-3.5" /> Add Server
                </Button>
            </div>
            <div className="flex-1 overflow-y-auto p-6">
            <div className="space-y-6">

            {loading ? (
                <div className="flex items-center justify-center py-16">
                    <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
                </div>
            ) : servers.length === 0 ? (
                <Card>
                    <CardContent className="flex flex-col items-center justify-center py-16 gap-4">
                        <Network className="w-10 h-10 text-slate-300 dark:text-muted-foreground" />
                        <div className="text-center">
                            <p className="font-medium text-slate-700 dark:text-foreground">No MCP servers configured</p>
                            <p className="text-sm text-slate-500 dark:text-muted-foreground mt-1">
                                Add an MCP server to give the AI access to external tools
                            </p>
                        </div>
                        <Button onClick={openAddModal}><Plus className="w-4 h-4 mr-2" /> Add Server</Button>
                    </CardContent>
                </Card>
            ) : (
                <div className="space-y-3">
                    {servers.map(server => (
                        <Card key={server.id}>
                            <CardContent className="p-4 flex items-center gap-4">
                                <div className="flex-shrink-0">
                                    {server.is_connected
                                        ? <CheckCircle2 className="w-5 h-5 text-green-500" />
                                        : <XCircle className="w-5 h-5 text-slate-300 dark:text-muted-foreground" />}
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2">
                                        <span className="font-semibold text-slate-900 dark:text-foreground">{server.name}</span>
                                        {transportBadge(server.transport)}
                                        {server.is_connected && toolCounts[server.id] !== undefined && (
                                            <span className="text-xs text-slate-500 dark:text-muted-foreground">
                                                {toolCounts[server.id]} tools
                                            </span>
                                        )}
                                    </div>
                                    <p className="text-sm text-slate-500 dark:text-muted-foreground break-words">{server.description}</p>
                                    {(server.url || server.command) && (
                                        <p className="text-xs font-mono text-slate-400 dark:text-muted-foreground mt-0.5">
                                            {server.url || server.command}
                                        </p>
                                    )}
                                </div>
                                <div className="flex items-center gap-2 flex-shrink-0">
                                    {connectingId === server.id ? (
                                        <Loader2 className="w-4 h-4 animate-spin text-primary" />
                                    ) : (
                                        <>
                                            {!server.is_connected ? (
                                                <Button size="sm" variant="outline" onClick={() => handleConnect(server.id)}>
                                                    <Zap className="w-3 h-3 mr-1" /> Connect
                                                </Button>
                                            ) : (
                                                <Button size="sm" variant="outline" onClick={() => handleRefresh(server.id)}>
                                                    <RefreshCw className="w-3 h-3 mr-1" /> Refresh
                                                </Button>
                                            )}
                                            <Button size="sm" variant="outline" onClick={() => openEditModal(server)}>
                                                <Edit2 className="w-3 h-3" />
                                            </Button>
                                            <Button size="sm" variant="outline" onClick={() => handleDelete(server)}>
                                                <Trash2 className="w-3 h-3 text-red-500" />
                                            </Button>
                                        </>
                                    )}
                                </div>
                            </CardContent>
                        </Card>
                    ))}
                </div>
            )}

            <Modal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                title={editingServer ? "Edit MCP Server" : "Add MCP Server"}
            >
                <div className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium mb-1">Name *</label>
                        <Input placeholder="e.g. GitHub MCP" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
                    </div>
                    <div>
                        <label className="block text-sm font-medium mb-1">Description</label>
                        <Input placeholder="What this server does (shown to AI)" value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
                    </div>
                    <div>
                        <label className="block text-sm font-medium mb-1">Transport *</label>
                        <select
                            className="w-full border rounded-md px-3 py-2 text-sm bg-background"
                            value={form.transport}
                            onChange={e => setForm(f => ({ ...f, transport: e.target.value as "http" | "sse" | "stdio" }))}
                        >
                            <option value="http">HTTP</option>
                            <option value="sse">SSE</option>
                            <option value="stdio">stdio</option>
                        </select>
                    </div>
                    {(form.transport === "http" || form.transport === "sse") && (
                        <div>
                            <label className="block text-sm font-medium mb-1">URL *</label>
                            <Input placeholder="http://localhost:3000" value={form.url} onChange={e => setForm(f => ({ ...f, url: e.target.value }))} />
                        </div>
                    )}
                    {form.transport === "stdio" && (
                        <>
                            <div>
                                <label className="block text-sm font-medium mb-1">Command *</label>
                                <Input placeholder="e.g. npx" value={form.command} onChange={e => setForm(f => ({ ...f, command: e.target.value }))} />
                            </div>
                            <div>
                                <label className="block text-sm font-medium mb-1">Arguments (space-separated)</label>
                                <Input placeholder="e.g. @modelcontextprotocol/server-github" value={form.args} onChange={e => setForm(f => ({ ...f, args: e.target.value }))} />
                            </div>
                        </>
                    )}
                    <div>
                        <label className="block text-sm font-medium mb-1">Auth Type</label>
                        <select
                            className="w-full border rounded-md px-3 py-2 text-sm bg-background"
                            value={form.auth_type}
                            onChange={e => setForm(f => ({ ...f, auth_type: e.target.value }))}
                        >
                            <option value="none">None</option>
                            <option value="bearer">Bearer Token</option>
                            <option value="api_key">API Key</option>
                            <option value="basic">Basic (user:password)</option>
                        </select>
                    </div>
                    {form.auth_type !== "none" && (
                        <div>
                            <label className="block text-sm font-medium mb-1">Auth Value</label>
                            <Input
                                type="password"
                                placeholder={form.auth_type === "basic" ? "username:password" : "Enter value"}
                                value={form.auth_value}
                                onChange={e => setForm(f => ({ ...f, auth_value: e.target.value }))}
                            />
                            {editingServer && <p className="text-xs text-slate-400 mt-1">Leave blank to keep existing value</p>}
                        </div>
                    )}
                    <div className="flex justify-end gap-3 pt-2">
                        <Button variant="outline" onClick={() => setIsModalOpen(false)}>Cancel</Button>
                        <Button onClick={handleSave} disabled={saving}>
                            {saving && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
                            {editingServer ? "Save Changes" : "Add & Connect"}
                        </Button>
                    </div>
                </div>
            </Modal>
            </div>
            </div>
        </div>
    );
}
