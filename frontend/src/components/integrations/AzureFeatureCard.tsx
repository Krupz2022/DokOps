import { useState } from "react";
import { AlertTriangle, Clock, Loader2 } from "lucide-react";
import { cn } from "../../lib/utils";

interface AzureFeatureCardProps {
  featureKey: string;
  title: string;
  description: string;
  enabled: boolean;
  lastSyncedAt?: string | null;
  incursCost: boolean;
  costWarning?: string;
  onToggle: (key: string, enabled: boolean) => Promise<void>;
}

export function AzureFeatureCard({
  featureKey,
  title,
  description,
  enabled,
  lastSyncedAt,
  incursCost,
  costWarning,
  onToggle,
}: AzureFeatureCardProps) {
  const [loading, setLoading] = useState(false);
  const [showCostConfirm, setShowCostConfirm] = useState(false);

  const handleToggle = async () => {
    const nextEnabled = !enabled;
    if (nextEnabled && incursCost) {
      setShowCostConfirm(true);
      return;
    }
    await doToggle(nextEnabled);
  };

  const doToggle = async (nextEnabled: boolean) => {
    setLoading(true);
    setShowCostConfirm(false);
    try {
      await onToggle(featureKey, nextEnabled);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div
        className={cn(
          "relative rounded-xl border p-5 flex flex-col gap-3 transition-all",
          enabled
            ? "border-blue-500/50 bg-blue-500/5 dark:bg-blue-950/20"
            : "border-slate-200 dark:border-border bg-white dark:bg-card"
        )}
      >
        {/* Title row */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1">
            <h3 className="font-semibold text-slate-900 dark:text-foreground text-sm">{title}</h3>
            <p className="text-xs text-slate-500 dark:text-muted-foreground mt-0.5 leading-relaxed">
              {description}
            </p>
          </div>
          {/* Toggle */}
          <button
            onClick={handleToggle}
            disabled={loading}
            className={cn(
              "relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent",
              "transition-colors duration-200 ease-in-out focus:outline-none mt-0.5",
              enabled ? "bg-blue-600" : "bg-slate-200 dark:bg-muted",
              loading && "opacity-50 cursor-not-allowed"
            )}
            aria-pressed={enabled}
          >
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 text-white absolute top-0.5 left-0.5 animate-spin" />
            ) : (
              <span
                className={cn(
                  "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out",
                  enabled ? "translate-x-4" : "translate-x-0"
                )}
              />
            )}
          </button>
        </div>

        {/* Cost warning badge */}
        {incursCost && (
          <div className="flex items-start gap-1.5 rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/50 px-3 py-2">
            <AlertTriangle className="h-3.5 w-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
            <p className="text-xs text-amber-700 dark:text-amber-400 leading-relaxed">
              {costWarning}
            </p>
          </div>
        )}

        {/* Last synced */}
        {enabled && lastSyncedAt && (
          <div className="flex items-center gap-1.5 text-xs text-slate-400 dark:text-muted-foreground">
            <Clock className="h-3 w-3" />
            Last synced: {new Date(lastSyncedAt).toLocaleString()}
          </div>
        )}
      </div>

      {/* Cost confirmation dialog */}
      {showCostConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white dark:bg-card rounded-xl shadow-xl border border-slate-200 dark:border-border p-6 max-w-md w-full mx-4">
            <div className="flex items-center gap-3 mb-3">
              <AlertTriangle className="h-5 w-5 text-amber-500 flex-shrink-0" />
              <h2 className="font-semibold text-slate-900 dark:text-foreground">Potential Azure Charges</h2>
            </div>
            <p className="text-sm text-slate-600 dark:text-muted-foreground mb-5 leading-relaxed">
              {costWarning}
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowCostConfirm(false)}
                className="px-4 py-2 rounded-lg text-sm text-slate-600 dark:text-muted-foreground hover:bg-slate-100 dark:hover:bg-accent transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => doToggle(true)}
                className="px-4 py-2 rounded-lg text-sm bg-blue-600 text-white hover:bg-blue-700 transition-colors"
              >
                Enable Anyway
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
