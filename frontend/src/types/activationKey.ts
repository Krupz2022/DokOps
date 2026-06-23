export interface ActivationKey {
  id: string;
  name: string;
  org_id: string | null;
  group_id: string | null;
  run_on_attach: boolean;
  enabled: boolean;
  created_at: string;
  blueprint_ids: string[];
}

export interface CreatedKey {
  key: ActivationKey;
  value: string; // shown once
}
