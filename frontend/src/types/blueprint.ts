export interface Blueprint {
  id: string;
  name: string;
  yaml_body: string;
  updated_at: string;
  org_ids?: string[];   // orgs this blueprint resolves to (via assignments); used to group the list
  is_global?: boolean;  // has a global assignment → applies to every minion
}

export interface BlueprintSource {
  id: string;
  blueprint_id: string;
  name: string;
  content: string;
  encoding?: "utf-8" | "base64";
  size?: number;
}

export interface BlueprintAssignment {
  id: string;
  blueprint_id: string;
  scope_type: "global" | "org" | "group" | "minion";
  scope_id: string;
}

export interface ResourceResult {
  resource_id?: string;
  id?: string;
  state_id?: string;
  result: boolean | null;
  changes: Record<string, unknown> | string;
  comment: string;
  output?: string;
}

export interface BlueprintRun {
  id: string;
  minion_id: string;
  actor: string;
  test: boolean;
  status: string;
  created_at: string;
  completed_at: string | null;
}

export interface CompiledResource {
  id: string;
  type: string;
  name?: string;
  [k: string]: unknown;
}

export interface CompiledBlueprint {
  resources: CompiledResource[];
  sources: Record<string, string>;
}

export interface RunResponse {
  run_id: string;
  test: boolean;
}

export type BlueprintEvent =
  | { kind: "resource_start"; id: string }
  | { kind: "log"; id: string; line: string }
  | { kind: "resource_result"; id: string; result: boolean | null; changes: Record<string, unknown> | string; comment: string; output?: string }
  | { kind: "done"; results: ResourceResult[] }
  | { kind: "error"; message: string };
