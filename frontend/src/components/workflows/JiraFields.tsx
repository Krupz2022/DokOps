import { useState, useEffect } from "react";
import { Loader2 } from "lucide-react";
import type { WorkflowStep, JiraFieldSchema } from "../../types/workflow";
import { DynamicField } from "./DynamicField";
import { jiraApi } from "../../lib/api";

interface Props {
  step: WorkflowStep;
  onChange: (updated: WorkflowStep) => void;
}

const ISSUE_TYPES = ["Bug", "Story", "Task", "Epic", "Sub-task", "Improvement", "New Feature"];

const INPUT =
  "bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary w-full";

export function JiraFields({ step, onChange }: Props) {
  const [fetchStatus, setFetchStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [fieldSchema, setFieldSchema] = useState<JiraFieldSchema[]>([]);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [showOptional, setShowOptional] = useState(false);
  const [showRawJson, setShowRawJson] = useState(false);
  const [rawJson, setRawJson] = useState("");
  const [rawJsonError, setRawJsonError] = useState<string | null>(null);
  const [issueTypes, setIssueTypes] = useState<string[]>([]);
  const [issueTypesLoading, setIssueTypesLoading] = useState(false);

  const cfg = step.config as Record<string, unknown>;
  const action = String(cfg.action ?? "create_issue");
  const customFields = (cfg.custom_fields ?? {}) as Record<string, unknown>;

  const instanceType = (String(cfg.instance_type ?? "cloud")) as "cloud" | "server_basic" | "server_pat";

  const credentials = {
    instance_type: instanceType,
    base_url: String(cfg.base_url ?? ""),
    email: String(cfg.email ?? ""),
    username: String(cfg.username ?? ""),
    api_token: String(cfg.api_token ?? ""),
  };

  const updateCfg = (key: string, value: unknown) =>
    onChange({ ...step, config: { ...cfg, [key]: value } });

  const updateCustomField = (id: string, value: unknown) =>
    onChange({
      ...step,
      config: { ...cfg, custom_fields: { ...customFields, [id]: value } },
    });

  const canFetch =
    credentials.base_url &&
    credentials.api_token &&
    String(cfg.project_key ?? "") &&
    (instanceType === "cloud"
      ? credentials.email
      : instanceType === "server_basic"
      ? credentials.username
      : true);

  const fetchIssueTypes = async () => {
    if (!canFetch) return;
    setIssueTypesLoading(true);
    try {
      const { data } = await jiraApi.getIssueTypes({
        ...credentials,
        project_key: String(cfg.project_key ?? ""),
      });
      if (data.length) setIssueTypes(data);
    } catch {
      // silently fall back to hardcoded list
    } finally {
      setIssueTypesLoading(false);
    }
  };

  // Auto-fetch on mount if config is already filled in (e.g. workflow loaded from DB)
  useEffect(() => {
    if (canFetch) fetchIssueTypes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFetch = async () => {
    setFetchStatus("loading");
    setFetchError(null);
    try {
      const { data } = await jiraApi.getFields({
        ...credentials,
        project_key: String(cfg.project_key ?? ""),
        issue_type: String(cfg.issue_type ?? "Bug"),
      });
      setFieldSchema(data);
      setFetchStatus("success");
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to load fields from Jira";
      setFetchError(msg);
      setFetchStatus("error");
    }
  };

  const handleRawJsonBlur = () => {
    if (!rawJson.trim() || rawJsonError) return;
    try {
      const parsed = JSON.parse(rawJson);
      onChange({
        ...step,
        config: { ...cfg, custom_fields: { ...customFields, ...parsed } },
      });
      setRawJson("");
    } catch {
      // error already set inline
    }
  };

  const required = fieldSchema.filter((f) => f.required);
  const optional = fieldSchema.filter((f) => !f.required);

  return (
    <div className="space-y-2">
      {/* ── Instance type ── */}
      <div>
        <label className="text-muted-foreground text-xs block mb-1">instance_type</label>
        <div className="flex gap-1">
          {(["cloud", "server_basic", "server_pat"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => updateCfg("instance_type", t)}
              className={`px-2 py-0.5 text-xs rounded border transition-colors ${
                instanceType === t
                  ? "border-primary bg-primary/10 text-primary font-medium"
                  : "border-border text-muted-foreground hover:border-primary/50"
              }`}
            >
              {t === "cloud" ? "Cloud" : t === "server_basic" ? "Server (Basic)" : "Server (PAT)"}
            </button>
          ))}
        </div>
      </div>

      {/* ── Credential grid ── */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-2">
        <div>
          <label className="text-muted-foreground text-xs block mb-0.5">base_url</label>
          <input
            value={String(cfg.base_url ?? "")}
            onChange={(e) => updateCfg("base_url", e.target.value)}
            placeholder="https://acme.atlassian.net"
            className={INPUT}
          />
        </div>
        <div>
          <label className="text-muted-foreground text-xs block mb-0.5">project_key</label>
          <input
            value={String(cfg.project_key ?? "")}
            onChange={(e) => updateCfg("project_key", e.target.value)}
            onBlur={fetchIssueTypes}
            placeholder="OPS"
            className={INPUT}
          />
        </div>
        {instanceType === "cloud" && (
          <div>
            <label className="text-muted-foreground text-xs block mb-0.5">email</label>
            <input
              value={String(cfg.email ?? "")}
              onChange={(e) => updateCfg("email", e.target.value)}
              placeholder="ops@acme.com"
              className={INPUT}
            />
          </div>
        )}
        {instanceType === "server_basic" && (
          <div>
            <label className="text-muted-foreground text-xs block mb-0.5">username</label>
            <input
              value={String(cfg.username ?? "")}
              onChange={(e) => updateCfg("username", e.target.value)}
              placeholder="jirauser"
              className={INPUT}
            />
          </div>
        )}
        <div>
          <label className="text-muted-foreground text-xs block mb-0.5">issue_type</label>
          <div className="flex gap-1.5">
            <select
              value={String(cfg.issue_type ?? "Bug")}
              onChange={(e) => updateCfg("issue_type", e.target.value)}
              className={INPUT}
            >
              {(issueTypes.length ? issueTypes : ISSUE_TYPES).map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={fetchIssueTypes}
              disabled={!canFetch || issueTypesLoading}
              title={canFetch ? "Load issue types from Jira" : "Fill in credentials and project key first"}
              className="flex items-center gap-1 px-2 py-1 rounded border border-border bg-muted/40 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs shrink-0"
            >
              {issueTypesLoading
                ? <Loader2 size={12} className="animate-spin" />
                : "↻"}
            </button>
          </div>
        </div>
        <div className="col-span-2">
          <label className="text-muted-foreground text-xs block mb-0.5">
            {instanceType === "cloud" ? "api_token" : instanceType === "server_basic" ? "password" : "personal_access_token"}
          </label>
          <input
            type="password"
            value={String(cfg.api_token ?? "")}
            onChange={(e) => updateCfg("api_token", e.target.value)}
            placeholder="Jira API token"
            className={INPUT}
          />
        </div>
        <div className="col-span-2">
          <label className="text-muted-foreground text-xs block mb-0.5">action</label>
          <select
            value={action}
            onChange={(e) => updateCfg("action", e.target.value)}
            className={INPUT}
          >
            <option value="create_issue">Create Issue</option>
            <option value="add_comment">Add Comment</option>
          </select>
        </div>
      </div>

      {/* ── add_comment fields ── */}
      {action === "add_comment" && (
        <>
          <div className="flex gap-2 items-center">
            <label className="text-muted-foreground text-xs w-24 shrink-0">issue_key</label>
            <input
              value={String(cfg.issue_key ?? "")}
              onChange={(e) => updateCfg("issue_key", e.target.value)}
              placeholder="OPS-123 or {{steps.create_ticket.issue_key}}"
              className="flex-1 bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
            />
          </div>
          <div className="flex gap-2 items-center">
            <label className="text-muted-foreground text-xs w-24 shrink-0">comment</label>
            <input
              value={String(cfg.comment ?? "")}
              onChange={(e) => updateCfg("comment", e.target.value)}
              placeholder="{{steps.ai_analyze}}"
              className="flex-1 bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
            />
          </div>
        </>
      )}

      {/* ── create_issue standard fields + load banner ── */}
      {action === "create_issue" && (
        <>
          <div className="flex gap-2 items-center">
            <label className="text-muted-foreground text-xs w-24 shrink-0">summary</label>
            <input
              value={String(cfg.summary ?? "")}
              onChange={(e) => updateCfg("summary", e.target.value)}
              placeholder="{{steps.ai_analyze}} or plain text"
              className="flex-1 bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary"
            />
          </div>

          {/* Fetch banner */}
          <div className="flex items-center gap-2 px-3 py-2 bg-primary/5 border border-primary/20 rounded">
            <span className="text-muted-foreground text-xs flex-1">
              Load custom fields for{" "}
              <span className="text-foreground font-medium">
                {String(cfg.project_key || "…")} /{" "}
                {String(cfg.issue_type ?? "Bug")}
              </span>
            </span>
            <button
              onClick={handleFetch}
              disabled={!canFetch || fetchStatus === "loading"}
              className="text-xs px-2 py-1 rounded bg-primary/10 text-primary hover:bg-primary/20 border border-primary/20 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1 transition-colors"
            >
              {fetchStatus === "loading" && (
                <Loader2 size={10} className="animate-spin" />
              )}
              Load Fields
            </button>
          </div>

          {/* Fetch error */}
          {fetchStatus === "error" && fetchError && (
            <div className="text-xs text-destructive bg-destructive/10 border border-destructive/40 rounded px-2 py-1.5">
              {fetchError}
            </div>
          )}

          {/* Required fields */}
          {required.length > 0 && (
            <div className="border border-border rounded p-2 space-y-2">
              <div className="text-destructive text-xs font-medium tracking-wide">
                REQUIRED ({required.length})
              </div>
              {required.map((field) => (
                <div key={field.id} className="flex gap-2 items-center">
                  <label
                    className="text-foreground text-xs w-24 shrink-0 truncate"
                    title={field.name}
                  >
                    {field.name}
                  </label>
                  <DynamicField
                    field={field}
                    value={customFields[field.id]}
                    credentials={credentials}
                    onChange={(v) => updateCustomField(field.id, v)}
                  />
                </div>
              ))}
            </div>
          )}

          {/* Optional fields toggle */}
          {optional.length > 0 && (
            <div>
              <button
                onClick={() => setShowOptional((s) => !s)}
                className="text-muted-foreground text-xs hover:text-foreground transition-colors"
              >
                {showOptional ? "▼" : "▶"} {showOptional ? "Hide" : "Show"} {optional.length}{" "}
                optional field{optional.length !== 1 ? "s" : ""}
              </button>
              {showOptional && (
                <div className="mt-2 border border-border rounded p-2 space-y-2">
                  {optional.map((field) => (
                    <div key={field.id} className="flex gap-2 items-center">
                      <label
                        className="text-muted-foreground text-xs w-24 shrink-0 truncate"
                        title={field.name}
                      >
                        {field.name}
                      </label>
                      <DynamicField
                        field={field}
                        value={customFields[field.id]}
                        credentials={credentials}
                        onChange={(v) => updateCustomField(field.id, v)}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Raw JSON escape hatch */}
          <div>
            <button
              onClick={() => setShowRawJson((s) => !s)}
              className="text-muted-foreground text-xs hover:text-foreground transition-colors font-mono"
            >
              {"{ }"} {showRawJson ? "Hide" : "Show"} raw JSON override
            </button>
            {showRawJson && (
              <div className="mt-1">
                <textarea
                  value={rawJson}
                  onChange={(e) => {
                    setRawJson(e.target.value);
                    setRawJsonError(null);
                    if (e.target.value.trim()) {
                      try {
                        JSON.parse(e.target.value);
                      } catch {
                        setRawJsonError("Invalid JSON");
                      }
                    }
                  }}
                  onBlur={handleRawJsonBlur}
                  placeholder={'{"customfield_10099": "value", "labels": ["tag1"]}'}
                  rows={3}
                  className="w-full bg-background border border-border rounded px-2 py-1 text-foreground text-xs outline-none focus:border-primary font-mono resize-none"
                />
                {rawJsonError && (
                  <p className="text-destructive text-xs mt-0.5">{rawJsonError}</p>
                )}
                <p className="text-muted-foreground text-xs mt-0.5">
                  Merged over typed values on blur. Raw JSON wins on key conflicts.
                </p>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
