import { useEffect, useState } from "react";
import api from "../lib/api";
import { useToast } from "../context/ToastContext";
import { useConfirm } from "../context/ConfirmContext";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Trash2, RotateCw, Eye, Scale, RefreshCw, Sparkles, Search, Edit, ChevronDown, CheckSquare, Network, Box, Server, FileText, Lock } from "lucide-react";
import { LogsTerminal } from "../components/ui/LogsTerminal";
import { useAppContext } from "../context/AppContext";
import { Modal } from "../components/ui/Modal";
import { ActionCard } from "../components/ai/ActionCard";
import { Toast } from "../components/ui/Toast";
import ReactMarkdown from "react-markdown";
import { StatusBadge } from "../components/ui/StatusBadge";
import { EmptyState } from "../components/ui/EmptyState";

export default function Resources({ initialTab, standalone }: { initialTab?: string, standalone?: boolean }) {
    const { godModeActive } = useAppContext();
    const { toast } = useToast();
    const [activeTab, setActiveTab] = useState(initialTab || "pods");
    const [namespaces, setNamespaces] = useState<string[]>([]);
    const [selectedNamespace, setSelectedNamespace] = useState("default");
    const [refreshKey, setRefreshKey] = useState(0);
    const [notification, setNotification] = useState<{ message: string, type: "success" | "error" } | null>(null);
    const [runbooks, setRunbooks] = useState<any[]>([]);

    const handleRefresh = () => {
        setRefreshKey(prev => prev + 1);
    };

    useEffect(() => {
        fetchNamespaces();
        fetchRunbooks();

        const handleContextChange = () => {
            fetchNamespaces();
            setRefreshKey(k => k + 1);
        };
        window.addEventListener("clusterContextChanged", handleContextChange);
        return () => window.removeEventListener("clusterContextChanged", handleContextChange);
    }, []);

    const fetchNamespaces = async () => {
        try {
            const res = await api.get("/k8s/namespaces");
            setNamespaces(res.data);
        } catch (err) {
            console.error(err);
        }
    };

    const fetchRunbooks = async () => {
        try {
            const res = await api.get("/ai/runbooks");
            setRunbooks(res.data);
        } catch (err) {
            console.error(err);
        }
    };

    // Global AI State
    const [globalAiOpen, setGlobalAiOpen] = useState(false);
    const [globalQuery, setGlobalQuery] = useState("");
    const [searchResults, setSearchResults] = useState<any[]>([]);
    const [searching, setSearching] = useState(false);
    const [selectedGlobalPods, setSelectedGlobalPods] = useState<string[]>([]);
    const [batchAnalysis, setBatchAnalysis] = useState("");
    const [batchLoading, setBatchLoading] = useState(false);
    const [actionProposal, setActionProposal] = useState<any | null>(null);
    const [actionLoading, setActionLoading] = useState(false);
    const [ambiguityChoices, setAmbiguityChoices] = useState<any[]>([]);
    const [aiReport, setAiReport] = useState<string | null>(null);
    const [selectedBatchRunbookId] = useState("");

    const [pendingRunbook, setPendingRunbook] = useState<any>(null);
    const [pendingOperation, setPendingOperation] = useState<any>(null);

    const handleGlobalSearch = async () => {
        if (!globalQuery) return;
        setSearching(true);
        setGlobalAiOpen(true);
        setBatchAnalysis("");
        setAiReport(null);
        setActionProposal(null);
        setAmbiguityChoices([]);
        setSearchResults([]);
        setPendingRunbook(null);
        setPendingOperation(null);

        try {
            // Phase 5: 1. Send /runbooks/match
            const matchRes = await api.post("/ai/runbooks/match", { query: globalQuery });
            const match = matchRes.data;

            if (match.matched_runbook_id && match.confidence !== "none") {
                // 2. Show confirmation to run the matched runbook
                setPendingRunbook(match);
                setSearching(false);
                return;
            }

            // Fallback to old intent or direct stream
            await executeGlobalStream(globalQuery, null);
        } catch (err) {
            console.error(err);
            setNotification({ message: "Search failed.", type: "error" });
        } finally {
            setSearching(false);
        }
    };

    const confirmRunbook = async () => {
        if (!pendingRunbook) return;
        const rb = pendingRunbook;
        setPendingRunbook(null);
        await executeGlobalStream(globalQuery, rb.matched_runbook_id);
    };

    const executeGlobalStream = async (query: string, runbook_id: string | null) => {
        setSearching(true);
        setAiReport("");
        try {
            const token = localStorage.getItem("access_token");
            const clusterContext = localStorage.getItem("clusterContext");
            const headers: Record<string, string> = { "Content-Type": "application/json" };
            if (token) headers["Authorization"] = `Bearer ${token}`;
            if (clusterContext) headers["X-Cluster-Context"] = clusterContext;
            
            const baseURL = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";
            
            // If we have a runbook, we'll append its instruction to the query conceptually, 
            // or pass runbook_id if /global/stream supports it. The backend currently doesn't 
            // accept runbook_id on /global/stream. We should use the intent API or just pass it in query.
            // Wait, we need to pass runbook_id to global/stream. Let's assume we can add it.
            const reqBody: any = { query };
            if (runbook_id) reqBody.runbook_id = runbook_id;

            const res = await fetch(`${baseURL}/ai/global/stream`, {
                method: "POST",
                headers,
                body: JSON.stringify(reqBody)
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || "Failed to start global analysis");
            }

            const reader = res.body?.getReader();
            if (!reader) throw new Error("No stream from server.");
            const decoder = new TextDecoder();
            let currentText = "";
            let buffer = "";
            
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n\n");
                buffer = lines.pop() || ""; 
                
                for (const line of lines) {
                    if (line.startsWith("data: ")) {
                        try {
                            const data = JSON.parse(line.substring(6));
                            if (data.type === "step") {
                                currentText += `\n> _${data.message}_\n\n`;
                                setAiReport(currentText);
                            } else if (data.type === "result") {
                                currentText += `\n\n${data.message}`;
                                setAiReport(currentText);
                            } else if (data.type === "pending_operation") {
                                setPendingOperation(data.operation);
                                setSearching(false);
                                return; // Pause streaming
                            }
                        } catch (e) {}
                    }
                }
            }
        } catch (err: any) {
            setNotification({ message: err.message, type: "error" });
        } finally {
            setSearching(false);
        }
    };

    const approvePendingOperation = async () => {
         if (!pendingOperation) return;
         try {
             setActionLoading(true);
             await api.post(`/operations/pending/${pendingOperation.id}/approve`);
             setNotification({ message: "Operation approved and executed.", type: "success" });
             setPendingOperation(null);
             // Ideally resuming stream here, but for now we just show success.
         } catch (e: any) {
             setNotification({ message: "Failed to approve operation.", type: "error" });
         } finally {
             setActionLoading(false);
         }
    };

    const rejectPendingOperation = async () => {
         if (!pendingOperation) return;
         try {
             await api.post(`/operations/pending/${pendingOperation.id}/reject`);
             setPendingOperation(null);
         } catch (e: any) {
             console.error(e);
             setPendingOperation(null);
         }
    };

    const handleApproveAction = async (editedParams?: any) => {
        if (!actionProposal) return;
        setActionLoading(true);
        try {
            const { tool } = actionProposal;
            const parameters = editedParams || actionProposal.parameters;
            if (tool === "scale_deployment") {
                await api.post(`/k8s/namespaces/${parameters.namespace}/deployments/${parameters.name}/scale`, { replicas: parameters.replicas });
                setNotification({ message: `Successfully scaled ${parameters.name} to ${parameters.replicas} replicas!`, type: "success" });
            } else if (tool === "create_deployment_simple") {
                await api.post(`/k8s/namespaces/${parameters.namespace}/deployments`, { name: parameters.name, image: parameters.image, replicas: parameters.replicas });
                setNotification({ message: `Successfully created deployment ${parameters.name} in ${parameters.namespace}!`, type: "success" });
            } else if (tool === "delete_namespace") {
                await api.delete(`/k8s/namespaces/${parameters.name}`);
                setNotification({ message: `Namespace ${parameters.name} deletion initiated.`, type: "success" });
            }
            setActionProposal(null);
            setGlobalAiOpen(false);
            handleRefresh();
        } catch (err: any) {
            setNotification({ message: "Action Failed: " + (err.response?.data?.detail || "Unknown error"), type: "error" });
        } finally {
            setActionLoading(false);
        }
    };

    const handleRejectAction = () => setActionProposal(null);

    const togglePodSelection = (podName: string) => {
        setSelectedGlobalPods(prev => prev.includes(podName) ? prev.filter(p => p !== podName) : [...prev, podName]);
    };

    const handleBatchAnalyze = async () => {
        if (selectedGlobalPods.length === 0) return;
        setBatchLoading(true);
        setBatchAnalysis("");
        try {
            const targets = searchResults.filter(p => selectedGlobalPods.includes(p.name)).map(p => ({ namespace: p.namespace, pod_name: p.name }));
            const token = localStorage.getItem("access_token");
            const clusterContext = localStorage.getItem("clusterContext");
            const headers: Record<string, string> = { "Content-Type": "application/json" };
            if (token) headers["Authorization"] = `Bearer ${token}`;
            if (clusterContext) headers["X-Cluster-Context"] = clusterContext;
            
            const baseURL = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";
            const res = await fetch(`${baseURL}/ai/analyze/batch`, {
                method: "POST",
                headers,
                body: JSON.stringify({ pods: targets, query: globalQuery || "Analyze these pods for issues.", runbook_id: selectedBatchRunbookId || null })
            });

            if (!res.ok) throw new Error("Failed to start batch analysis");
            const reader = res.body?.getReader();
            if (!reader) throw new Error("No response stream.");
            const decoder = new TextDecoder();
            let currentText = "";
            let buffer = "";
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n\n");
                buffer = lines.pop() || "";
                
                for (const line of lines) {
                    if (line.startsWith("data: ")) {
                        try {
                            const data = JSON.parse(line.substring(6));
                            if (data.type === "step") {
                                currentText += `\n> _${data.message}_\n\n`;
                                setBatchAnalysis(currentText);
                            } else if (data.type === "result") {
                                currentText += `\n\n${data.message}`;
                                setBatchAnalysis(currentText);
                            }
                        } catch (e) {
                            // ignore partial parsings
                        }
                    }
                }
            }
        } catch (err: any) {
            toast("Batch Analysis failed: " + err.message, "error");
        } finally {
            setBatchLoading(false);
        }
    };

    return (
        <div className="flex flex-col h-full">
            {!standalone && (
                <div className="flex-shrink-0 px-6 pt-4 pb-0 space-y-3">
                    <div className="flex items-center justify-between">
                        <div>
                            <h1 className="text-xl font-bold text-foreground">Resources</h1>
                            <p className="text-sm text-muted-foreground mt-0.5">
                                Kubernetes resources · {selectedNamespace} namespace
                            </p>
                        </div>
                    </div>
                    <div className="flex items-center gap-3">
                        <div className="relative flex-1 max-w-md">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                            <Input className="pl-9 h-9" placeholder="Ask AI (e.g., 'Find crashing pods')" value={globalQuery} onChange={(e) => setGlobalQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && handleGlobalSearch()} />
                        </div>
                        <Button onClick={handleGlobalSearch} disabled={searching} size="sm" className="h-9">
                            {searching ? <RotateCw className="w-4 h-4 animate-spin" /> : <><Sparkles className="w-4 h-4 mr-1.5" />Ask AI</>}
                        </Button>
                    </div>

                    <div className="flex items-center gap-2">
                        <div className="relative">
                            <select value={selectedNamespace} onChange={(e) => setSelectedNamespace(e.target.value)} className="h-9 pl-3 pr-8 border border-slate-200 dark:border-border rounded-lg bg-white dark:bg-background text-sm text-slate-700 dark:text-foreground appearance-none focus:outline-none focus:ring-2 focus:ring-blue-500">
                                {namespaces.map((ns) => <option key={ns} value={ns}>{ns}</option>)}
                            </select>
                            <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
                        </div>
                        <Button variant="outline" size="icon" onClick={() => { setRefreshKey(prev => prev + 1); fetchNamespaces(); }} title="Refresh" className="h-9 w-9">
                            <RefreshCw className="w-4 h-4" />
                        </Button>
                    </div>

                    <div className="flex gap-0">
                        {["pods", "deployments", "services", "configmaps", "secrets"].map((tab) => (
                            <button key={tab} onClick={() => setActiveTab(tab)} className={`px-4 py-2.5 text-sm font-medium border-b-2 capitalize transition-colors ${activeTab === tab ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
                                {tab}
                            </button>
                        ))}
                    </div>
                </div>
            )}

            <div className="flex-1 overflow-y-auto p-6">
            {activeTab === "pods" && <PodsView key={refreshKey} namespace={selectedNamespace} godModeActive={godModeActive} runbooks={runbooks} />}
            {activeTab === "deployments" && <DeploymentsView key={refreshKey} namespace={selectedNamespace} godModeActive={godModeActive} />}
            {activeTab === "services" && <ServicesView key={refreshKey} namespace={selectedNamespace} />}
            {activeTab === "configmaps" && <ConfigMapsView key={refreshKey} namespace={selectedNamespace} />}
            {activeTab === "secrets" && <SecretsView key={refreshKey} namespace={selectedNamespace} />}

            <Modal isOpen={globalAiOpen} onClose={() => setGlobalAiOpen(false)} title="Global AI Assistant 🤖" className="max-w-3xl">
                <div className="space-y-4 max-h-[80vh] flex flex-col min-w-[600px]">
                    {pendingRunbook && (
                        <div className="border border-slate-200 dark:border-purple-800 rounded-lg p-6 bg-slate-50 dark:bg-purple-950/30">
                            <h3 className="font-bold text-lg mb-2 flex items-center gap-2 text-purple-700 dark:text-purple-300">
                                <Sparkles className="w-5 h-5" /> Found Runbook: {pendingRunbook.runbook_name}
                            </h3>
                            <p className="text-sm text-slate-600 dark:text-purple-400 mb-4">{pendingRunbook.reasoning}</p>
                            <div className="flex gap-4">
                                <Button onClick={confirmRunbook} className="bg-purple-600 hover:bg-purple-700">Run Sequence</Button>
                                <Button variant="outline" onClick={() => { setPendingRunbook(null); executeGlobalStream(globalQuery, null); }}>Skip & Use AI</Button>
                            </div>
                        </div>
                    )}
                    {pendingOperation && (
                        <div className="border border-amber-200 dark:border-amber-800 rounded-lg p-6 bg-amber-50 dark:bg-amber-950/30">
                            <h3 className="font-bold text-lg mb-2 flex items-center gap-2 text-amber-900 dark:text-amber-300">
                                ⚠️ Requires Confirmation
                            </h3>
                            <p className="text-sm text-amber-800 dark:text-amber-400 mb-4">{pendingOperation.confirmation_message}</p>
                            <div className="bg-background/50 p-3 rounded text-xs font-mono mb-4">
                                Tool: {pendingOperation.tool_name}<br/>
                                Risk: <span className="uppercase font-bold">{pendingOperation.risk_level}</span>
                            </div>
                            <div className="flex gap-4">
                                <Button onClick={approvePendingOperation} className="bg-amber-600 hover:bg-amber-700 text-white" disabled={actionLoading}>
                                    {actionLoading ? "Approving..." : "Approve & Execute"}
                                </Button>
                                <Button variant="outline" onClick={rejectPendingOperation} disabled={actionLoading}>Reject</Button>
                            </div>
                        </div>
                    )}
                    {!pendingRunbook && !pendingOperation && ambiguityChoices.length > 0 && (
                        <div className="border rounded-lg p-4 bg-muted/30">
                            <h3 className="font-bold text-lg mb-2 flex items-center gap-2"><Sparkles className="w-5 h-5 text-amber-500" />Which one did you mean?</h3>
                            <div className="space-y-2">
                                {ambiguityChoices.map((choice, i) => (
                                    <div key={i} className="flex items-center justify-between p-3 border rounded-md hover:bg-muted cursor-pointer bg-background" onClick={() => { setActionProposal({ type: "action_proposal", tool: "scale_deployment", summary: `Scale ${choice.name} to ${choice.replicas} replicas`, parameters: { namespace: choice.namespace, name: choice.name, replicas: choice.replicas } }); setAmbiguityChoices([]); }}>
                                        <div className="font-bold">{choice.namespace} / {choice.name} (Replicas: {choice.replicas})</div>
                                        <Button size="sm" variant="outline">Select</Button>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                    {aiReport && (
                        <div className="border rounded-lg p-4 bg-muted/30 overflow-auto">
                            <h3 className="font-bold text-lg mb-2 flex items-center gap-2"><CheckSquare className="w-5 h-5 text-green-500" />Analysis Report</h3>
                            <div className="bg-background p-4 rounded-md border font-sans text-sm prose dark:prose-invert max-w-none"><ReactMarkdown>{aiReport}</ReactMarkdown></div>
                            <Button onClick={() => setAiReport(null)} className="mt-4">Close</Button>
                        </div>
                    )}
                    {actionProposal && <ActionCard proposal={actionProposal} onApprove={handleApproveAction} onReject={handleRejectAction} godMode={godModeActive} loading={actionLoading} />}
                    {!actionProposal && ambiguityChoices.length === 0 && (
                        <div className="space-y-2">
                            <Input value={globalQuery} onChange={(e) => setGlobalQuery(e.target.value)} placeholder="e.g., check api logs for errors" />
                            <Button onClick={handleGlobalSearch} disabled={searching}>{searching ? <RotateCw className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4 mr-2" />}Find</Button>
                        </div>
                    )}
                    {searchResults.length > 0 && !batchAnalysis && (
                        <div className="border rounded-md p-4 bg-muted/20">
                            <h4 className="text-sm font-bold mb-2">Found {searchResults.length} Pods</h4>
                            <div className="max-h-40 overflow-auto space-y-1">
                                {searchResults.map(pod => (
                                    <div key={pod.name} className={`flex items-center justify-between p-2 rounded text-sm cursor-pointer ${selectedGlobalPods.includes(pod.name) ? "bg-primary/10 border-primary border" : "bg-background"}`} onClick={() => togglePodSelection(pod.name)}>
                                        <span>{pod.namespace}/{pod.name}</span>
                                        <span className="text-[10px] uppercase">{pod.status}</span>
                                    </div>
                                ))}
                            </div>
                            <Button className="w-full mt-4" onClick={handleBatchAnalyze} disabled={selectedGlobalPods.length === 0 || batchLoading}>{batchLoading ? "Analyzing..." : `Analyze ${selectedGlobalPods.length} Pods`}</Button>
                        </div>
                    )}
                    {batchAnalysis && (
                        <div className="flex-1 overflow-auto bg-muted/50 p-4 rounded-lg border min-h-[300px]">
                            <h3 className="text-lg font-bold mb-4 flex items-center gap-2"><Sparkles className="w-5 h-5 text-purple-500" />AI Batch Analysis</h3>
                            <div className="prose prose-sm dark:prose-invert max-w-none"><ReactMarkdown>{batchAnalysis}</ReactMarkdown></div>
                        </div>
                    )}
                </div>
            </Modal>
            {notification && <Toast message={notification.message} type={notification.type} onClose={() => setNotification(null)} />}
            </div>
        </div>
    );
}

// Pods View
function PodsView({ namespace, godModeActive, runbooks }: { namespace: string; godModeActive: boolean; runbooks: any[] }) {
    const { toast } = useToast();
    const { confirm } = useConfirm();
    const [pods, setPods] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [podSearch, setPodSearch] = useState("");
    const [sortRunning, setSortRunning] = useState<"running-first" | "not-first" | null>(null);
    const [selectedPod, setSelectedPod] = useState<string | null>(null);
    const [logs, setLogs] = useState("");
    const [aiModalOpen, setAiModalOpen] = useState(false);
    const [aiAnalysis, setAiAnalysis] = useState("");
    const [aiLoading, setAiLoading] = useState(false);
    const [aiQuery, setAiQuery] = useState("Analyze these logs and identify any errors or issues.");
    const [selectedRunbookId, setSelectedRunbookId] = useState("");
    const [logsModalOpen, setLogsModalOpen] = useState(false);

    useEffect(() => { fetchPods(); }, [namespace]);

    const fetchPods = async () => {
        setLoading(true);
        try {
            const res = await api.get(`/k8s/namespaces/${namespace}/pods`);
            setPods(res.data);
        } catch (err) { console.error(err); }
        finally { setLoading(false); }
    };

    const viewLogs = async (podName: string) => {
        try {
            const res = await api.get(`/k8s/namespaces/${namespace}/pods/${podName}/logs`);
            setLogs(res.data.logs);
            setSelectedPod(podName);
            setLogsModalOpen(true);
        } catch (err) { toast("Failed to fetch logs", "error"); }
    };

    const deletePod = async (podName: string) => {
        const ok = await confirm({
            title: "Delete Pod",
            description: `Permanently delete pod ${podName}? Kubernetes will reschedule it if managed by a controller.`,
            variant: "danger",
            confirmLabel: "Delete Pod",
        });
        if (!ok) return;
        try {
            await api.delete(`/k8s/namespaces/${namespace}/pods/${podName}`);
            fetchPods();
        } catch (err: any) { toast(err.response?.data?.detail || "Failed to delete pod", "error"); }
    };

    const handleAnalyze = async () => {
        if (!selectedPod) return;
        setAiLoading(true);
        setAiAnalysis("");
        try {
            const token = localStorage.getItem("access_token");
            const clusterContext = localStorage.getItem("clusterContext");
            const headers: Record<string, string> = { "Content-Type": "application/json" };
            if (token) headers["Authorization"] = `Bearer ${token}`;
            if (clusterContext) headers["X-Cluster-Context"] = clusterContext;
            const baseURL = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";
            const res = await fetch(`${baseURL}/ai/diagnose/stream`, {
                method: "POST",
                headers,
                body: JSON.stringify({ namespace, pod_name: selectedPod, query: aiQuery, runbook_id: selectedRunbookId || null })
            });
            if (!res.ok) throw new Error("Analysis failed");
            const reader = res.body?.getReader();
            if (!reader) throw new Error("No response stream available.");
            const decoder = new TextDecoder();
            let currentText = "";
            let buffer = "";
            
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n\n");
                buffer = lines.pop() || "";
                
                for (const line of lines) {
                    if (line.startsWith("data: ")) {
                        try {
                            const data = JSON.parse(line.substring(6));
                            if (data.type === "step") {
                                currentText += `\n> _${data.message}_\n\n`;
                                setAiAnalysis(currentText);
                            } else if (data.type === "result") {
                                currentText += `\n\n${data.message}`;
                                setAiAnalysis(currentText);
                            }
                        } catch (e) {
                            // ignore partial parsings
                        }
                    }
                }
            }
        } catch (err: any) { toast(err.message, "error"); } finally { setAiLoading(false); }
    };

    const filteredPods = pods
        .filter(p => p.name.toLowerCase().includes(podSearch.toLowerCase()))
        .sort((a, b) => {
            if (!sortRunning) return 0;
            const aRunning = a.status === "Running";
            const bRunning = b.status === "Running";
            if (sortRunning === "running-first") return aRunning === bRunning ? 0 : aRunning ? -1 : 1;
            return aRunning === bRunning ? 0 : aRunning ? 1 : -1;
        });

    return (
        <>
            <Card>
                <CardHeader><CardTitle>Pods in {namespace}</CardTitle></CardHeader>
                <CardContent>
                    {loading ? (
                        <div className="flex items-center justify-center py-12 text-muted-foreground"><RotateCw className="w-5 h-5 animate-spin mr-2" />Loading pods…</div>
                    ) : pods.length === 0 ? (
                        <EmptyState icon={Box} title="No pods found" description="No pods were found in this namespace. Deploy an application to see pods here." />
                    ) : (
                    <>
                    <div className="flex items-center gap-2 mb-3">
                        <div className="relative flex-1 max-w-sm">
                            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
                            <input className="w-full pl-8 pr-3 h-8 text-sm border border-border rounded-md bg-background focus:outline-none focus:ring-1 focus:ring-blue-500" placeholder="Filter pods…" value={podSearch} onChange={e => setPodSearch(e.target.value)} />
                        </div>
                        <button onClick={() => setSortRunning(s => s === "running-first" ? "not-first" : s === "not-first" ? null : "running-first")} className={`h-8 px-3 text-xs rounded-md border transition-colors ${sortRunning ? "bg-primary text-primary-foreground border-primary" : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30"}`}>
                            {sortRunning === "running-first" ? "Running first" : sortRunning === "not-first" ? "Not running first" : "Sort by status"}
                        </button>
                        {podSearch && <span className="text-xs text-muted-foreground">{filteredPods.length} / {pods.length}</span>}
                    </div>
                    <table className="w-full text-sm">
                        <thead className="border-b"><tr><th className="p-4 text-left">Name</th><th className="p-4 text-left">Status</th><th className="p-4 text-left">IP</th><th className="p-4 text-left">Actions</th></tr></thead>
                        <tbody>
                            {filteredPods.map(pod => (
                                <tr key={pod.name} className="border-b hover:bg-slate-50 dark:hover:bg-accent transition-colors">
                                    <td className="p-4 font-mono text-xs">{pod.name}</td>
                                    <td className="p-4"><StatusBadge status={pod.status || "Unknown"} /></td>
                                    <td className="p-4 font-mono text-xs">{pod.ip}</td>
                                    <td className="p-4 flex gap-2">
                                        <Button size="sm" variant="outline" onClick={() => viewLogs(pod.name)}><Eye className="w-4 h-4" /></Button>
                                        <Button size="sm" variant="outline" className="text-purple-600 border-purple-200" onClick={() => { setSelectedPod(pod.name); setAiModalOpen(true); }}><Sparkles className="w-4 h-4" /></Button>
                                        {godModeActive && <Button size="sm" variant="destructive" onClick={() => deletePod(pod.name)}><Trash2 className="w-4 h-4" /></Button>}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    </>
                    )}
                </CardContent>
            </Card>
            <LogsTerminal
                isOpen={logsModalOpen}
                onClose={() => setLogsModalOpen(false)}
                podName={selectedPod ?? ""}
                namespace={namespace}
                logs={logs}
            />
            <Modal isOpen={aiModalOpen} onClose={() => setAiModalOpen(false)} title={`AI Analysis: ${selectedPod}`} className="max-w-4xl">
                <div className="space-y-4 max-h-[70vh] flex flex-col">
                    <div className="flex gap-2">
                        <Input value={aiQuery} onChange={(e) => setAiQuery(e.target.value)} placeholder="What should I look for?" />
                        <Button onClick={handleAnalyze} disabled={aiLoading}>{aiLoading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4 mr-2" />}Analyze</Button>
                    </div>
                    {runbooks.length > 0 && (
                        <select className="w-full bg-background border rounded-md px-3 py-1.5 text-sm" value={selectedRunbookId} onChange={(e) => setSelectedRunbookId(e.target.value)}>
                            <option value="">No Runbook (Pure AI)</option>
                            {runbooks.map(rb => <option key={rb.id} value={rb.id}>{rb.name}</option>)}
                        </select>
                    )}
                    <div className="flex-1 overflow-auto bg-muted/50 p-4 rounded-lg border font-sans text-sm prose dark:prose-invert max-w-none"><ReactMarkdown>{aiAnalysis}</ReactMarkdown></div>
                </div>
            </Modal>
        </>
    );
}

// Deployments View
function DeploymentsView({ namespace, godModeActive }: { namespace: string; godModeActive: boolean }) {
    const { toast } = useToast();
    const { confirm } = useConfirm();
    const [deployments, setDeployments] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [depSearch, setDepSearch] = useState("");
    const [sortAvailable, setSortAvailable] = useState<"available-first" | "degraded-first" | null>(null);
    const [isScaleModalOpen, setIsScaleModalOpen] = useState(false);
    const [selectedDeployment, setSelectedDeployment] = useState<any>(null);
    const [targetReplicas, setTargetReplicas] = useState(1);

    useEffect(() => { fetchDeployments(); }, [namespace]);

    const fetchDeployments = async () => {
        setLoading(true);
        try {
            const res = await api.get(`/k8s/namespaces/${namespace}/deployments`);
            setDeployments(res.data);
        } catch (err) { console.error(err); }
        finally { setLoading(false); }
    };

    const handleScaleSubmit = async () => {
        try {
            await api.post(`/k8s/namespaces/${namespace}/deployments/${selectedDeployment.name}/scale`, { replicas: targetReplicas });
            setIsScaleModalOpen(false);
            fetchDeployments();
        } catch (err: any) { toast("Scaling failed", "error"); }
    };

    const handleDeleteDeployment = async (name: string) => {
        const ok = await confirm({
            title: "Delete Deployment",
            description: `Permanently delete deployment ${name}? All managed pods will be terminated.`,
            variant: "danger",
            confirmLabel: "Delete Deployment",
        });
        if (!ok) return;
        try {
            await api.delete(`/k8s/namespaces/${namespace}/deployments/${name}`);
            fetchDeployments();
        } catch (err: any) { toast(err.response?.data?.detail || "Failed to delete deployment", "error"); }
    };

    const filteredDeployments = deployments
        .filter(d => d.name.toLowerCase().includes(depSearch.toLowerCase()))
        .sort((a, b) => {
            if (!sortAvailable) return 0;
            const aOk = a.available === a.replicas && a.replicas > 0;
            const bOk = b.available === b.replicas && b.replicas > 0;
            if (sortAvailable === "available-first") return aOk === bOk ? 0 : aOk ? -1 : 1;
            return aOk === bOk ? 0 : aOk ? 1 : -1;
        });

    return (
        <Card>
            <CardHeader><CardTitle>Deployments in {namespace}</CardTitle></CardHeader>
            <CardContent>
                {loading ? (
                    <div className="flex items-center justify-center py-12 text-muted-foreground"><RotateCw className="w-5 h-5 animate-spin mr-2" />Loading deployments…</div>
                ) : deployments.length === 0 ? (
                    <EmptyState icon={Server} title="No deployments found" description="No deployments were found in this namespace." />
                ) : (
                <>
                <div className="flex items-center gap-2 mb-3">
                    <div className="relative flex-1 max-w-sm">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
                        <input className="w-full pl-8 pr-3 h-8 text-sm border border-border rounded-md bg-background focus:outline-none focus:ring-1 focus:ring-blue-500" placeholder="Filter deployments…" value={depSearch} onChange={e => setDepSearch(e.target.value)} />
                    </div>
                    <button onClick={() => setSortAvailable(s => s === "available-first" ? "degraded-first" : s === "degraded-first" ? null : "available-first")} className={`h-8 px-3 text-xs rounded-md border transition-colors ${sortAvailable ? "bg-primary text-primary-foreground border-primary" : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30"}`}>
                        {sortAvailable === "available-first" ? "Available first" : sortAvailable === "degraded-first" ? "Degraded first" : "Sort by status"}
                    </button>
                    {depSearch && <span className="text-xs text-muted-foreground">{filteredDeployments.length} / {deployments.length}</span>}
                </div>
                <table className="w-full text-sm">
                    <thead className="border-b"><tr><th className="p-4 text-left">Name</th><th className="p-4 text-left">Replicas</th><th className="p-4 text-left">Actions</th></tr></thead>
                    <tbody>
                        {filteredDeployments.map(dep => (
                            <tr key={dep.name} className="border-b hover:bg-slate-50 dark:hover:bg-accent transition-colors">
                                <td className="p-4">{dep.name}</td>
                                <td className="p-4">{dep.available}/{dep.replicas}</td>
                                <td className="p-4 flex gap-2">
                                    <Button size="sm" variant="outline" onClick={() => { setSelectedDeployment(dep); setTargetReplicas(dep.replicas); setIsScaleModalOpen(true); }}><Scale className="w-4 h-4" /></Button>
                                    {godModeActive && <Button size="sm" variant="destructive" onClick={() => handleDeleteDeployment(dep.name)}><Trash2 className="w-4 h-4" /></Button>}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                </>
                )}
            </CardContent>
            <Modal isOpen={isScaleModalOpen} onClose={() => setIsScaleModalOpen(false)} title={`Scale: ${selectedDeployment?.name}`}>
                <div className="space-y-4">
                    <Input type="number" value={targetReplicas} onChange={(e) => setTargetReplicas(parseInt(e.target.value))} />
                    <Button onClick={handleScaleSubmit}>Scale</Button>
                </div>
            </Modal>
        </Card>
    );
}

// Services View
function ServicesView({ namespace }: { namespace: string }) {
    const [services, setServices] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [svcSearch, setSvcSearch] = useState("");
    useEffect(() => { fetchServices(); }, [namespace]);
    const fetchServices = async () => {
        setLoading(true);
        try {
            const res = await api.get(`/k8s/namespaces/${namespace}/services`);
            setServices(res.data);
        } catch (err) { console.error(err); }
        finally { setLoading(false); }
    };

    const filteredServices = services.filter(s => s.name.toLowerCase().includes(svcSearch.toLowerCase()));

    return (
        <Card>
            <CardHeader><CardTitle>Services in {namespace}</CardTitle></CardHeader>
            <CardContent>
                {loading ? (
                    <div className="flex items-center justify-center py-12 text-muted-foreground"><RotateCw className="w-5 h-5 animate-spin mr-2" />Loading services…</div>
                ) : services.length === 0 ? (
                    <EmptyState icon={Network} title="No services found" description="No services were found in this namespace." />
                ) : (
                <>
                <div className="flex items-center gap-2 mb-3">
                    <div className="relative flex-1 max-w-sm">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
                        <input className="w-full pl-8 pr-3 h-8 text-sm border border-border rounded-md bg-background focus:outline-none focus:ring-1 focus:ring-blue-500" placeholder="Filter services…" value={svcSearch} onChange={e => setSvcSearch(e.target.value)} />
                    </div>
                    {svcSearch && <span className="text-xs text-muted-foreground">{filteredServices.length} / {services.length}</span>}
                </div>
                <table className="w-full text-sm">
                    <thead className="border-b"><tr><th className="p-4 text-left">Name</th><th className="p-4 text-left">Type</th><th className="p-4 text-left">Cluster IP</th></tr></thead>
                    <tbody>
                        {filteredServices.map(svc => (
                            <tr key={svc.name} className="border-b hover:bg-slate-50 dark:hover:bg-accent transition-colors">
                                <td className="p-4">{svc.name}</td>
                                <td className="p-4">{svc.type}</td>
                                <td className="p-4">{svc.cluster_ip}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                </>
                )}
            </CardContent>
        </Card>
    );
}

// ConfigMaps View
function ConfigMapsView({ namespace }: { namespace: string }) {
    const { toast } = useToast();
    const [configmaps, setConfigmaps] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [cmSearch, setCmSearch] = useState("");
    const [selectedCM, setSelectedCM] = useState<any>(null);
    const [cmDataString, setCmDataString] = useState("");
    const [isEditOpen, setIsEditOpen] = useState(false);
    const [isViewOpen, setIsViewOpen] = useState(false);
    const [viewData, setViewData] = useState<Record<string, string>>({});
    const [loadingCM, setLoadingCM] = useState<string | null>(null);

    useEffect(() => { fetchConfigMaps(); }, [namespace]);

    const fetchConfigMaps = async () => {
        setLoading(true);
        try {
            const res = await api.get(`/k8s/namespaces/${namespace}/configmaps`);
            setConfigmaps(res.data);
        } catch (err) { console.error(err); }
        finally { setLoading(false); }
    };

    const fetchFullCM = async (name: string): Promise<Record<string, string>> => {
        const res = await api.get(`/k8s/namespaces/${namespace}/configmaps/${name}`);
        return res.data.data || {};
    };

    const handleView = async (cm: any) => {
        setLoadingCM(cm.name);
        try {
            const data = await fetchFullCM(cm.name);
            setSelectedCM(cm);
            setViewData(data);
            setIsViewOpen(true);
        } catch (err) {
            toast("Failed to load ConfigMap data", "error");
        } finally {
            setLoadingCM(null);
        }
    };

    const handleEdit = async (cm: any) => {
        setLoadingCM(cm.name);
        try {
            const data = await fetchFullCM(cm.name);
            setSelectedCM(cm);
            setCmDataString(JSON.stringify(data, null, 2));
            setIsEditOpen(true);
        } catch (err) {
            toast("Failed to load ConfigMap data", "error");
        } finally {
            setLoadingCM(null);
        }
    };

    const filteredCMs = configmaps.filter(cm => cm.name.toLowerCase().includes(cmSearch.toLowerCase()));

    return (
        <Card>
            <CardHeader><CardTitle>ConfigMaps in {namespace}</CardTitle></CardHeader>
            <CardContent>
                {loading ? (
                    <div className="flex items-center justify-center py-12 text-muted-foreground"><RotateCw className="w-5 h-5 animate-spin mr-2" />Loading ConfigMaps…</div>
                ) : configmaps.length === 0 ? (
                    <EmptyState icon={FileText} title="No ConfigMaps found" description="No ConfigMaps were found in this namespace." />
                ) : (
                <>
                <div className="flex items-center gap-2 mb-3">
                    <div className="relative flex-1 max-w-sm">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
                        <input className="w-full pl-8 pr-3 h-8 text-sm border border-border rounded-md bg-background focus:outline-none focus:ring-1 focus:ring-blue-500" placeholder="Filter configmaps…" value={cmSearch} onChange={e => setCmSearch(e.target.value)} />
                    </div>
                    {cmSearch && <span className="text-xs text-muted-foreground">{filteredCMs.length} / {configmaps.length}</span>}
                </div>
                <table className="w-full text-sm">
                    <thead className="border-b"><tr><th className="p-4 text-left">Name</th><th className="p-4 text-left">Keys</th><th className="p-4 text-left">Actions</th></tr></thead>
                    <tbody>
                        {filteredCMs.map(cm => (
                            <tr key={cm.name} className="border-b hover:bg-slate-50 dark:hover:bg-accent transition-colors">
                                <td className="p-4">{cm.name}</td>
                                <td className="p-4">{cm.data_count} keys</td>
                                <td className="p-4 flex gap-2">
                                    <Button size="sm" variant="outline" onClick={() => handleView(cm)} disabled={loadingCM === cm.name}><Eye className="w-4 h-4" /></Button>
                                    <Button size="sm" variant="outline" onClick={() => handleEdit(cm)} disabled={loadingCM === cm.name}><Edit className="w-4 h-4" /></Button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                </>
                )}
            </CardContent>
            <Modal isOpen={isViewOpen} onClose={() => setIsViewOpen(false)} title={`View: ${selectedCM?.name}`} className="max-w-2xl">
                <div className="space-y-3 max-h-[70vh] overflow-auto">
                    {Object.entries(viewData).map(([key, value]) => (
                        <div key={key}>
                            <div className="text-xs font-bold text-muted-foreground mb-1">{key}</div>
                            <pre className="bg-muted p-3 rounded text-xs font-mono whitespace-pre-wrap break-all">{value}</pre>
                        </div>
                    ))}
                    {Object.keys(viewData).length === 0 && <p className="text-sm text-muted-foreground">This ConfigMap has no data keys.</p>}
                </div>
            </Modal>
            <Modal isOpen={isEditOpen} onClose={() => setIsEditOpen(false)} title={`Edit: ${selectedCM?.name}`}>
                <div className="space-y-4">
                    <textarea className="w-full h-64 p-2 border rounded font-mono text-xs bg-background" value={cmDataString} onChange={e => setCmDataString(e.target.value)} />
                    <Button onClick={async () => {
                        try {
                            await api.patch(`/k8s/namespaces/${namespace}/configmaps/${selectedCM.name}`, { data: JSON.parse(cmDataString) });
                            setIsEditOpen(false);
                            fetchConfigMaps();
                            toast("ConfigMap updated successfully", "success");
                        } catch (err) { toast("Patch failed — check JSON is valid", "error"); }
                    }}>Save</Button>
                </div>
            </Modal>
        </Card>
    );
}

// Secrets View
function SecretsView({ namespace }: { namespace: string }) {
    const [secrets, setSecrets] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [secretSearch, setSecretSearch] = useState("");
    useEffect(() => { fetchSecrets(); }, [namespace]);
    const fetchSecrets = async () => {
        setLoading(true);
        try {
            const res = await api.get(`/k8s/namespaces/${namespace}/secrets`);
            setSecrets(res.data);
        } catch (err) { console.error(err); }
        finally { setLoading(false); }
    };

    const filteredSecrets = secrets.filter(s => s.name.toLowerCase().includes(secretSearch.toLowerCase()));

    return (
        <Card>
            <CardHeader><CardTitle>Secrets in {namespace}</CardTitle></CardHeader>
            <CardContent>
                {loading ? (
                    <div className="flex items-center justify-center py-12 text-muted-foreground"><RotateCw className="w-5 h-5 animate-spin mr-2" />Loading secrets…</div>
                ) : secrets.length === 0 ? (
                    <EmptyState icon={Lock} title="No secrets found" description="No secrets were found in this namespace." />
                ) : (
                <>
                <div className="flex items-center gap-2 mb-3">
                    <div className="relative flex-1 max-w-sm">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
                        <input className="w-full pl-8 pr-3 h-8 text-sm border border-border rounded-md bg-background focus:outline-none focus:ring-1 focus:ring-blue-500" placeholder="Filter secrets…" value={secretSearch} onChange={e => setSecretSearch(e.target.value)} />
                    </div>
                    {secretSearch && <span className="text-xs text-muted-foreground">{filteredSecrets.length} / {secrets.length}</span>}
                </div>
                <table className="w-full text-sm">
                    <thead className="border-b"><tr><th className="p-4 text-left">Name</th><th className="p-4 text-left">Type</th></tr></thead>
                    <tbody>
                        {filteredSecrets.map(s => (
                            <tr key={s.name} className="border-b hover:bg-slate-50 dark:hover:bg-accent transition-colors">
                                <td className="p-4">{s.name}</td>
                                <td className="p-4">{s.type}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                </>
                )}
            </CardContent>
        </Card>
    );
}


