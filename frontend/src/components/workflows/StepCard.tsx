import { GripVertical, Trash2, ChevronDown, ChevronUp, ShieldAlert } from "lucide-react";
import { useState } from "react";
import type { WorkflowStep } from "../../types/workflow";
import { JiraFields } from "./JiraFields";

const CONNECTOR_LABELS: Record<string, string> = {
  http: "HTTP Request", jenkins: "Jenkins", argocd: "ArgoCD", k8s: "Kubernetes",
  slack: "Slack", teams: "Microsoft Teams", jira: "Jira", email: "Email", ai_analyze: "AI Analyze",
};

interface K8sActionMeta {
  label: string;
  description: string;
  fields: Array<{ key: string; label: string; placeholder?: string; type?: "number" }>;
  godMode?: boolean;
}

const K8S_ACTIONS: Record<string, K8sActionMeta> = {
  get_pod_logs:       { label: "Get Pod Logs",       description: "Fetch recent logs from a specific pod",              fields: [{ key: "namespace", label: "Namespace", placeholder: "default" }, { key: "pod_name", label: "Pod Name", placeholder: "my-pod-abc123" }, { key: "tail_lines", label: "Tail Lines", placeholder: "100", type: "number" }] },
  list_pods:          { label: "List Pods",           description: "List all pods in a namespace",                       fields: [{ key: "namespace", label: "Namespace", placeholder: "default" }] },
  list_namespaces:    { label: "List Namespaces",     description: "List all namespaces in the cluster",                 fields: [] },
  get_cluster_health: { label: "Cluster Health",      description: "Get a health report for the cluster",                fields: [] },
  list_deployments:   { label: "List Deployments",    description: "List all deployments in a namespace",                fields: [{ key: "namespace", label: "Namespace", placeholder: "default" }] },
  list_services:      { label: "List Services",       description: "List all services in a namespace",                   fields: [{ key: "namespace", label: "Namespace", placeholder: "default" }] },
  list_configmaps:    { label: "List ConfigMaps",     description: "List all configmaps in a namespace",                 fields: [{ key: "namespace", label: "Namespace", placeholder: "default" }] },
  list_secrets:       { label: "List Secrets",        description: "List secret names (values are masked)",              fields: [{ key: "namespace", label: "Namespace", placeholder: "default" }] },
  search_pods:        { label: "Search Pods",         description: "Search for pods by name across all namespaces",      fields: [{ key: "query", label: "Search Query", placeholder: "my-app" }] },
  scale_deployment:   { label: "Scale Deployment",    description: "Change the replica count of a deployment",           fields: [{ key: "namespace", label: "Namespace", placeholder: "default" }, { key: "deployment_name", label: "Deployment Name", placeholder: "my-deployment" }, { key: "replicas", label: "Replicas", placeholder: "2", type: "number" }], godMode: true },
  restart_deployment: { label: "Restart Deployment",  description: "Perform a rolling restart of a deployment",          fields: [{ key: "namespace", label: "Namespace", placeholder: "default" }, { key: "deployment_name", label: "Deployment Name", placeholder: "my-deployment" }], godMode: true },
  delete_pod:         { label: "Delete Pod",          description: "Delete a specific pod (it will be rescheduled)",     fields: [{ key: "namespace", label: "Namespace", placeholder: "default" }, { key: "pod_name", label: "Pod Name", placeholder: "my-pod-abc123" }], godMode: true },
};

const K8S_ACTION_ORDER = [
  "get_pod_logs", "list_pods", "list_namespaces", "get_cluster_health",
  "list_deployments", "list_services", "list_configmaps", "list_secrets", "search_pods",
  "scale_deployment", "restart_deployment", "delete_pod",
];

interface Props {
  step: WorkflowStep;
  index: number;
  previousOutputVars: string[];
  onChange: (updated: WorkflowStep) => void;
  onRemove: () => void;
}

