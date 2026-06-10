import React, { useEffect, useRef, useState, useMemo } from "react";
import {
  Plus, Trash2, Pencil, Check, X, Server, Search,
  MessageSquare, Orbit, Sparkles, Send, ChevronRight, Zap, Download,
} from "lucide-react";
import { cn } from "../lib/utils";
import { useChatContext } from "../context/ChatContext";
import { useConfirm } from "../context/ConfirmContext";
import { ChatMessage, StepGroup } from "../components/ai/ChatMessage";
import type { ChatMessageData } from "../context/ChatContext";
import { TokenBadge } from "../components/ai/TokenBadge";

/* ── Suggested prompts shown on the empty state ──────────────── */
const SUGGESTED_PROMPTS = [
  {
    icon: "🔍",
    title: "Diagnose failing pods",
    desc: "Check what's crashing and why",
    prompt: "Which pods are failing right now and what is causing them to crash?",
  },
  {
    icon: "📊",
    title: "Cluster health report",
    desc: "Full status of nodes and namespaces",
    prompt: "Give me a complete health report of the cluster — nodes, namespaces, and any warnings.",
  },
  {
    icon: "🔥",
    title: "High resource usage",
    desc: "Pods consuming excess CPU or memory",
    prompt: "Which pods or nodes are consuming the most CPU and memory right now?",
  },
  {
    icon: "⚠️",
    title: "Recent error events",
    desc: "Summarize warnings from the last hour",
    prompt: "Show me all Warning events from the last hour and explain what they mean.",
  },
  {
    icon: "🚀",
    title: "Scale a deployment",
    desc: "Adjust replicas with AI guidance",
    prompt: "Help me scale a deployment — walk me through the safest way to do it.",
  },
  {
    icon: "🔄",
    title: "Rollout status",
    desc: "Check if deployments rolled out cleanly",
    prompt: "Show me the rollout status for all deployments and flag anything that isn't healthy.",
  },
] as const;

/* ── Date grouping helper ────────────────────────────────────── */
function getGroupLabel(iso: string): string {
  const diffDays = Math.floor(
    (Date.now() - new Date(iso).getTime()) / 86_400_000
  );
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays <= 7) return "This week";
  return "Older";
}

const GROUP_ORDER = ["Today", "Yesterday", "This week", "Older"];

