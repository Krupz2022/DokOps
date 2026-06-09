import { useState, useEffect } from "react";
import {
    CheckCircle2,
    XCircle,
    Loader2,
    Download,
    Terminal,
    Plus,
    Trash2,
    AlertTriangle,
} from "lucide-react";
import { Button } from "../components/ui/Button";
import { Card, CardContent } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { useToast } from "../context/ToastContext";
import { useConfirm } from "../context/ConfirmContext";
import { useAppContext } from "../context/AppContext";
import api from "../lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CLITool {
    name: string;
    description: string;
    installed: boolean;
    version: string | null;
    installing: boolean;
}

interface CustomTool {
    name: string;
    platform: "windows" | "linux" | "both";
    command: string;
}

// ---------------------------------------------------------------------------
// Pre-defined tool descriptions (shown on card; backend returns name+installed+version)
// ---------------------------------------------------------------------------

const TOOL_DESCRIPTIONS: Record<string, string> = {
    helm: "Kubernetes package manager — install, upgrade, and rollback releases",
    kubectl: "Official Kubernetes CLI — raw cluster operations",
    kubectx: "Fast cluster and namespace context switcher",
    kustomize: "Kubernetes native config management via overlays",
    flux: "FluxCD GitOps CLI — manage continuous delivery pipelines",
    argocd: "Argo CD CLI — declarative GitOps for Kubernetes",
    "helm-diff": "Helm plugin — preview what changes a helm upgrade would apply",
};

// ---------------------------------------------------------------------------
// CLIToolCard
// ---------------------------------------------------------------------------

interface CLIToolCardProps {
    tool: CLITool;
    godMode: boolean;
    onInstall: (name: string) => void;
}

