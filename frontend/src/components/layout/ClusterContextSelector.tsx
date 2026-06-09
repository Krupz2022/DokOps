import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../lib/api";
import { ChevronDown, Plus, Server } from "lucide-react";
import { Button } from "../ui/Button";

interface ClusterContextSelectorProps {
    onContextChange?: (context: string) => void;
}

interface ClusterItem {
    id: string;
    name: string;
}

export function ClusterContextSelector({ onContextChange }: ClusterContextSelectorProps) {
    const navigate = useNavigate();
    const [clusters, setClusters] = useState<ClusterItem[]>([]);
    const [selectedContext, setSelectedContext] = useState<string>("");
    const [isOpen, setIsOpen] = useState(false);

    useEffect(() => {
        const stored = localStorage.getItem("clusterContext");
        if (stored) setSelectedContext(stored);
        fetchContexts();
    }, []);

    const fetchContexts = async () => {
        try {
            const res = await api.get<ClusterItem[]>("/clusters/");
            const list: ClusterItem[] = Array.isArray(res.data) ? res.data : [];
            setClusters(list);

            if (list.length === 0) {
                // Keep the last known context in the selector rather than blanking it —
                // the backend may be momentarily unreachable but the cluster connection is live.
                return;
            }

            const stored = localStorage.getItem("clusterContext");
            const names = list.map(c => c.name);
            if (stored && names.includes(stored)) {
                setSelectedContext(stored);
            } else {
                setSelectedContext(list[0].name);
                localStorage.setItem("clusterContext", list[0].name);
                window.dispatchEvent(new Event("clusterContextChanged"));
            }
        } catch {
            setClusters([]);
            setSelectedContext("");
        }
    };

    const handleSelect = (name: string) => {
        setSelectedContext(name);
        localStorage.setItem("clusterContext", name);
        setIsOpen(false);
        if (onContextChange) onContextChange(name);
        window.dispatchEvent(new Event("clusterContextChanged"));
    };

    return (
        <div className="relative">
            <Button
                variant="outline"
                className="flex items-center gap-2"
                onClick={() => setIsOpen(!isOpen)}
            >
                <Server className="w-4 h-4 text-muted-foreground" />
                <span className="font-medium text-sm max-w-[200px] truncate">{selectedContext || "No Context"}</span>
                <ChevronDown className={`w-3 h-3 opacity-50 transition-transform ${isOpen ? "rotate-180" : ""}`} />
            </Button>

            {isOpen && (
                <>
                    <div className="fixed inset-0 z-[59]" onClick={() => setIsOpen(false)} />
                    <div className="absolute top-full mt-2 left-0 w-72 bg-card border rounded-lg shadow-xl z-[60] p-2 animate-in fade-in zoom-in-95 duration-200">
                        <div className="mb-2 px-2 py-1 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                            Switch Context
                        </div>
                        <div className="space-y-1 max-h-60 overflow-y-auto">
                            {clusters.length === 0 && (
                                <p className="text-xs text-muted-foreground px-3 py-4 text-center">No clusters found.</p>
                            )}
                            {clusters.map(c => (
                                <button
                                    key={c.id}
                                    onClick={() => handleSelect(c.name)}
                                    className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center justify-between
                                        ${selectedContext === c.name
                                            ? "bg-primary/10 text-primary font-medium"
                                            : "hover:bg-muted text-foreground/80"
                                        }`}
                                >
                                    <span className="truncate">{c.name}</span>
                                    {selectedContext === c.name && <div className="w-2 h-2 rounded-full bg-primary shrink-0" />}
                                </button>
                            ))}
                        </div>
                        <div className="border-t my-2" />
                        <Button
                            variant="ghost"
                            className="w-full justify-start text-xs h-8"
                            onClick={() => { setIsOpen(false); navigate("/clusters"); }}
                        >
                            <Plus className="w-3 h-3 mr-2" />
                            Add New Cluster
                        </Button>
                    </div>
                </>
            )}
        </div>
    );
}
