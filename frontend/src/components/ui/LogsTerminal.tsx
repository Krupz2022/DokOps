import React, { useRef, useState, useEffect, useCallback } from "react";
import ReactDOM from "react-dom";
import { Copy, Download, WrapText, Search, X, ArrowDown, Check } from "lucide-react";
import { cn } from "../../lib/utils";

interface LogsTerminalProps {
  isOpen: boolean;
  onClose: () => void;
  podName: string;
  namespace?: string;
  logs: string;
}

type LogLevel = "error" | "warn" | "info" | "debug" | "plain";

function detectLevel(line: string): LogLevel {
  const u = line.toUpperCase();
  if (/\b(ERROR|FATAL|PANIC|CRITICAL|EXCEPTION)\b/.test(u)) return "error";
  if (/\b(WARN|WARNING)\b/.test(u)) return "warn";
  if (/\b(INFO)\b/.test(u)) return "info";
  if (/\b(DEBUG|TRACE)\b/.test(u)) return "debug";
  return "plain";
}

const LEVEL_LINE: Record<LogLevel, string> = {
  error:  "text-red-400",
  warn:   "text-amber-300",
  info:   "text-slate-200",
  debug:  "text-slate-500",
  plain:  "text-slate-300",
};

const LEVEL_BADGE: Record<LogLevel, { label: string; cls: string } | null> = {
  error:  { label: "ERR", cls: "bg-red-500/15 text-red-400 border-red-500/20" },
  warn:   { label: "WRN", cls: "bg-amber-500/15 text-amber-400 border-amber-500/20" },
  info:   { label: "INF", cls: "bg-sky-500/10 text-sky-400 border-sky-500/20" },
  debug:  { label: "DBG", cls: "bg-slate-700/50 text-slate-500 border-slate-600/30" },
  plain:  null,
};

function highlightMatch(text: string, query: string): React.ReactElement {
  if (!query) return <>{text}</>;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-yellow-400/30 text-yellow-200 rounded-sm">{text.slice(idx, idx + query.length)}</mark>
      {text.slice(idx + query.length)}
    </>
  );
}