export default function AIChats() {
  const {
    conversations,
    activeConversationId,
    messages,
    isStreaming,
    loadConversations,
    startNewChat,
    loadConversation,
    sendMessage,
    deleteConversation,
    renameConversation,
  } = useChatContext();

  const { confirm } = useConfirm();

  const [input, setInput] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [search, setSearch] = useState("");
  const [clusterContext, setClusterContext] = useState<string>(
    () => localStorage.getItem("clusterContext") ?? ""
  );
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === "clusterContext") setClusterContext(e.newValue ?? "");
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  useEffect(() => {
    loadConversations();
    // Resync message thread from DB when navigating back to this page
    // (stream may have completed or errored while on another page)
    if (activeConversationId && !isStreaming) {
      loadConversation(activeConversationId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // intentionally run only on mount — context values are already initialized

  useEffect(() => {
    const deepDive = sessionStorage.getItem("azureResourcesDeepDive");
    if (deepDive) {
      sessionStorage.removeItem("azureResourcesDeepDive");
      setInput(deepDive);
    }
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  /* Auto-resize textarea */
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  };

  const handleSend = async (text?: string) => {
    const msg = (text ?? input).trim();
    if (!msg || isStreaming) return;
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    const convId = activeConversationId ?? (await startNewChat());
    await sendMessage(msg, convId);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleDownload = () => {
    const lines: string[] = [];
    for (const item of renderItems.items) {
      if (item.kind !== "message") continue;
      const { role, content } = item.msg;
      if (!content) continue;
      lines.push(`**${role === "user" ? "You" : "Assistant"}:** ${content}`);
      lines.push("");
    }
    const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const firstUser = messages.find((m) => m.role === "user")?.content ?? "conversation";
    a.download = `${firstUser.slice(0, 40).replace(/[^a-z0-9]/gi, "-")}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleRegenerate = async () => {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUser) return;
    await sendMessage(lastUser.content);
  };

  const startRename = (id: string, title: string) => {
    setEditingId(id);
    setEditTitle(title);
  };

  const commitRename = async () => {
    if (editingId && editTitle.trim()) await renameConversation(editingId, editTitle.trim());
    setEditingId(null);
  };

  /* Filtered + grouped conversations */
  const grouped = useMemo(() => {
    const filtered = conversations.filter((c) =>
      c.title.toLowerCase().includes(search.toLowerCase())
    );
    const buckets: Record<string, typeof conversations> = {};
    for (const conv of filtered) {
      const label = getGroupLabel(conv.updated_at);
      if (!buckets[label]) buckets[label] = [];
      buckets[label].push(conv);
    }
    return GROUP_ORDER.filter((g) => buckets[g]).map((g) => ({ label: g, items: buckets[g] }));
  }, [conversations, search]);

  const activeConv = conversations.find((c) => c.id === activeConversationId);

  const totalTokensAllChats = useMemo(
    () => conversations.reduce((sum, c) => sum + (c.total_tokens ?? 0), 0),
    [conversations]
  );

  function formatTokens(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return String(n);
  }

  /* Render items: group consecutive steps into StepGroup */
  type RenderItem =
    | { kind: "message"; msg: ChatMessageData }
    | { kind: "step_group"; steps: ChatMessageData[]; groupIndex: number };

  const renderItems = useMemo(() => {
    const items: RenderItem[] = [];
    let gi = 0;
    for (let i = 0; i < messages.length; ) {
      if (messages[i].message_type === "step") {
        const steps: ChatMessageData[] = [];
        while (i < messages.length && messages[i].message_type === "step") steps.push(messages[i++]);
        items.push({ kind: "step_group", steps, groupIndex: gi++ });
      } else {
        items.push({ kind: "message", msg: messages[i++] });
      }
    }
    return { items, gi };
  }, [messages]);

  const lastIsSteps = renderItems.items.length > 0 &&
    renderItems.items[renderItems.items.length - 1].kind === "step_group";

  const lastAssistantIdx = renderItems.items.reduce<number>((acc, item, idx) =>
    item.kind === "message" &&
    item.msg.role === "assistant" &&
    item.msg.message_type !== "pending_op" &&
    item.msg.content
      ? idx : acc,
    -1
  );

  return (
    <div className="flex flex-1 min-h-0 overflow-hidden">

      {/* ── Left sidebar — conversation list ───────────────────── */}
      <aside className="w-64 flex-shrink-0 flex flex-col glass-sidebar border-r border-border">

        {/* New chat button */}
        <div className="px-3 pt-3 pb-2 flex-shrink-0">
          <button
            onClick={startNewChat}
            className={cn(
              "w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-medium transition-all",
              "bg-primary text-primary-foreground hover:bg-primary/90",
              "dark:shadow-[0_0_16px_hsl(191_89%_55%_/_0.3)] dark:hover:shadow-[0_0_24px_hsl(191_89%_55%_/_0.45)]"
            )}
          >
            <Plus className="w-4 h-4 flex-shrink-0" />
            <span>New Chat</span>
          </button>
        </div>

        {/* Search */}
        <div className="px-3 pb-2 flex-shrink-0">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search chats..."
              className={cn(
                "w-full pl-8 pr-3 py-2 text-xs rounded-lg transition-colors",
                "bg-secondary/60 border border-border text-foreground placeholder:text-muted-foreground",
                "outline-none focus:border-primary/50 focus:bg-secondary"
              )}
            />
          </div>
        </div>

        {/* Conversation groups */}
        <div className="flex-1 overflow-y-auto px-2 pb-1">
          {conversations.length === 0 && !search && (
            <div className="flex flex-col items-center gap-2 py-8 px-3 text-center">
              <MessageSquare className="w-6 h-6 text-muted-foreground/40" />
              <p className="text-xs text-muted-foreground/60">No conversations yet. Start a new chat above.</p>
            </div>
          )}
          {search && grouped.length === 0 && (
            <p className="text-xs text-muted-foreground/50 px-3 py-4 text-center">No results found.</p>
          )}

          {grouped.map(({ label, items }) => (
            <div key={label} className="mb-3">
              <p className="px-2 py-1 text-[10px] font-mono font-semibold text-muted-foreground/35 tracking-[0.18em] uppercase">
                {label}
              </p>
              {items.map((conv) => {
                const isActive = activeConversationId === conv.id;
                return (
                  <div
                    key={conv.id}
                    onClick={() => loadConversation(conv.id)}
                    className={cn(
                      "group relative flex items-start gap-2 px-2.5 py-2 rounded-lg cursor-pointer transition-all duration-100",
                      isActive
                        ? "bg-primary/10 border border-primary/20 text-foreground dark:shadow-[0_0_12px_hsl(191_89%_55%_/_0.08)]"
                        : "hover:bg-secondary/50 border border-transparent"
                    )}
                  >
                    <MessageSquare className={cn(
                      "w-3.5 h-3.5 mt-0.5 flex-shrink-0",
                      isActive ? "text-primary" : "text-muted-foreground/50"
                    )} />

                    <div className="flex-1 min-w-0">
                      {editingId === conv.id ? (
                        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                          <input
                            autoFocus
                            value={editTitle}
                            onChange={(e) => setEditTitle(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && commitRename()}
                            className="flex-1 text-xs bg-background border border-border rounded px-1.5 py-0.5 outline-none focus:border-primary"
                          />
                          <button onClick={commitRename} className="text-green-400">
                            <Check className="w-3 h-3" />
                          </button>
                          <button onClick={() => setEditingId(null)} className="text-muted-foreground">
                            <X className="w-3 h-3" />
                          </button>
                        </div>
                      ) : (
                        <>
                          <p className={cn(
                            "text-xs truncate leading-snug",
                            isActive ? "font-medium text-foreground" : "text-foreground/80"
                          )}>
                            {conv.title}
                          </p>
                          <p className="text-[10px] text-muted-foreground/50 font-mono mt-0.5">
                            {conv.message_count} msg
                          </p>
                        </>
                      )}
                    </div>

                    {editingId !== conv.id && (
                      <div className="opacity-0 group-hover:opacity-100 flex items-center gap-0.5 flex-shrink-0 transition-opacity">
                        <button
                          onClick={(e) => { e.stopPropagation(); startRename(conv.id, conv.title); }}
                          className="p-1 text-muted-foreground hover:text-foreground rounded"
                        >
                          <Pencil className="w-3 h-3" />
                        </button>
                        <button
                          onClick={async (e) => {
                            e.stopPropagation();
                            const ok = await confirm({
                              title: "Delete Conversation",
                              description: "This conversation and all its messages will be permanently deleted.",
                              variant: "danger",
                              confirmLabel: "Delete",
                            });
                            if (ok) await deleteConversation(conv.id);
                          }}
                          className="p-1 text-muted-foreground hover:text-destructive rounded"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {/* Total token usage footer */}
        {conversations.length > 0 && (
          <div className="flex-shrink-0 px-3 py-2 border-t border-border/50 flex items-center gap-1.5">
            <Zap className="w-3 h-3 text-violet-400/60 flex-shrink-0" />
            <span className="text-[10px] font-mono text-muted-foreground/50">
              {formatTokens(totalTokensAllChats)} tokens · {conversations.length} chats
            </span>
          </div>
        )}
      </aside>

      {/* ── Right panel — chat area ──────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 relative">

        {/* Conversation header (only when active) */}
        {activeConv && (
          <div className={cn(
            "flex-shrink-0 flex items-center justify-between px-6 py-3 border-b border-border",
            "glass-header"
          )}>
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-sm font-medium text-foreground truncate">{activeConv.title}</span>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <TokenBadge />
              {messages.length > 0 && (
                <button
                  onClick={handleDownload}
                  title="Download conversation"
                  className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 border border-border rounded hover:bg-accent text-muted-foreground transition-colors"
                >
                  <Download className="w-3.5 h-3.5" />
                  Download
                </button>
              )}
              {clusterContext ? (
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-primary/30 bg-primary/10 text-primary text-xs font-medium">
                  <Server className="w-3 h-3 flex-shrink-0" />
                  <span className="max-w-[160px] truncate">{clusterContext}</span>
                </div>
              ) : (
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-400 text-xs">
                  <Server className="w-3 h-3 flex-shrink-0" />
                  <span>No cluster</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Thread */}
        <div className="flex-1 overflow-y-auto">
          {/* Empty state */}
          {!activeConversationId && (
            <div className="h-full flex flex-col items-center justify-center px-6 py-12 fade-up">
              {/* Logo */}
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-cyan-400 to-sky-600 flex items-center justify-center mb-5 logo-glow shadow-xl shadow-cyan-500/20">
                <Orbit className="w-8 h-8 text-white" strokeWidth={1.5} />
              </div>
              <h2 className="text-2xl font-semibold text-foreground mb-1 tracking-tight">DokOps AI</h2>
              <p className="text-sm text-muted-foreground mb-8 text-center max-w-xs">
                Your autonomous Kubernetes intelligence. Ask anything about your cluster.
              </p>

              {/* Suggested prompts */}
              <div className="grid grid-cols-2 gap-2.5 w-full max-w-2xl">
                {SUGGESTED_PROMPTS.map((p) => (
                  <button
                    key={p.title}
                    onClick={() => handleSend(p.prompt)}
                    className={cn(
                      "group text-left p-4 rounded-xl border border-border transition-all duration-150",
                      "bg-card/60 hover:bg-card dark:glass",
                      "dark:hover:shadow-[0_0_20px_hsl(191_89%_55%_/_0.1),0_0_0_1px_hsl(191_89%_55%_/_0.12)]",
                      "dark:hover:border-primary/20"
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-base">{p.icon}</span>
                          <span className="text-sm font-medium text-foreground">{p.title}</span>
                        </div>
                        <p className="text-xs text-muted-foreground leading-relaxed">{p.desc}</p>
                      </div>
                      <ChevronRight className="w-3.5 h-3.5 text-muted-foreground/40 group-hover:text-primary/60 transition-colors flex-shrink-0 mt-0.5" />
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Messages */}
          {activeConversationId && (
            <div className="max-w-3xl mx-auto w-full px-4 py-6 flex flex-col gap-5">
              {messages.length === 0 && !isStreaming && (
                <div className="flex flex-col items-center justify-center py-16 gap-3 fade-up">
                  <Sparkles className="w-8 h-8 text-primary/50" />
                  <p className="text-sm text-muted-foreground text-center max-w-xs">
                    Start the conversation — ask me about your cluster, deployments, or recent issues.
                  </p>
                </div>
              )}

              {renderItems.items.map((item, idx) =>
                item.kind === "step_group" ? (
                  <StepGroup
                    key={`sg-${item.groupIndex}`}
                    steps={item.steps}
                    isActive={isStreaming && lastIsSteps && item.groupIndex === renderItems.gi - 1}
                  />
                ) : (
                  <ChatMessage
                    key={item.msg.id}
                    message={item.msg}
                    isLast={idx === lastAssistantIdx}
                    onRegenerate={idx === lastAssistantIdx ? handleRegenerate : undefined}
                  />
                )
              )}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        {/* ── Floating input bar ──────────────────────────────────── */}
        <div className="flex-shrink-0 px-4 py-4">
          <div className="max-w-3xl mx-auto w-full">
            <div className={cn(
              "relative rounded-2xl border border-border transition-all duration-150",
              "glass dark:shadow-[0_2px_20px_hsl(0_0%_0%_/_0.4),0_0_0_1px_hsl(191_89%_55%_/_0.04)]",
              "focus-within:border-primary/40 dark:focus-within:shadow-[0_4px_28px_hsl(0_0%_0%_/_0.5),0_0_0_1px_hsl(191_89%_55%_/_0.12)]"
            )}>
              <textarea
                ref={textareaRef}
                value={input}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                disabled={isStreaming}
                rows={1}
                placeholder={
                  isStreaming
                    ? "AI is responding…"
                    : activeConversationId
                      ? "Continue this conversation…"
                      : "Ask anything about your cluster…"
                }
                className={cn(
                  "w-full bg-transparent px-4 py-3.5 pr-14 text-sm text-foreground",
                  "placeholder:text-muted-foreground/50 resize-none outline-none leading-relaxed",
                  "disabled:cursor-not-allowed disabled:opacity-60",
                  "min-h-[52px] max-h-[160px]"
                )}
                style={{ height: "auto" }}
              />

              {/* Send button */}
              <button
                onClick={() => handleSend()}
                disabled={!input.trim() || isStreaming}
                className={cn(
                  "absolute right-3 bottom-3 w-8 h-8 rounded-xl flex items-center justify-center transition-all duration-150",
                  input.trim() && !isStreaming
                    ? "bg-primary text-primary-foreground dark:shadow-[0_0_12px_hsl(191_89%_55%_/_0.4)] hover:scale-105"
                    : "bg-secondary text-muted-foreground cursor-not-allowed"
                )}
              >
                {isStreaming ? (
                  <span className="w-3.5 h-3.5 rounded-full border-2 border-current/30 border-t-current animate-spin" />
                ) : (
                  <Send className="w-3.5 h-3.5" />
                )}
              </button>
            </div>

            <p className="text-center text-[10px] text-muted-foreground/40 mt-2">
              Enter to send · Shift+Enter for new line
            </p>
          </div>
        </div>

      </div>
    </div>
  );
}