function VarPills({ vars }: { vars: string[] }) {
  const [copied, setCopied] = useState<string | null>(null);
  if (vars.length === 0) return null;

  const copy = (v: string) => {
    const token = `{{steps.${v}}}`;
    navigator.clipboard.writeText(token);
    setCopied(v);
    setTimeout(() => setCopied(null), 1500);
  };

  return (
    <div className="flex flex-wrap gap-1 pt-1">
      <span className="text-muted-foreground text-xs self-center">Prev outputs:</span>
      {vars.map((v) => (
        <button
          key={v}
          onClick={() => copy(v)}
          title={`Click to copy {{steps.${v}}}`}
          className="text-xs px-1.5 py-0.5 rounded bg-primary/10 text-primary hover:bg-primary/20 border border-primary/20 font-mono transition-colors"
        >
          {copied === v ? "copied!" : `{{steps.${v}}}`}
        </button>
      ))}
    </div>
  );
}

function K8sFields({ step, onChange }: { step: WorkflowStep; onChange: (updated: WorkflowStep) => void }) {
  const action = String(step.config.action ?? "get_pod_logs");
  const meta = K8S_ACTIONS[action];

  const updateConfig = (key: string, value: string) => {
    onChange({ ...step, config: { ...step.config, [key]: value } });
  };

  const handleActionChange = (newAction: string) => {
    const newMeta = K8S_ACTIONS[newAction];
    const preserved: Record<string, unknown> = {
      cluster_context: step.config.cluster_context ?? "",
      action: newAction,
    };
    for (const f of (newMeta?.fields ?? [])) {
      preserved[f.key] = step.config[f.key] ?? "";
    }
    onChange({ ...step, config: preserved });
  };

  return (
    <div className="space-y-2">
      {/* Cluster */}
      <div className="flex gap-2 items-center">
        <label className="text-muted-foreground text-xs w-28 shrink-0">Cluster</label>
        <input
          value={String(step.config.cluster_context ?? "")}
          onChange={(e) => updateConfig("cluster_context", e.target.value)}
          placeholder="leave blank for default"
          className="flex-1 bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
        />
      </div>

      {/* Action dropdown */}
      <div className="flex gap-2 items-start">
        <label className="text-muted-foreground text-xs w-28 shrink-0 pt-1">Action</label>
        <div className="flex-1 space-y-1">
          <select
            value={action}
            onChange={(e) => handleActionChange(e.target.value)}
            className="w-full bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
          >
            {K8S_ACTION_ORDER.map((key) => {
              const m = K8S_ACTIONS[key];
              return (
                <option key={key} value={key}>
                  {m.label}{m.godMode ? " ⚠ God Mode" : ""}
                </option>
              );
            })}
          </select>
          {meta && (
            <p className="text-muted-foreground text-xs leading-snug">{meta.description}</p>
          )}
          {meta?.godMode && (
            <div className="flex items-center gap-1 text-amber-400 text-xs">
              <ShieldAlert size={12} />
              Requires God Mode to execute
            </div>
          )}
        </div>
      </div>

      {/* Dynamic fields for selected action */}
      {meta?.fields.map((f) => (
        <div key={f.key} className="flex gap-2 items-center">
          <label className="text-muted-foreground text-xs w-28 shrink-0">{f.label}</label>
          <input
            type={f.type === "number" ? "number" : "text"}
            value={String(step.config[f.key] ?? "")}
            onChange={(e) => updateConfig(f.key, e.target.value)}
            placeholder={f.placeholder}
            className="flex-1 bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
          />
        </div>
      ))}
    </div>
  );
}

function slugify(value: string): string {
  return value.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "");
}

function StepNameField({ step, onChange }: { step: WorkflowStep; onChange: (updated: WorkflowStep) => void }) {
  return (
    <div className="flex gap-2 items-center pb-2 border-b border-border mb-1">
      <label className="text-muted-foreground text-xs w-24 shrink-0 font-medium">Name</label>
      <input
        value={step.output_var}
        onChange={(e) => {
          const slug = slugify(e.target.value);
          onChange({ ...step, output_var: slug, name: e.target.value });
        }}
        placeholder="e.g. pod_logs, build_status"
        className="flex-1 bg-background border border-primary/40 rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary font-medium"
      />
      {step.output_var && (
        <span className="text-muted-foreground text-xs font-mono shrink-0">→ {`{{steps.${step.output_var}}}`}</span>
      )}
    </div>
  );
}

