// frontend/src/components/ai/ChatPanel.tsx
import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X, History, Plus, Send, Download } from "lucide-react";
import { useChatContext } from "../../context/ChatContext";
import { ChatMessage, StepGroup } from "./ChatMessage";
import type { ChatMessageData } from "../../context/ChatContext";
import { ConversationList } from "./ConversationList";
import { TokenBadge } from "./TokenBadge";

export function ChatPanel() {
  const {
    panelOpen,
    setPanelOpen,
    messages,
    isStreaming,
    activeConversationId,
    sendMessage,
    loadConversations,
    loadConversation,
    startNewChat,
  } = useChatContext();

  const [input, setInput] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const handleDownload = () => {
    const lines: string[] = [];
    for (const msg of messages) {
      if (msg.message_type === "step" || msg.message_type === "model" || msg.message_type === "compaction_banner") continue;
      if (!msg.content.trim()) continue;
      lines.push(msg.role === "user" ? `**You:** ${msg.content}` : `**Assistant:** ${msg.content}`);
      lines.push("");
    }
    const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const title = messages.find((m) => m.role === "user")?.content?.slice(0, 40).replace(/[^\w\s-]/g, "").trim() ?? "chat";
    a.download = `${title}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleRegenerate = async () => {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUser || isStreaming) return;
    await sendMessage(lastUser.content);
  };

  useEffect(() => {
    if (panelOpen) {
      loadConversations();
    }
  }, [panelOpen, loadConversations]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    // startNewChat() returns the new ID synchronously before state re-renders,
    // so we pass it as override to avoid stale closure in sendMessage.
    const convId = activeConversationId ?? (await startNewChat());
    await sendMessage(text, convId);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSelectConversation = async (id: string) => {
    await loadConversation(id);
    setShowHistory(false);
  };

  if (!panelOpen) return null;

  const activeTitle = messages.length === 0 ? "New Chat" : undefined;

  // Group consecutive step messages into StepGroup blocks
  type RenderItem =
    | { kind: "message"; msg: ChatMessageData }
    | { kind: "step_group"; steps: ChatMessageData[]; groupIndex: number };

  const renderItems: RenderItem[] = [];
  let groupIndex = 0;
  for (let i = 0; i < messages.length; ) {
    if (messages[i].message_type === "step") {
      const steps: ChatMessageData[] = [];
      while (i < messages.length && messages[i].message_type === "step") {
        steps.push(messages[i]);
        i++;
      }
      renderItems.push({ kind: "step_group", steps, groupIndex: groupIndex++ });
    } else {
      renderItems.push({ kind: "message", msg: messages[i] });
      i++;
    }
  }
  const lastItemIsSteps =
    renderItems.length > 0 && renderItems[renderItems.length - 1].kind === "step_group";

  const lastAssistantIdx = renderItems.reduce<number>((acc, item, idx) =>
    item.kind === "message" && item.msg.role === "assistant" && item.msg.message_type === "text" && item.msg.content
      ? idx
      : acc,
    -1
  );

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="relative bg-background border border-border rounded-xl shadow-2xl w-full max-w-4xl h-[90vh] flex flex-col overflow-hidden">
        {/* Conversation list slide-in */}
        {showHistory && (
          <ConversationList
            onClose={() => setShowHistory(false)}
            onSelect={handleSelectConversation}
          />
        )}

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/30 flex-shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-sm font-semibold text-foreground">🤖 AI Assistant</span>
            {activeTitle && (
              <span className="text-xs text-muted-foreground">{activeTitle}</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <TokenBadge />
            {messages.length > 0 && (
              <button
                onClick={handleDownload}
                title="Download conversation"
                className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 border border-border rounded hover:bg-accent text-muted-foreground"
              >
                <Download className="w-3.5 h-3.5" />
                Download
              </button>
            )}
            <button
              onClick={() => setShowHistory((v) => !v)}
              className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 border border-border rounded hover:bg-accent text-muted-foreground"
            >
              <History className="w-3.5 h-3.5" />
              History
            </button>
            <button
              onClick={async () => { await startNewChat(); setShowHistory(false); }}
              className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 border border-border rounded hover:bg-accent text-muted-foreground"
            >
              <Plus className="w-3.5 h-3.5" />
              New Chat
            </button>
            <button
              onClick={() => setPanelOpen(false)}
              className="text-muted-foreground hover:text-foreground p-1"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Message thread */}
        <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-3">
          {messages.length === 0 && (
            <div className="flex-1 flex flex-col items-center justify-center text-center gap-3 py-12">
              <span className="text-4xl">🤖</span>
              <p className="text-muted-foreground text-sm max-w-xs">
                Ask me anything about your cluster — I can diagnose issues, check logs, and propose fixes.
              </p>
            </div>
          )}
          {renderItems.map((item, idx) =>
            item.kind === "step_group" ? (
              <StepGroup
                key={`sg-${item.groupIndex}`}
                steps={item.steps}
                isActive={isStreaming && lastItemIsSteps && item.groupIndex === groupIndex - 1}
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

        {/* Input bar */}
        <div className="flex-shrink-0 border-t border-border px-4 py-3 bg-muted/20">
          <div className="flex flex-col gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isStreaming}
              rows={2}
              placeholder="Ask a follow-up or give a new command..."
              className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground resize-none outline-none focus:border-primary disabled:opacity-50"
            />
            <div className="flex justify-between items-center">
              <span className="text-[10px] text-muted-foreground">Enter to send · Shift+Enter for new line</span>
              <button
                onClick={handleSend}
                disabled={!input.trim() || isStreaming}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Send className="w-3 h-3" />
                {isStreaming ? "Thinking..." : "Send"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
