import { useState } from "react";

interface Props {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  allowedValues?: string[];
  required?: boolean;
}

export function TagChipInput({ values, onChange, placeholder, allowedValues, required }: Props) {
  const [input, setInput] = useState("");

  const addChip = (val: string) => {
    const trimmed = val.trim();
    if (!trimmed || values.includes(trimmed)) return;
    if (allowedValues && allowedValues.length > 0 && !allowedValues.includes(trimmed)) return;
    onChange([...values, trimmed]);
    setInput("");
  };

  const removeChip = (val: string) => onChange(values.filter((v) => v !== val));

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addChip(input);
    } else if (e.key === "Backspace" && input === "" && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  };

  const borderClass = required && values.length === 0
    ? "border-destructive focus-within:border-destructive"
    : "border-border focus-within:border-primary";

  return (
    <div
      className={`flex flex-wrap gap-1 min-h-[28px] bg-background border rounded px-2 py-1 ${borderClass}`}
    >
      {values.map((v) => (
        <span
          key={v}
          className="inline-flex items-center gap-1 bg-primary/10 text-primary border border-primary/20 rounded-full text-xs px-2 py-0.5"
        >
          {v}
          <button
            type="button"
            onClick={() => removeChip(v)}
            className="hover:text-destructive leading-none"
          >
            ×
          </button>
        </span>
      ))}
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKey}
        onBlur={() => addChip(input)}
        placeholder={values.length === 0 ? (placeholder ?? "Type and press Enter") : ""}
        className="flex-1 min-w-[80px] bg-transparent text-foreground text-xs outline-none"
      />
    </div>
  );
}