function CLIToolCard({ tool, godMode, onInstall }: CLIToolCardProps) {
    const description = TOOL_DESCRIPTIONS[tool.name] ?? tool.description;

    return (
        <Card className="hover:shadow-md transition-shadow">
            <CardContent className="p-4">
                <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                            <Terminal className="w-4 h-4 text-slate-500 dark:text-slate-400 flex-shrink-0" />
                            <span className="font-mono font-semibold text-sm text-slate-800 dark:text-slate-100 truncate">
                                {tool.name}
                            </span>
                        </div>
                        <p className="text-xs text-slate-500 dark:text-slate-400 leading-snug">
                            {description}
                        </p>
                    </div>

                    <div className="flex-shrink-0 flex flex-col items-end gap-2">
                        {tool.installing ? (
                            <div className="flex items-center gap-1.5 text-xs text-blue-600 dark:text-blue-400">
                                <Loader2 className="w-4 h-4 animate-spin" />
                                <span>Installing…</span>
                            </div>
                        ) : tool.installed ? (
                            <div className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
                                <CheckCircle2 className="w-4 h-4" />
                                <span className="font-mono truncate max-w-[120px]">
                                    {tool.version ?? "installed"}
                                </span>
                            </div>
                        ) : (
                            <div className="flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500">
                                <XCircle className="w-4 h-4" />
                                <span>Not installed</span>
                            </div>
                        )}

                        {!tool.installed && !tool.installing && (
                            <Button
                                size="sm"
                                variant="outline"
                                disabled={!godMode}
                                title={
                                    godMode
                                        ? `Install ${tool.name}`
                                        : "God Mode required to install tools"
                                }
                                onClick={() => onInstall(tool.name)}
                            >
                                <Download className="w-3.5 h-3.5 mr-1" />
                                Install
                            </Button>
                        )}
                    </div>
                </div>
            </CardContent>
        </Card>
    );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CLIToolsTab() {
    const { toast } = useToast();
    const { confirm } = useConfirm();
    const { godModeActive, isSuperuser } = useAppContext();
    const godMode = godModeActive;

    const [tools, setTools] = useState<CLITool[]>([]);
    const [detecting, setDetecting] = useState(true);

    const [customTools, setCustomTools] = useState<CustomTool[]>([]);
    const [customLoading, setCustomLoading] = useState(true);

    // New custom tool form
    const [newName, setNewName] = useState("");
    const [newPlatform, setNewPlatform] = useState<"windows" | "linux" | "both">("both");
    const [newCommand, setNewCommand] = useState("");
    const [formSaving, setFormSaving] = useState(false);

    const [installingCustom, setInstallingCustom] = useState<Record<string, boolean>>({});

    // ------------------------------------------------------------------
    // Load
    // ------------------------------------------------------------------

    const detectTools = async () => {
        setDetecting(true);
        try {
            const res = await api.get<{ name: string; installed: boolean; version: string | null; description: string }[]>(
                "/system/cli-tools/"
            );
            setTools(
                res.data.map((t) => ({ ...t, installing: false }))
            );
        } catch {
            toast("Failed to detect CLI tools", "error");
        } finally {
            setDetecting(false);
        }
    };

    const loadCustomTools = async () => {
        setCustomLoading(true);
        try {
            const res = await api.get<CustomTool[]>("/system/cli-tools/custom");
            setCustomTools(res.data);
        } catch {
            toast("Failed to load custom tools", "error");
        } finally {
            setCustomLoading(false);
        }
    };

    useEffect(() => {
        if (isSuperuser) {
            detectTools();
            loadCustomTools();
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isSuperuser]);

    // ------------------------------------------------------------------
    // Pre-defined tool install
    // ------------------------------------------------------------------

    const handleInstall = async (name: string) => {
        const ok = await confirm({
            title: `Install ${name}`,
            description: `This will download the latest official ${name} binary for the detected server platform and place it in backend/bin/. God Mode is required.`,
            variant: "warning",
            confirmLabel: "Install",
        });
        if (!ok) return;

        setTools((prev) =>
            prev.map((t) => (t.name === name ? { ...t, installing: true } : t))
        );

        try {
            await api.post(`/system/cli-tools/${name}/install`, {});
            toast(`${name} installed successfully`, "success");
            // Re-detect to get actual version
            await detectTools();
        } catch (err: any) {
            toast(err.response?.data?.detail ?? `Failed to install ${name}`, "error");
            setTools((prev) =>
                prev.map((t) => (t.name === name ? { ...t, installing: false } : t))
            );
        }
    };

    // ------------------------------------------------------------------
    // Custom tools
    // ------------------------------------------------------------------

    const handleSaveCustom = async () => {
        if (!newName.trim() || !newCommand.trim()) {
            toast("Name and command are required", "error");
            return;
        }
        setFormSaving(true);
        try {
            await api.post("/system/cli-tools/custom", {
                name: newName.trim(),
                platform: newPlatform,
                command: newCommand.trim(),
            });
            toast("Custom tool saved", "success");
            setNewName("");
            setNewCommand("");
            setNewPlatform("both");
            await loadCustomTools();
        } catch (err: any) {
            toast(err.response?.data?.detail ?? "Failed to save custom tool", "error");
        } finally {
            setFormSaving(false);
        }
    };

    const handleDeleteCustom = async (name: string) => {
        const ok = await confirm({
            title: `Delete "${name}"`,
            description: `Remove the custom tool installer for "${name}"? This only removes the definition, not any installed binary.`,
            variant: "danger",
            confirmLabel: "Delete",
        });
        if (!ok) return;
        try {
            await api.delete(`/system/cli-tools/custom/${name}`);
            toast("Custom tool removed", "success");
            await loadCustomTools();
        } catch {
            toast("Failed to delete custom tool", "error");
        }
    };

    const handleInstallCustom = async (name: string) => {
        const tool = customTools.find((t) => t.name === name);
        if (!tool) return;
        const ok = await confirm({
            title: `Install "${name}"`,
            description: `Run the install command for "${name}" on the server (platform: ${tool.platform}):\n\n${tool.command}`,
            variant: "warning",
            confirmLabel: "Run",
        });
        if (!ok) return;

        setInstallingCustom((prev) => ({ ...prev, [name]: true }));
        try {
            await api.post(`/system/cli-tools/custom/${name}/install`, {});
            toast(`"${name}" installed successfully`, "success");
        } catch (err: any) {
            toast(err.response?.data?.detail ?? `Failed to install "${name}"`, "error");
        } finally {
            setInstallingCustom((prev) => ({ ...prev, [name]: false }));
        }
    };

    // ------------------------------------------------------------------
    // Guard — superuser only
    // ------------------------------------------------------------------

    if (!isSuperuser) {
        return (
            <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400 p-6">
                <AlertTriangle className="w-5 h-5" />
                <span>CLI Tools management is only available to superusers.</span>
            </div>
        );
    }

    // ------------------------------------------------------------------
    // Render
    // ------------------------------------------------------------------

    return (
        <div className="space-y-8 p-1">
            {/* God Mode notice */}
            {!godMode && (
                <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 dark:border-amber-900/40 dark:bg-amber-950/20 px-4 py-3 text-sm text-amber-700 dark:text-amber-400">
                    <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                    Install buttons are disabled — activate <strong>&nbsp;God Mode&nbsp;</strong> to install tools.
                </div>
            )}

            {/* Pre-defined tools */}
            <section>
                <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">
                    Pre-defined Tools
                </h3>
                {detecting ? (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                        {Array.from({ length: 7 }).map((_, i) => (
                            <Card key={i} className="animate-pulse">
                                <CardContent className="p-4 h-20 bg-slate-100 dark:bg-slate-800 rounded-lg" />
                            </Card>
                        ))}
                    </div>
                ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                        {tools.map((tool) => (
                            <CLIToolCard
                                key={tool.name}
                                tool={tool}
                                godMode={godMode}
                                onInstall={handleInstall}
                            />
                        ))}
                    </div>
                )}
            </section>

            {/* Custom tools */}
            <section>
                <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">
                    Custom Tools
                </h3>

                {/* Form */}
                <Card className="mb-4">
                    <CardContent className="p-4 space-y-3">
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                            <Input
                                placeholder="Tool name (e.g. kubeseal)"
                                value={newName}
                                onChange={(e) => setNewName(e.target.value)}
                            />
                            <select
                                value={newPlatform}
                                onChange={(e) =>
                                    setNewPlatform(e.target.value as "windows" | "linux" | "both")
                                }
                                className="rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
                            >
                                <option value="both">Both (Windows &amp; Linux)</option>
                                <option value="linux">Linux</option>
                                <option value="windows">Windows</option>
                            </select>
                            <Button
                                onClick={handleSaveCustom}
                                disabled={formSaving || !newName.trim() || !newCommand.trim()}
                                className="w-full"
                            >
                                {formSaving ? (
                                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                                ) : (
                                    <Plus className="w-4 h-4 mr-2" />
                                )}
                                Save
                            </Button>
                        </div>
                        <textarea
                            placeholder="Install command, e.g. curl -Lo /usr/local/bin/kubeseal ..."
                            value={newCommand}
                            onChange={(e) => setNewCommand(e.target.value)}
                            rows={2}
                            className="w-full rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm font-mono text-slate-800 dark:text-slate-100 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder:text-slate-400"
                        />
                    </CardContent>
                </Card>

                {/* Saved custom tools list */}
                {customLoading ? (
                    <div className="text-sm text-slate-400 dark:text-slate-500">Loading…</div>
                ) : customTools.length === 0 ? (
                    <p className="text-sm text-slate-400 dark:text-slate-500">
                        No custom tools saved yet.
                    </p>
                ) : (
                    <div className="space-y-2">
                        {customTools.map((tool) => (
                            <Card key={tool.name}>
                                <CardContent className="p-3 flex items-center gap-3">
                                    <Terminal className="w-4 h-4 text-slate-400 flex-shrink-0" />
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2">
                                            <span className="font-mono font-semibold text-sm text-slate-800 dark:text-slate-100">
                                                {tool.name}
                                            </span>
                                            <span className="text-xs px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400">
                                                {tool.platform}
                                            </span>
                                        </div>
                                        <p className="text-xs font-mono text-slate-500 dark:text-slate-400 truncate mt-0.5">
                                            {tool.command}
                                        </p>
                                    </div>
                                    <div className="flex items-center gap-2 flex-shrink-0">
                                        <Button
                                            size="sm"
                                            variant="outline"
                                            disabled={!godMode || installingCustom[tool.name]}
                                            title={
                                                godMode
                                                    ? `Install ${tool.name}`
                                                    : "God Mode required"
                                            }
                                            onClick={() => handleInstallCustom(tool.name)}
                                        >
                                            {installingCustom[tool.name] ? (
                                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                            ) : (
                                                <Download className="w-3.5 h-3.5" />
                                            )}
                                        </Button>
                                        <Button
                                            size="sm"
                                            variant="ghost"
                                            onClick={() => handleDeleteCustom(tool.name)}
                                        >
                                            <Trash2 className="w-3.5 h-3.5 text-red-500" />
                                        </Button>
                                    </div>
                                </CardContent>
                            </Card>
                        ))}
                    </div>
                )}
            </section>
        </div>
    );
}
