import { describe, it, expect } from "vitest";
import { parseChanges, resultChip, resultRowId, dryRunWarning } from "./blueprintView";

describe("parseChanges", () => {
  it("passes objects through", () => {
    expect(parseChanges({ old: "a", new: "b" })).toEqual({ old: "a", new: "b" });
  });
  it("parses JSON strings", () => {
    expect(parseChanges('{"new":"x"}')).toEqual({ new: "x" });
  });
  it("returns {} on bad input", () => {
    expect(parseChanges("not json")).toEqual({});
    expect(parseChanges("")).toEqual({});
  });
});

describe("resultChip", () => {
  it("null => would change (amber)", () => {
    expect(resultChip(null, {})).toEqual({ label: "would change", tone: "amber" });
  });
  it("false => failed (red)", () => {
    expect(resultChip(false, {})).toEqual({ label: "failed", tone: "red" });
  });
  it("true with changes => changed (green)", () => {
    expect(resultChip(true, { new: "x" })).toEqual({ label: "changed", tone: "green" });
  });
  it("true without changes => ok (green)", () => {
    expect(resultChip(true, {})).toEqual({ label: "ok", tone: "green" });
  });
});

describe("resultRowId", () => {
  it("prefers resource_id, falls back to id then state_id", () => {
    expect(resultRowId({ resource_id: "a", result: true, changes: {}, comment: "" })).toBe("a");
    expect(resultRowId({ id: "b", result: true, changes: {}, comment: "" })).toBe("b");
    expect(resultRowId({ state_id: "c", result: true, changes: {}, comment: "" })).toBe("c");
  });
});

describe("dryRunWarning", () => {
  it("warns when no dry-run was done", () => {
    expect(dryRunWarning(false)).toContain("No dry-run");
  });
  it("empty when a dry-run was done", () => {
    expect(dryRunWarning(true)).toBe("");
  });
});
