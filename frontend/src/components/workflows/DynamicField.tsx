import { useState, useEffect, useRef } from "react";
import type { JiraFieldSchema, JiraUser, JiraCredentials } from "../../types/workflow";
import { TagChipInput } from "./TagChipInput";
import { jiraApi } from "../../lib/api";

interface Props {
  field: JiraFieldSchema;
  value: unknown;
  credentials: JiraCredentials;
  onChange: (value: unknown) => void;
}

const baseInput =
  "flex-1 bg-background border rounded px-2 py-1 text-foreground text-xs outline-none w-full";

function borderClass(required: boolean) {
  return required
    ? "border-destructive focus:border-destructive"
    : "border-border focus:border-primary";
}

export function DynamicField({ field, value, credentials, onChange }: Props) {
  const cls = `${baseInput} ${borderClass(field.required)}`;

  if (field.type === "number") {
    return (
      <input
        type="number"
        value={value != null ? String(value) : ""}
        onChange={(e) => onChange(e.target.valueAsNumber)}
        className={cls}
      />
    );
  }

  if (field.type === "date") {
    return (
      <input
        type="date"
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.target.value)}
        className={cls}
      />
    );
  }

  if (field.type === "option") {
    const current =
      value && typeof value === "object" && "name" in (value as object)
        ? String((value as { name: string }).name)
        : "";
    return (
      <select
        value={current}
        onChange={(e) => onChange(e.target.value ? { name: e.target.value } : null)}
        className={cls}
      >
        <option value="">— select —</option>
        {(field.allowed_values ?? []).map((av) => (
          <option key={av} value={av}>
            {av}
          </option>
        ))}
      </select>
    );
  }

  if (field.type === "array") {
    const arr = Array.isArray(value) ? (value as string[]) : [];
    return (
      <div className="flex-1">
        <TagChipInput
          values={arr}
          onChange={(v) => onChange(v)}
          allowedValues={field.allowed_values ?? undefined}
          placeholder={`Add ${field.name.toLowerCase()}…`}
          required={field.required}
        />
      </div>
    );
  }

  if (field.type === "user") {
    return (
      <UserPickerField
        value={value}
        credentials={credentials}
        onChange={onChange}
        required={field.required}
      />
    );
  }

  // string fallback
  return (
    <input
      type="text"
      value={typeof value === "string" ? value : ""}
      onChange={(e) => onChange(e.target.value)}
      placeholder="{{steps.name}} or plain value"
      className={cls}
    />
  );
}

// ---------------------------------------------------------------------------
// User picker sub-component (internal — not exported)
// ---------------------------------------------------------------------------

function UserPickerField({
  value,
  credentials,
  onChange,
  required,
}: {
  value: unknown;
  credentials: Props["credentials"];
  onChange: (v: unknown) => void;
  required: boolean;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<JiraUser[]>([]);
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const resolvedName =
    value && typeof value === "object" && "display_name" in (value as object)
      ? String((value as { display_name: string }).display_name)
      : "";

  useEffect(() => {
    if (query.length < 2) {
      setResults([]);
      return;
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try {
        const { data } = await jiraApi.searchUsers({ ...credentials, query });
        setResults(data);
        setOpen(true);
      } catch {
        setResults([]);
      }
    }, 300);
  }, [query, credentials.base_url, credentials.email, credentials.api_token]);

  const select = (user: JiraUser) => {
    onChange({ id: user.account_id, display_name: user.display_name });
    setQuery(user.display_name);
    setOpen(false);
  };

  const cls = `${baseInput} ${borderClass(required && !resolvedName)}`;

  return (
    <div className="flex-1 relative">
      <input
        type="text"
        value={resolvedName || query}
        onChange={(e) => {
          setQuery(e.target.value);
          onChange(null);
        }}
        onFocus={() => query.length >= 2 && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Search user by name…"
        className={cls}
      />
      {open && results.length > 0 && (
        <div className="absolute z-50 top-full left-0 right-0 mt-0.5 bg-card border border-border rounded shadow-lg max-h-40 overflow-y-auto">
          {results.map((u) => (
            <button
              key={u.account_id}
              onMouseDown={() => select(u)}
              className="w-full text-left px-2 py-1.5 text-xs text-foreground hover:bg-primary/10 flex flex-col gap-0.5"
            >
              <span className="font-medium">{u.display_name}</span>
              <span className="text-muted-foreground">{u.email}</span>
            </button>
          ))}
        </div>
      )}
      {open && results.length === 0 && query.length >= 2 && (
        <div className="absolute z-50 top-full left-0 right-0 mt-0.5 bg-card border border-border rounded px-2 py-1.5 text-xs text-muted-foreground">
          No users found
        </div>
      )}
    </div>
  );
}
