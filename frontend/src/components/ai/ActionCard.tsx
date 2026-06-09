import React from "react";
import { AlertTriangle, CheckCircle, XCircle } from "lucide-react";
import { Button } from "../ui/Button";

interface ActionCardProps {
    proposal: {
        summary: string;
        risk_level: "low" | "medium" | "high";
        tool: string;
        parameters: any;
    };
    onApprove: (params: any) => void;
    onReject: () => void;
    godMode: boolean;
    loading?: boolean;
}

export function ActionCard({ proposal, onApprove, onReject, godMode, loading }: ActionCardProps) {
    const isHighRisk = proposal.risk_level === "high";

    // Local state for editable parameters
    const [editedParams, setEditedParams] = React.useState(proposal.parameters);
    const [isEditing, setIsEditing] = React.useState(false);

    // Sync if proposal changes
    React.useEffect(() => {
        setEditedParams(proposal.parameters);
    }, [proposal]);

    const handleParamChange = (key: string, value: any) => {
        setEditedParams((prev: any) => ({ ...prev, [key]: value }));
    };

    return (
        <div className={`border rounded-lg p-4 ${isHighRisk ? "bg-red-500/10 border-red-500/50" : "bg-blue-500/10 border-blue-500/50"}`}>
            <div className="flex items-start gap-4">
                <div className={`p-2 rounded-full ${isHighRisk ? "bg-red-500/20 text-red-500" : "bg-blue-500/20 text-blue-500"}`}>
                    <AlertTriangle className="w-6 h-6" />
                </div>
                <div className="flex-1">
                    <h3 className="text-lg font-bold mb-1">Action Proposed</h3>
                    <p className="text-sm text-foreground/80 mb-4">{proposal.summary}</p>
                </div>
                {Object.keys(editedParams).length > 0 && (
                    <Button
                        variant="ghost"
                        size="sm"
                        className="text-xs"
                        onClick={() => setIsEditing(!isEditing)}
                    >
                        {isEditing ? "Done Editing" : "Edit Parameters"}
                    </Button>
                )}
            </div>

            {isEditing ? (
                <div className="bg-background/80 p-4 rounded-md border mb-4 space-y-3">
                    <h4 className="text-xs font-bold uppercase text-muted-foreground">Parameters</h4>

                    {/* Namespace Field */}
                    {editedParams.namespace !== undefined && (
                        <div className="grid grid-cols-4 items-center gap-2">
                            <label className="text-xs font-medium text-right">Namespace:</label>
                            <div className="col-span-3">
                                <input
                                    type="text"
                                    value={editedParams.namespace || ""}
                                    onChange={(e) => handleParamChange("namespace", e.target.value)}
                                    className="w-full px-2 py-1 text-sm border rounded bg-background"
                                    placeholder="e.g. default, new-ns"
                                />
                                <p className="text-[10px] text-muted-foreground mt-1">
                                    Type a new namespace to create it automatically.
                                </p>
                            </div>
                        </div>
                    )}

                    {/* Name Field */}
                    {editedParams.name !== undefined && (
                        <div className="grid grid-cols-4 items-center gap-2">
                            <label className="text-xs font-medium text-right">Name:</label>
                            <input
                                type="text"
                                value={editedParams.name}
                                onChange={(e) => handleParamChange("name", e.target.value)}
                                className="col-span-3 px-2 py-1 text-sm border rounded bg-background"
                            />
                        </div>
                    )}

                    {/* Replicas Field */}
                    {editedParams.replicas !== undefined && (
                        <div className="grid grid-cols-4 items-center gap-2">
                            <label className="text-xs font-medium text-right">Replicas:</label>
                            <input
                                type="number"
                                value={editedParams.replicas}
                                onChange={(e) => handleParamChange("replicas", parseInt(e.target.value) || 0)}
                                className="col-span-3 px-2 py-1 text-sm border rounded bg-background"
                            />
                        </div>
                    )}

                    {/* Image Field (for create) */}
                    {editedParams.image !== undefined && (
                        <div className="grid grid-cols-4 items-center gap-2">
                            <label className="text-xs font-medium text-right">Image:</label>
                            <input
                                type="text"
                                value={editedParams.image}
                                onChange={(e) => handleParamChange("image", e.target.value)}
                                className="col-span-3 px-2 py-1 text-sm border rounded bg-background"
                            />
                        </div>
                    )}

                </div>
            ) : (
                Object.keys(editedParams).length > 0 && (
                    <div className="bg-background/50 p-2 rounded text-xs font-mono mb-4 border">
                        {/* Show Edited Params in Read-Only Mode */}
                        {JSON.stringify(editedParams, null, 2)}
                    </div>
                )
            )}

            {!godMode && (
                <div className="text-xs text-amber-500 font-bold mb-4 flex items-center gap-2">
                    <AlertTriangle className="w-3 h-3" />
                    God Mode required to approve this action.
                </div>
            )}

            <div className="flex gap-3 justify-end">
                <Button variant="outline" onClick={onReject} disabled={loading}>
                    <XCircle className="w-4 h-4 mr-2" />
                    Reject
                </Button>
                <Button
                    variant={isHighRisk ? "destructive" : "default"}
                    onClick={() => onApprove(editedParams)}
                    disabled={!godMode || loading}
                >
                    {loading ? "Executing..." : (
                        <>
                            <CheckCircle className="w-4 h-4 mr-2" />
                            {isEditing ? "Save & Execute" : "Approve & Execute"}
                        </>
                    )}
                </Button>
            </div>
        </div>
    );
}
