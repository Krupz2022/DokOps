import type { ResourceResult } from "../types/blueprint";

export function parseChanges(changes: Record<string, unknown> | string): Record<string, unknown> {
  if (typeof changes !== "string") return changes ?? {};
  try {
    const parsed = JSON.parse(changes);
    return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

export function resultChip(
  result: boolean | null,
  changes: Record<string, unknown> | string
): { label: string; tone: "amber" | "green" | "red" } {
  if (result === null) return { label: "would change", tone: "amber" };
  if (result === false) return { label: "failed", tone: "red" };
  const hasChanges = Object.keys(parseChanges(changes)).length > 0;
  return { label: hasChanges ? "changed" : "ok", tone: "green" };
}

export function resultRowId(r: ResourceResult): string {
  return r.resource_id ?? r.id ?? r.state_id ?? "?";
}

export function dryRunWarning(hasDryRun: boolean): string {
  return hasDryRun ? "" : "No dry-run has been run this session — apply anyway?";
}
