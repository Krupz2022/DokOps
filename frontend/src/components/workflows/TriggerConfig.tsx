import { Copy } from "lucide-react";
import type { Workflow, WorkflowCreate } from "../../types/workflow";

interface Props {
  workflow: Partial<Workflow> & WorkflowCreate;
  onChange: (updates: Partial<WorkflowCreate>) => void;
}

export function TriggerConfig({ workflow, onChange }: Props) {
  const webhookUrl = workflow.webhook_token
    ? `${import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1"}/workflows/webhook/${workflow.webhook_token}`
    : null;

  const triggerTypes = ["manual", "webhook", "cron", "all", "alert"] as const;
  const current = workflow.trigger_type ?? "manual";

  return (
    <div className="bg-card border border-border rounded-lg p-4 space-y-3">
      <div className="text-foreground text-sm font-medium">Trigger</div>
      <div className="flex gap-2 flex-wrap">
        {triggerTypes.map((t) => (
          <button
            key={t}
            onClick={() => onChange({ trigger_type: t })}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              current === t
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-muted/70"
            }`}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {(current === "cron" || current === "all") && (
        <div>
          <label className="text-muted-foreground text-xs block mb-1">Cron schedule</label>
          <input
            value={workflow.cron_schedule ?? ""}
            onChange={(e) => onChange({ cron_schedule: e.target.value })}
            placeholder="0 9 * * 1 (every Monday 9am)"
            className="w-full bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
          />
        </div>
      )}

      {current === "alert" && (
        <div>
          <label className="text-muted-foreground text-xs block mb-1">Alert Name (exact match)</label>
          <input
            value={(() => {
              try { return JSON.parse(workflow.trigger_config || "{}").alert_name || ""; }
              catch { return ""; }
            })()}
            onChange={(e) =>
              onChange({ trigger_config: JSON.stringify({ alert_name: e.target.value }) })
            }
            placeholder="e.g. CrashLoopBackOff"
            className="w-full bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
          />
          <p className="text-xs text-muted-foreground mt-1">
            This workflow runs automatically when an alert with this name arrives.
          </p>
        </div>
      )}

      {(current === "webhook" || current === "all") && webhookUrl && (
        <div>
          <label className="text-muted-foreground text-xs block mb-1">Webhook URL</label>
          <div className="flex items-center gap-2 bg-background border border-border rounded px-2 py-1">
            <span className="text-foreground/70 text-xs flex-1 truncate font-mono">{webhookUrl}</span>
            <button
              onClick={() => navigator.clipboard.writeText(webhookUrl)}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <Copy size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
