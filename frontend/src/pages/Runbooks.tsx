import { useEffect, useState } from "react";
import api from "../lib/api";
import { useToast } from "../context/ToastContext";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Modal";
import { RefreshCw, Plus, Edit, BookOpen } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { cn } from "../lib/utils";

interface Runbook {
    id: string;
    name: string;
    trigger: string;
    body: string;
}

const NEW_RUNBOOK_TEMPLATE = `---
name: My Runbook
trigger: describe when this runbook should be triggered
---

## Steps

1. First step — describe what the AI should do.
2. Second step — include tool names like \`get_pod_logs\` if relevant.
3. Ask for user permission before any destructive action (restart, delete, patch).
`;

export default function Runbooks() {
    const { toast } = useToast();
    const [runbooks, setRunbooks] = useState<Runbook[]>([]);
    const [loading, setLoading] = useState(true);
    const [selected, setSelected] = useState<Runbook | null>(null);
    const [isEditing, setIsEditing] = useState(false);
    const [editContent, setEditContent] = useState("");
    const [saving, setSaving] = useState(false);
    const [isCreateOpen, setIsCreateOpen] = useState(false);
    const [newContent, setNewContent] = useState(NEW_RUNBOOK_TEMPLATE);
    const [newId, setNewId] = useState("");

    const fetchRunbooks = async () => {
        setLoading(true);
        try {
            const res = await api.get("/ai/runbooks");
            setRunbooks(res.data);
        } catch {
            toast("Failed to load runbooks", "error");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchRunbooks(); }, []);

    const openView = (rb: Runbook) => {
        setSelected(rb);
        setIsEditing(false);
        setEditContent("");
    };

    const startEdit = () => {
        if (!selected) return;
        const raw = `---\nname: ${selected.name}\ntrigger: ${selected.trigger}\n---\n\n${selected.body}`;
        setEditContent(raw);
        setIsEditing(true);
    };

    const handleSave = async () => {
        if (!selected) return;
        setSaving(true);
        try {
            await api.post(`/ai/runbooks/${selected.id}`, editContent, {
                headers: { "Content-Type": "text/plain" },
            });
            toast("Runbook saved", "success");
            setIsEditing(false);
            setSelected(null);
            fetchRunbooks();
        } catch (err: unknown) {
            const e = err as { response?: { data?: { detail?: string } }; message?: string };
            toast("Save failed: " + (e.response?.data?.detail || e.message), "error");
        } finally {
            setSaving(false);
        }
    };

    const handleCreate = async () => {
        if (!newId.trim()) {
            toast("Please enter a runbook ID", "warning");
            return;
        }
        setSaving(true);
        try {
            await api.post(`/ai/runbooks/${newId.trim()}`, newContent, {
                headers: { "Content-Type": "text/plain" },
            });
            toast("Runbook created", "success");
            setIsCreateOpen(false);
            setNewId("");
            setNewContent(NEW_RUNBOOK_TEMPLATE);
            fetchRunbooks();
        } catch (err: unknown) {
            const e = err as { response?: { data?: { detail?: string } }; message?: string };
            toast("Create failed: " + (e.response?.data?.detail || e.message), "error");
        } finally {
            setSaving(false);
        }
    };

    const stepCount = (body: string) =>
        (body.match(/^\d+\./gm) || []).length;

    const inputCls = cn(
        "w-full px-3 py-2 text-sm rounded-lg border border-border transition-colors",
        "bg-background text-foreground placeholder:text-muted-foreground/40 font-mono",
        "outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20"
    );

    return (
        <div className="flex flex-col h-full">
            {/* Page header */}
            <div className="flex-shrink-0 px-6 py-4 flex items-center justify-between border-b border-border/60">
                <div>
                    <h1 className="text-base font-semibold text-foreground tracking-tight">Runbooks</h1>
                    <p className="text-xs text-muted-foreground font-mono mt-0.5">
                        AI automation guides triggered by natural language
                    </p>
                </div>
                <div className="flex gap-2">
                    <button
                        onClick={fetchRunbooks}
                        title="Refresh"
                        className="h-8 w-8 flex items-center justify-center rounded-lg border border-border bg-secondary/50 text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
                    >
                        <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
                    </button>
                    <Button onClick={() => setIsCreateOpen(true)} size="sm" className="h-8 px-3 text-xs gap-1.5">
                        <Plus className="w-3.5 h-3.5" />
                        New Runbook
                    </Button>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto p-6">
                {loading ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {[...Array(6)].map((_, i) => (
                            <div key={i} className="h-36 rounded-xl bg-secondary/40 animate-pulse" />
                        ))}
                    </div>
                ) : runbooks.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-20 text-center text-muted-foreground">
                        <BookOpen className="w-10 h-10 mb-4 opacity-20" />
                        <p className="text-sm font-medium">No runbooks yet</p>
                        <p className="text-xs mt-1 opacity-60">Create your first runbook to get started</p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {runbooks.map(rb => (
                            <div
                                key={rb.id}
                                onClick={() => openView(rb)}
                                className={cn(
                                    "rounded-xl border border-border p-4 flex flex-col gap-3 cursor-pointer",
                                    "bg-card dark:glass",
                                    "transition-all duration-200",
                                    "hover:border-primary/30",
                                    "dark:hover:shadow-[0_4px_24px_hsl(0_0%_0%_/_0.4),0_0_0_1px_hsl(191_89%_55%_/_0.08)]"
                                )}
                            >
                                <div className="flex items-start justify-between gap-2">
                                    <h3 className="font-semibold text-foreground text-sm leading-tight">
                                        {rb.name}
                                    </h3>
                                    <span className="text-[10px] text-muted-foreground/60 bg-secondary/60 border border-border/60 px-1.5 py-0.5 rounded-sm font-mono shrink-0">
                                        {rb.id}.md
                                    </span>
                                </div>
                                <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                                    <span className="font-semibold text-primary">Trigger:</span>{" "}
                                    {rb.trigger}
                                </p>
                                <p className="text-[11px] font-mono text-muted-foreground/50 mt-auto">
                                    {stepCount(rb.body)} steps
                                </p>
                            </div>
                        ))}
                    </div>
                )}

                {/* View / Edit Modal */}
                <Modal
                    isOpen={!!selected}
                    onClose={() => { setSelected(null); setIsEditing(false); }}
                    title={selected?.name ?? ""}
                    className="max-w-2xl"
                >
                    <div className="space-y-4 pt-2 max-h-[70vh] flex flex-col">
                        {!isEditing ? (
                            <>
                                <div className="flex items-center justify-between gap-3">
                                    <p className="text-xs text-muted-foreground font-mono">
                                        <span className="text-primary font-semibold">Trigger:</span>{" "}
                                        {selected?.trigger}
                                    </p>
                                    <button
                                        onClick={startEdit}
                                        className="flex items-center gap-1.5 h-7 px-2.5 rounded-lg border border-border text-xs text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors flex-shrink-0"
                                    >
                                        <Edit className="w-3 h-3" /> Edit
                                    </button>
                                </div>
                                <div className="flex-1 overflow-auto prose dark:prose-invert max-w-none text-sm bg-secondary/30 p-4 rounded-lg border border-border/60">
                                    <ReactMarkdown>{selected?.body ?? ""}</ReactMarkdown>
                                </div>
                            </>
                        ) : (
                            <>
                                <p className="text-xs text-muted-foreground font-mono">
                                    Edit the raw markdown below (frontmatter included).
                                </p>
                                <textarea
                                    className={cn(inputCls, "min-h-[350px] resize-none")}
                                    value={editContent}
                                    onChange={e => setEditContent(e.target.value)}
                                />
                                <div className="flex justify-end gap-2 pt-1">
                                    <button
                                        onClick={() => setIsEditing(false)}
                                        className="px-4 py-2 rounded-lg text-sm text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
                                    >
                                        Cancel
                                    </button>
                                    <Button onClick={handleSave} disabled={saving} size="sm" className="h-8 px-4">
                                        {saving && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                                        Save
                                    </Button>
                                </div>
                            </>
                        )}
                    </div>
                </Modal>

                {/* Create Modal */}
                <Modal
                    isOpen={isCreateOpen}
                    onClose={() => setIsCreateOpen(false)}
                    title="New Runbook"
                    className="max-w-2xl"
                >
                    <div className="space-y-4 pt-2">
                        <div className="space-y-1.5">
                            <label className="text-xs font-mono font-medium text-muted-foreground">Runbook ID</label>
                            <input
                                className={inputCls}
                                placeholder="e.g. jwt_api_error_triage"
                                value={newId}
                                onChange={e => setNewId(e.target.value.replace(/\s+/g, "_").toLowerCase())}
                            />
                            <p className="text-[10px] text-muted-foreground/60 font-mono">
                                Saved as: <span className="text-primary/70">{newId || "my_runbook"}.md</span>
                            </p>
                        </div>
                        <div className="space-y-1.5">
                            <label className="text-xs font-mono font-medium text-muted-foreground">Markdown Content</label>
                            <textarea
                                className={cn(inputCls, "h-64 resize-none")}
                                value={newContent}
                                onChange={e => setNewContent(e.target.value)}
                            />
                        </div>
                        <div className="flex justify-end gap-2">
                            <button
                                onClick={() => setIsCreateOpen(false)}
                                className="px-4 py-2 rounded-lg text-sm text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
                            >
                                Cancel
                            </button>
                            <Button onClick={handleCreate} disabled={saving} size="sm" className="h-8 px-4">
                                {saving && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                                Create
                            </Button>
                        </div>
                    </div>
                </Modal>
            </div>
        </div>
    );
}
