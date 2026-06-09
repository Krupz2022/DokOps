// frontend/src/components/ai/TokenBadge.tsx
import { useEffect, useRef, useState } from "react";
import { Zap } from "lucide-react";
import { useChatContext } from "../../context/ChatContext";

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export function TokenBadge() {
  const { tokenUsage } = useChatContext();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  if (!tokenUsage) return null;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-violet-500/30 bg-violet-500/10 text-violet-400 text-xs font-medium hover:bg-violet-500/20 transition-colors"
        title="Token usage"
      >
        <Zap className="w-3 h-3 flex-shrink-0" />
        <span>{formatTokens(tokenUsage.conversationTotal)} tokens</span>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 z-50 w-52 rounded-lg border border-border bg-background shadow-lg p-3 text-xs">
          <p className="font-semibold text-foreground mb-2">Token Usage</p>
          <div className="flex flex-col gap-1.5 text-muted-foreground">
            <div className="flex justify-between">
              <span>Input (this msg)</span>
              <span className="text-foreground">{tokenUsage.input.toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span>Output (this msg)</span>
              <span className="text-foreground">{tokenUsage.output.toLocaleString()}</span>
            </div>
            <div className="flex justify-between border-t border-border pt-1.5 mt-0.5 font-medium">
              <span className="text-foreground">Conversation total</span>
              <span className="text-foreground">{tokenUsage.conversationTotal.toLocaleString()}</span>
            </div>
          </div>
          <div className="mt-2.5 flex items-center gap-1.5">
            <span
              className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                tokenUsage.source === "provider" ? "bg-green-500" : "bg-amber-500"
              }`}
            />
            <span className="text-muted-foreground">
              {tokenUsage.source === "provider" ? "Provider data" : "~Estimated"}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
