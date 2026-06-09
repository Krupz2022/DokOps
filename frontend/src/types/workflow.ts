export interface JiraFieldSchema {
  id: string;
  name: string;
  type: "string" | "number" | "array" | "option" | "user" | "date";
  required: boolean;
  allowed_values?: string[] | null;
}

export interface JiraUser {
  account_id: string;
  display_name: string;
  email?: string;
}

export interface JiraCredentials {
  base_url: string;
  email: string;
  username: string;
  api_token: string;
  instance_type: "cloud" | "server_basic" | "server_pat";
}

export interface WorkflowStep {
  id: string;
  name: string;
  connector_type: "http" | "jenkins" | "argocd" | "slack" | "teams" | "jira" | "email" | "k8s" | "ai_analyze";
  config: Record<string, unknown>;
  on_failure: "stop" | "continue";
  output_var: string;
}

export interface Workflow {
  id: number;
  name: string;
  description: string;
  workflow_type?: string;
  trigger_type: "manual" | "webhook" | "cron" | "all" | "alert";
  webhook_token: string;
  cron_schedule: string | null;
  trigger_config?: string | null;
  input_schema: Record<string, string>;
  steps: WorkflowStep[];
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface WorkflowCreate {
  name: string;
  description?: string;
  trigger_type?: string;
  cron_schedule?: string;
  trigger_config?: string;
  input_schema?: Record<string, string>;
  steps?: WorkflowStep[];
}

export interface StepResult {
  step_id: string;
  step_name: string;
  status: "pending" | "running" | "passed" | "failed" | "skipped";
  started_at: string | null;
  completed_at: string | null;
  output: Record<string, unknown> | null;
  error: string | null;
}

export interface WorkflowRun {
  id: number;
  workflow_id: number;
  triggered_by: "manual" | "webhook" | "cron";
  trigger_input: Record<string, unknown>;
  status: "pending" | "running" | "completed" | "failed";
  started_at: string;
  completed_at: string | null;
  step_results: StepResult[];
  ai_summary: string | null;
}

export interface WorkflowSSEEvent {
  type: "step_update" | "step" | "result" | "completed" | "ping" | "error";
  step_id?: string;
  status?: string;
  message?: string;
  run_id?: number;
  error?: string;
}
