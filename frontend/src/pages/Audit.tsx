import { useEffect, useState } from "react";
import api from "../lib/api";
import { ArrowUpDown, RefreshCw, Cloud, Server } from "lucide-react";
import { SkeletonRow } from "../components/ui/Skeleton";
import { cn } from "../lib/utils";

interface AuditLogEntry {
    id: number;
    timestamp: string;
    actor: string;
    action: string;
    resource: string;
    result: string;
    mode: string;
    source?: string;
    details?: string;
}

type AuditTab = "all" | "azure" | "k8s";

const TAB_LABELS: Record<AuditTab, string> = {
    all: "All Activity",
    azure: "Azure Activity",
    k8s: "K8S Activity",
};

export default function Audit() {
    const [logs, setLogs] = useState<AuditLogEntry[]>([]);
    const [loading, setLoading] = useState(true);
    const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
    const [activeTab, setActiveTab] = useState<AuditTab>("all");

    useEffect(() => {
        fetchLogs(tabSource);
    }, [activeTab]);

    const fetchLogs = async (source?: string) => {
        setLoading(true);
        try {
            const params = new URLSearchParams({ limit: "100" });
            if (source) params.set("source", source);
            const res = await api.get(`/audit/?${params.toString()}`);
            setLogs(res.data);
        } catch (err) {
            console.error("Failed to fetch audit logs", err);
        } finally {
            setLoading(false);
        }
    };

    const tabSource = activeTab === "azure" ? "AZURE" : activeTab === "k8s" ? "K8S" : undefined;

    const sortedLogs = [...logs].sort((a, b) => {
        const timeA = new Date(a.timestamp).getTime();
        const timeB = new Date(b.timestamp).getTime();
        return sortOrder === "asc" ? timeA - timeB : timeB - timeA;
    });

    const resultBadgeClass = (result: string): string => {
        const code = parseInt(result, 10);
        if (result === "SUCCESS" || (!isNaN(code) && code < 400))
            return "bg-emerald-500/8 text-emerald-600 dark:text-emerald-400 border-emerald-500/20";
        if (result === "REJECTED")
            return "bg-amber-500/8 text-amber-600 dark:text-amber-400 border-amber-500/20";
        if (result === "EXPIRED")
            return "bg-white/5 text-muted-foreground border-border";
        return "bg-red-500/8 text-red-600 dark:text-red-400 border-red-500/20";
    };

    const pageHeader = (
        <div className="flex-shrink-0 px-6 py-4 flex items-center justify-between border-b border-border/60">
            <div>
                <h1 className="text-base font-semibold text-foreground tracking-tight">Audit Logs</h1>
                <p className="text-xs text-muted-foreground font-mono mt-0.5">System activity · Last 100 entries</p>
            </div>
            <div className="flex items-center gap-2">
                <button
                    onClick={() => setSortOrder(o => o === "asc" ? "desc" : "asc")}
                    className="flex items-center gap-1.5 h-8 px-3 rounded-lg border border-border bg-secondary/50 text-xs font-mono text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                >
                    <ArrowUpDown className="w-3 h-3" />
                    {sortOrder === "desc" ? "Newest First" : "Oldest First"}
                </button>
                <button
                    onClick={() => fetchLogs(tabSource)}
                    className="h-8 w-8 flex items-center justify-center rounded-lg border border-border bg-secondary/50 text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                >
                    <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
                </button>
            </div>
        </div>
    );

    return (
        <div className="flex flex-col h-full">
            {pageHeader}
            <div className="flex-1 overflow-y-auto p-6">
                <div className="space-y-4">

                    {/* Tabs */}
                    <div className="flex gap-1 p-1 bg-secondary/40 border border-border/60 rounded-lg w-fit">
                        {(["all", "azure", "k8s"] as AuditTab[]).map(tab => (
                            <button
                                key={tab}
                                onClick={() => setActiveTab(tab)}
                                className={cn(
                                    "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium font-mono transition-colors",
                                    activeTab === tab
                                        ? "bg-card border border-border/60 text-foreground shadow-sm"
                                        : "text-muted-foreground hover:text-foreground"
                                )}
                            >
                                {tab === "azure" && <Cloud className="h-3 w-3" />}
                                {tab === "k8s" && <Server className="h-3 w-3" />}
                                {TAB_LABELS[tab]}
                            </button>
                        ))}
                    </div>

                    {/* Table */}
                    <div className="bg-card border border-border overflow-hidden">
                        <div className="relative w-full overflow-auto">
                            <table className="w-full text-left">
                                <thead>
                                    <tr className="border-b border-border bg-secondary/30">
                                        {["Time", "Actor", "Action", "Resource", "Details", "Status", "Mode"].map(h => (
                                            <th key={h} className="h-10 px-4 align-middle text-[9px] font-mono font-semibold text-muted-foreground/50 uppercase tracking-[0.18em]">
                                                {h}
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {loading ? (
                                        [...Array(8)].map((_, i) => <SkeletonRow key={i} />)
                                    ) : sortedLogs.length === 0 ? (
                                        <tr>
                                            <td colSpan={7} className="py-16 text-center text-xs font-mono text-muted-foreground/50">
                                                No audit logs recorded yet.
                                            </td>
                                        </tr>
                                    ) : sortedLogs.map((log) => (
                                        <tr key={log.id} className="border-b border-border last:border-0 transition-colors hover:bg-secondary/20">
                                            <td className="px-4 py-3 align-middle font-mono text-[11px] text-muted-foreground">
                                                {new Date(log.timestamp).toLocaleString()}
                                            </td>
                                            <td className="px-4 py-3 align-middle text-xs font-medium text-foreground">
                                                {log.actor}
                                            </td>
                                            <td className="px-4 py-3 align-middle font-mono text-[11px] text-foreground/80">
                                                {log.action}
                                            </td>
                                            <td className="px-4 py-3 align-middle text-[11px] text-muted-foreground">
                                                {log.resource}
                                                {log.source === "AZURE" && (
                                                    <Cloud className="inline h-3 w-3 text-primary ml-1" />
                                                )}
                                            </td>
                                            <td className="px-4 py-3 align-middle text-[11px] text-muted-foreground/60 font-mono">
                                                {log.details || "—"}
                                            </td>
                                            <td className="px-4 py-3 align-middle">
                                                <span className={cn(
                                                    "inline-flex items-center px-2 py-0.5 rounded-sm text-[10px] font-mono font-semibold border",
                                                    resultBadgeClass(log.result)
                                                )}>
                                                    {log.result}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3 align-middle">
                                                <span className={cn(
                                                    "inline-flex items-center px-2 py-0.5 rounded-sm text-[10px] font-mono font-semibold border",
                                                    log.mode === "GOD"
                                                        ? "bg-red-500/8 text-red-600 dark:text-red-400 border-red-500/20"
                                                        : "bg-primary/8 text-primary border-primary/20"
                                                )}>
                                                    {log.mode}
                                                </span>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>

                </div>
            </div>
        </div>
    );
}
