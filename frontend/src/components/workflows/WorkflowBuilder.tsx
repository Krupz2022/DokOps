import { useState } from "react";
import { Plus, Save, X } from "lucide-react";
import type { Workflow, WorkflowCreate, WorkflowStep } from "../../types/workflow";
import { workflowApi } from "../../lib/api";
import { TriggerConfig } from "./TriggerConfig";
import { StepCard } from "./StepCard";
import { ConnectorPicker } from "./ConnectorPicker";
import { FlowPreview } from "./FlowPreview";

interface Props {
  workflow?: Workflow;
  onSave: (id: number) => void;
  onCancel: () => void;
}

type ConnectorType = WorkflowStep["connector_type"];

const CONNECTOR_LABELS: Record<ConnectorType, string> = {
  http: "HTTP Request",
  jenkins: "Jenkins",
  argocd: "ArgoCD",
  k8s: "Kubernetes",
  slack: "Slack",
  teams: "Microsoft Teams",
  jira: "Jira",
  email: "Email",
  ai_analyze: "AI Analyze",
};

const DEFAULT_CONFIGS: Record<ConnectorType, Record<string, unknown>> = {
  http:       { url: "", method: "GET" },
  jenkins:    { base_url: "", username: "", api_token: "", job_name: "" },
  argocd:     { base_url: "", token: "", app_name: "" },
  k8s:        { cluster_context: "", action: "get_pod_logs", namespace: "default", pod_name: "", tail_lines: "100" },
  slack:      { webhook_url: "", message: "" },
  teams:      { webhook_url: "", message: "" },
  jira:       { base_url: "", email: "", api_token: "", action: "create_issue", project_key: "", issue_type: "Bug", summary: "", custom_fields: {} },
  email:      { smtp_host: "", smtp_port: "587", username: "", password: "", to: "", subject: "", body: "" },
  ai_analyze: {},
};

function buildInitialDraft(workflow?: Workflow): WorkflowCreate {
  if (workflow) {
    return {
      name: workflow.name,
      description: workflow.description,
      trigger_type: workflow.trigger_type,
      cron_schedule: workflow.cron_schedule ?? undefined,
      input_schema: workflow.input_schema,
      steps: workflow.steps,
    };
  }
  return {
    name: "",
    description: "",
    trigger_type: "manual",
    steps: [],
  };
}