export function LogsTerminal({ isOpen, onClose, podName, namespace, logs }: LogsTerminalProps) {
  const [filter, setFilter] = useState("");
  const [wrapLines, setWrapLines] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [copied, setCopied] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const lines = logs.split("\n");

  const filteredLines = filter
    ? lines.map((l, i) => ({ line: l, originalIndex: i + 1 })).filter(({ line }) =>
        line.toLowerCase().includes(filter.toLowerCase())
      )
    : lines.map((l, i) => ({ line: l, originalIndex: i + 1 }));

  const errorCount  = lines.filter(l => detectLevel(l) === "error").length;
  const warnCount   = lines.filter(l => detectLevel(l) === "warn").length;

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const copyLogs = async () => {
    await navigator.clipboard.writeText(logs);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const downloadLogs = () => {
    const blob = new Blob([logs], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${podName}.log`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const toggleSearch = useCallback(() => {
    setShowSearch(s => {
      if (!s) setTimeout(() => searchRef.current?.focus(), 50);
      return !s;
    });
    if (showSearch) setFilter("");
  }, [showSearch]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "f") { e.preventDefault(); toggleSearch(); }
      if (e.key === "Escape") { if (showSearch) { setShowSearch(false); setFilter(""); } else onClose(); }
    };
    if (isOpen) window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [isOpen, showSearch, toggleSearch, onClose]);

  if (!isOpen) return null;

  const lineDigits = String(lines.length).length;

  return ReactDOM.createPortal(
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-5xl max-h-[88vh] flex flex-col rounded-lg overflow-hidden shadow-2xl shadow-black/60"
        style={{ background: "#07090F", border: "1px solid #1a2030" }}
        onClick={e => e.stopPropagation()}
      >

        {/* ── Terminal title bar ─────────────────────────────────────── */}
        <div
          className="flex items-center justify-between px-4 py-2.5 border-b flex-shrink-0"
          style={{ background: "#0D1117", borderColor: "#1a2030" }}
        >
          {/* macOS traffic lights */}
          <div className="flex items-center gap-1.5">
            <button
              onClick={onClose}
              className="w-3 h-3 rounded-full bg-red-500 hover:bg-red-400 transition-colors flex items-center justify-center group"
              title="Close"
            >
              <X className="w-1.5 h-1.5 text-red-900 opacity-0 group-hover:opacity-100" />
            </button>
            <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
            <div className="w-3 h-3 rounded-full bg-green-500/80" />
          </div>

          {/* Title */}
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-mono text-slate-400">
              {namespace && <span className="text-slate-600">{namespace} / </span>}
              <span className="text-slate-200">{podName}</span>
              <span className="text-slate-600"> — logs</span>
            </span>
          </div>

          {/* Toolbar */}
          <div className="flex items-center gap-1">
            {errorCount > 0 && (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-red-500/15 text-red-400 border border-red-500/20">
                {errorCount} ERR
              </span>
            )}
            {warnCount > 0 && (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/20 ml-1">
                {warnCount} WRN
              </span>
            )}
            <div className="w-px h-4 bg-slate-700 mx-1" />
            <ToolButton onClick={toggleSearch} active={showSearch} title="Search (Ctrl+F)">
              <Search className="w-3.5 h-3.5" />
            </ToolButton>
            <ToolButton onClick={() => setWrapLines(w => !w)} active={wrapLines} title="Wrap lines">
              <WrapText className="w-3.5 h-3.5" />
            </ToolButton>
            <ToolButton onClick={scrollToBottom} title="Scroll to bottom">
              <ArrowDown className="w-3.5 h-3.5" />
            </ToolButton>
            <div className="w-px h-4 bg-slate-700 mx-1" />
            <ToolButton onClick={copyLogs} title="Copy all">
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            </ToolButton>
            <ToolButton onClick={downloadLogs} title="Download">
              <Download className="w-3.5 h-3.5" />
            </ToolButton>
          </div>
        </div>

        {/* ── Search bar ─────────────────────────────────────────────── */}
        {showSearch && (
          <div
            className="flex items-center gap-2 px-4 py-2 border-b flex-shrink-0"
            style={{ background: "#0A0E14", borderColor: "#1a2030" }}
          >
            <Search className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" />
            <input
              ref={searchRef}
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="Filter logs…"
              className="flex-1 bg-transparent text-sm text-slate-200 placeholder:text-slate-600 outline-none font-mono"
            />
            {filter && (
              <span className="text-[10px] font-mono text-slate-500">
                {filteredLines.length} / {lines.length}
              </span>
            )}
            <button
              onClick={() => { setFilter(""); setShowSearch(false); }}
              className="text-slate-600 hover:text-slate-400"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* ── Log content ────────────────────────────────────────────── */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto overflow-x-auto"
          style={{ background: "#07090F" }}
        >
          {filteredLines.length === 0 ? (
            <div className="flex items-center justify-center h-32 text-slate-600 text-sm font-mono">
              {filter ? `no matches for "${filter}"` : "no logs available"}
            </div>
          ) : (
            <table className="w-full border-collapse">
              <tbody>
                {filteredLines.map(({ line, originalIndex }) => {
                  const level = detectLevel(line);
                  const badge = LEVEL_BADGE[level];
                  const lineColor = LEVEL_LINE[level];
                  const isError = level === "error";

                  return (
                    <tr
                      key={originalIndex}
                      className={cn(
                        "group hover:bg-white/[0.025] transition-colors",
                        isError && "bg-red-500/[0.04]"
                      )}
                    >
                      {/* Line number */}
                      <td
                        className="select-none text-right px-3 py-0.5 align-top text-[11px] font-mono text-slate-700 border-r"
                        style={{ width: `${lineDigits + 3}ch`, borderColor: "#1a2030", userSelect: "none" }}
                      >
                        {String(originalIndex).padStart(lineDigits, " ")}
                      </td>

                      {/* Level badge */}
                      <td className="px-2 py-0.5 align-top" style={{ width: "3.5rem" }}>
                        {badge && (
                          <span className={cn(
                            "text-[9px] font-mono font-semibold px-1 py-px rounded border tracking-wider",
                            badge.cls
                          )}>
                            {badge.label}
                          </span>
                        )}
                      </td>

                      {/* Log content */}
                      <td
                        className={cn(
                          "py-0.5 pr-4 pl-1 text-[12px] font-mono leading-5 align-top",
                          lineColor,
                          !wrapLines && "whitespace-nowrap"
                        )}
                      >
                        {highlightMatch(line, filter)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <div ref={bottomRef} />
        </div>

        {/* ── Status bar ─────────────────────────────────────────────── */}
        <div
          className="flex items-center justify-between px-4 py-1.5 border-t flex-shrink-0"
          style={{ background: "#0A0E14", borderColor: "#1a2030" }}
        >
          <div className="flex items-center gap-3 text-[10px] font-mono">
            <span className="text-slate-600">{lines.length} lines</span>
            {filter && (
              <span className="text-sky-500">{filteredLines.length} matching</span>
            )}
            {errorCount > 0 && (
              <span className="text-red-500">{errorCount} errors</span>
            )}
            {warnCount > 0 && (
              <span className="text-amber-500">{warnCount} warnings</span>
            )}
          </div>
          <span className="text-[10px] font-mono text-slate-700">
            {wrapLines ? "wrap on" : "wrap off"} · esc to close
          </span>
        </div>
      </div>
    </div>,
    document.body
  );
}

function ToolButton({
  children, onClick, active, title,
}: {
  children: React.ReactNode;
  onClick: () => void;
  active?: boolean;
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={cn(
        "w-6 h-6 flex items-center justify-center rounded transition-colors",
        active
          ? "bg-sky-500/20 text-sky-400"
          : "text-slate-500 hover:text-slate-200 hover:bg-white/5"
      )}
    >
      {children}
    </button>
  );
}