export function StepCard({ step, index, previousOutputVars, onChange, onRemove }: Props) {
  const [expanded, setExpanded] = useState(false);

  const updateConfig = (key: string, value: string) => {
    onChange({ ...step, config: { ...step.config, [key]: value } });
  };

  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2">
        <GripVertical size={16} className="text-muted-foreground cursor-grab" />
        <span className="text-muted-foreground text-xs w-5">{index + 1}.</span>
        <div className="flex-1">
          <div className="text-foreground text-sm font-medium">{step.output_var || step.name}</div>
          <div className="text-muted-foreground text-xs">{CONNECTOR_LABELS[step.connector_type] ?? step.connector_type}</div>
        </div>
        <button onClick={() => setExpanded(!expanded)} className="text-muted-foreground hover:text-foreground p-1 transition-colors">
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        <button onClick={onRemove} className="text-muted-foreground hover:text-destructive p-1 transition-colors">
          <Trash2 size={16} />
        </button>
      </div>

      {expanded && step.connector_type === "ai_analyze" && (
        <div className="px-3 pb-3 border-t border-border pt-3 space-y-2">
          <StepNameField step={step} onChange={onChange} />
          <p className="text-muted-foreground text-xs">
            The AI will automatically receive all step outputs collected so far and reason over them. No configuration needed.
          </p>
          <VarPills vars={previousOutputVars} />
          <div className="flex gap-2 items-center">
            <label className="text-muted-foreground text-xs w-24 shrink-0">on_failure</label>
            <select
              value={step.on_failure}
              onChange={(e) => onChange({ ...step, on_failure: e.target.value as "stop" | "continue" })}
              className="bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
            >
              <option value="stop">Stop</option>
              <option value="continue">Continue</option>
            </select>
          </div>
        </div>
      )}

      {expanded && step.connector_type === "jira" && (
        <div className="px-3 pb-3 border-t border-border pt-3 space-y-2">
          <StepNameField step={step} onChange={onChange} />
          <VarPills vars={previousOutputVars} />
          <JiraFields step={step} onChange={onChange} />
          <div className="flex gap-2 items-center border-t border-border pt-2 mt-1">
            <label className="text-muted-foreground text-xs w-24 shrink-0">on_failure</label>
            <select
              value={step.on_failure}
              onChange={(e) =>
                onChange({ ...step, on_failure: e.target.value as "stop" | "continue" })
              }
              className="bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
            >
              <option value="stop">Stop</option>
              <option value="continue">Continue</option>
            </select>
          </div>
        </div>
      )}

      {expanded && step.connector_type === "k8s" && (
        <div className="px-3 pb-3 border-t border-border pt-3 space-y-2">
          <StepNameField step={step} onChange={onChange} />
          <VarPills vars={previousOutputVars} />
          <K8sFields step={step} onChange={onChange} />
          <div className="flex gap-2 items-center border-t border-border pt-2 mt-1">
            <label className="text-muted-foreground text-xs w-28 shrink-0">On Failure</label>
            <select
              value={step.on_failure}
              onChange={(e) => onChange({ ...step, on_failure: e.target.value as "stop" | "continue" })}
              className="bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
            >
              <option value="stop">Stop</option>
              <option value="continue">Continue</option>
            </select>
          </div>
        </div>
      )}

      {expanded && step.connector_type !== "ai_analyze" && step.connector_type !== "k8s" && step.connector_type !== "jira" && (
        <div className="px-3 pb-3 border-t border-border pt-3 space-y-2">
          <StepNameField step={step} onChange={onChange} />
          <VarPills vars={previousOutputVars} />
          {Object.entries(step.config).map(([key, value]) => (
            <div key={key} className="flex gap-2 items-center">
              <label className="text-muted-foreground text-xs w-24 shrink-0">{key}</label>
              <input
                value={String(value)}
                onChange={(e) => updateConfig(key, e.target.value)}
                className="flex-1 bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
              />
            </div>
          ))}
          <div className="flex gap-2 items-center border-t border-border pt-2 mt-1">
            <label className="text-muted-foreground text-xs w-24 shrink-0">on_failure</label>
            <select
              value={step.on_failure}
              onChange={(e) => onChange({ ...step, on_failure: e.target.value as "stop" | "continue" })}
              className="bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
            >
              <option value="stop">Stop</option>
              <option value="continue">Continue</option>
            </select>
          </div>
        </div>
      )}
    </div>
  );
}