export function WorkflowBuilder({ workflow, onSave, onCancel }: Props) {
  const [draft, setDraft] = useState<WorkflowCreate>(() => buildInitialDraft(workflow));
  const [saving, setSaving] = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const steps: WorkflowStep[] = draft.steps ?? [];

  const handleTriggerChange = (updates: Partial<WorkflowCreate>) => {
    setDraft((prev) => ({ ...prev, ...updates }));
  };

  const handleSelectConnector = (type: string) => {
    const connectorType = type as ConnectorType;
    const id = crypto.randomUUID();
    const sameTypeCount = (draft.steps ?? []).filter((s) => s.connector_type === connectorType).length;
    const outputVar = sameTypeCount === 0 ? connectorType : `${connectorType}_${sameTypeCount + 1}`;
    const newStep: WorkflowStep = {
      id,
      name: CONNECTOR_LABELS[connectorType] ?? type,
      connector_type: connectorType,
      config: { ...DEFAULT_CONFIGS[connectorType] },
      output_var: outputVar,
      on_failure: "stop",
    };
    setDraft((prev) => ({ ...prev, steps: [...(prev.steps ?? []), newStep] }));
    setShowPicker(false);
  };

  const handleStepChange = (index: number, updated: WorkflowStep) => {
    const newSteps = [...steps];
    newSteps[index] = updated;
    setDraft((prev) => ({ ...prev, steps: newSteps }));
  };

  const handleStepRemove = (index: number) => {
    setDraft((prev) => ({
      ...prev,
      steps: (prev.steps ?? []).filter((_, i) => i !== index),
    }));
  };

  const handleSave = async () => {
    if (!draft.name.trim()) {
      setError("Workflow name is required");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      let result: Workflow;
      if (workflow) {
        const res = await workflowApi.update(workflow.id, draft);
        result = res.data;
      } else {
        const res = await workflowApi.create(draft);
        result = res.data;
      }
      onSave(result.id);
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      setError(e.response?.data?.detail ?? e.message ?? "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const draftAsWorkflow: Partial<Workflow> & WorkflowCreate = {
    ...draft,
    trigger_type: draft.trigger_type as Workflow["trigger_type"],
    webhook_token: workflow?.webhook_token,
  };

  return (
    <div className="h-full grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-4">
      {/* Left panel — scrollable config */}
      <div className="overflow-y-auto space-y-4 pr-1">
        <TriggerConfig workflow={draftAsWorkflow} onChange={handleTriggerChange} />

        <div className="space-y-2">
          {steps.map((step, i) => (
            <StepCard
              key={step.id}
              step={step}
              index={i}
              previousOutputVars={steps.slice(0, i).map((s) => s.output_var).filter(Boolean)}
              onChange={(updated) => handleStepChange(i, updated)}
              onRemove={() => handleStepRemove(i)}
            />
          ))}
        </div>

        <button
          onClick={() => setShowPicker(true)}
          className="w-full flex items-center justify-center gap-2 py-2 rounded-lg border border-dashed border-border text-muted-foreground hover:border-primary hover:text-primary transition-colors text-sm"
        >
          <Plus size={16} />
          Add Step
        </button>
      </div>

      {/* Right panel — fixed height, buttons always visible */}
      <div className="flex flex-col gap-3 h-full overflow-hidden">
        {/* Name & description */}
        <div className="bg-card border border-border rounded-lg p-4 space-y-3 flex-shrink-0">
          <div>
            <label className="text-muted-foreground text-xs block mb-1">Name *</label>
            <input
              value={draft.name}
              onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
              placeholder="My Workflow"
              className="w-full bg-background border border-border rounded px-3 py-1.5 text-foreground text-sm outline-none focus:border-primary"
            />
          </div>
          <div>
            <label className="text-muted-foreground text-xs block mb-1">Description</label>
            <textarea
              value={draft.description ?? ""}
              onChange={(e) => setDraft((prev) => ({ ...prev, description: e.target.value }))}
              placeholder="What does this workflow do?"
              rows={2}
              className="w-full bg-background border border-border rounded px-3 py-1.5 text-foreground text-sm outline-none focus:border-primary resize-none"
            />
          </div>
        </div>

        {/* Flow preview — flex-1 so it fills remaining space */}
        <div className="bg-card border border-border rounded-lg p-4 flex-1 min-h-0 overflow-y-auto">
          <div className="text-muted-foreground text-xs font-medium mb-3">Flow Preview</div>
          <FlowPreview steps={steps} />
        </div>

        {/* Actions — always pinned at bottom */}
        {error && (
          <div className="text-red-400 text-xs bg-red-900/20 border border-red-800 rounded-lg px-3 py-2 flex-shrink-0">
            {error}
          </div>
        )}
        <div className="flex gap-2 flex-shrink-0">
          <button
            onClick={onCancel}
            className="flex items-center gap-1 px-4 py-2 rounded-lg bg-muted text-muted-foreground hover:bg-muted/70 text-sm transition-colors"
          >
            <X size={14} />
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-primary hover:bg-primary/90 text-primary-foreground text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Save size={14} />
            {saving ? "Saving…" : workflow ? "Update Workflow" : "Save Workflow"}
          </button>
        </div>
      </div>

      {showPicker && (
        <ConnectorPicker
          onSelect={handleSelectConnector}
          onClose={() => setShowPicker(false)}
        />
      )}
    </div>
  );
}
