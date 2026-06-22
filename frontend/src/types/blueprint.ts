export interface Blueprint {
  id: string;
  name: string;
  yaml_body: string;
  updated_at: string;
}

export interface BlueprintSource {
  id: string;
  blueprint_id: string;
  name: string;
  content: string;
}

export interface BlueprintAssignment {
  id: string;
  blueprint_id: string;
  scope_type: "org" | "group" | "minion";
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
