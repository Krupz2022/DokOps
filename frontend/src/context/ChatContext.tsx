// frontend/src/context/ChatContext.tsx
import React, { createContext, useContext, useState, useCallback, useRef } from "react";
import api from "../lib/api";

export interface ChatMessageData {
  id: string;
  role: "user" | "assistant";
  content: string;
  message_type: "text" | "step" | "model" | "action_card" | "runbook_card" | "pending_op" | "compaction_banner";
  created_at: string;
  is_compacted: boolean;
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  message_count: number;
  preview: string;
  is_compacted: boolean;
  total_tokens: number;
}

export interface TokenUsage {
  input: number;
  output: number;
  total: number;
  conversationTotal: number;
  source: "provider" | "estimate";
}

interface ChatContextValue {
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  messages: ChatMessageData[];
  isStreaming: boolean;
  tokenUsage: TokenUsage | null;
  panelOpen: boolean;
  setPanelOpen: (open: boolean) => void;
  loadConversations: () => Promise<void>;
  startNewChat: () => Promise<string>;
  loadConversation: (id: string) => Promise<void>;
  sendMessage: (content: string, overrideConversationId?: string) => Promise<void>;
  deleteConversation: (id: string) => Promise<void>;
  renameConversation: (id: string, title: string) => Promise<void>;
}

const ChatContext = createContext<ChatContextValue | undefined>(undefined);

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessageData[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [tokenUsage, setTokenUsage] = useState<TokenUsage | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const loadConversations = useCallback(async () => {
    const resp = await api.get("/chat/conversations");
    setConversations(resp.data);
  }, []);

  const startNewChat = useCallback(async (): Promise<string> => {
    const resp = await api.post("/chat/conversations");
    const conv = resp.data;
    setActiveConversationId(conv.id);
    setMessages([]);
    setTokenUsage(null);
    await loadConversations();
    return conv.id;
  }, [loadConversations]);

  const loadConversation = useCallback(async (id: string) => {
    const resp = await api.get(`/chat/conversations/${id}`);
    setActiveConversationId(id);
    setMessages(resp.data.messages);
    setTokenUsage(
      typeof resp.data.total_tokens === "number"
        ? { input: 0, output: 0, total: 0, conversationTotal: resp.data.total_tokens, source: "estimate" }
        : null
    );
  }, []);

  const sendMessage = useCallback(async (content: string, overrideConversationId?: string) => {
    const convId = overrideConversationId ?? activeConversationId;
    if (!convId || isStreaming) return;

    // Optimistically add user message to UI
    const userMsg: ChatMessageData = {
      id: `tmp-${Date.now()}`,
      role: "user",
      content,
      message_type: "text",
      created_at: new Date().toISOString(),
      is_compacted: false,
    };
    const streamingMsgId = `stream-${Date.now()}`;

    setMessages((prev) => [
      ...prev,
      userMsg,
      {
        id: streamingMsgId,
        role: "assistant",
        content: "",
        message_type: "text",
        created_at: new Date().toISOString(),
        is_compacted: false,
      },
    ]);
    setIsStreaming(true);

    const token = localStorage.getItem("access_token");
    const clusterContext = localStorage.getItem("clusterContext");

    abortRef.current = new AbortController();

    try {
      const res = await fetch(
        `${import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1"}/chat/conversations/${convId}/message`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
            ...(clusterContext ? { "X-Cluster-Context": clusterContext } : {}),
          },
          body: JSON.stringify({ content }),
          signal: abortRef.current.signal,
        }
      );

      if (!res.body) return;

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const event = JSON.parse(line.substring(6));

          if (event.type === "model") {
            setMessages((prev) => [
              ...prev.filter((m) => m.id !== streamingMsgId),
              {
                id: `model-${Date.now()}`,
                role: "assistant",
                content: event.message,
                message_type: "model",
                created_at: new Date().toISOString(),
                is_compacted: false,
              },
              {
                id: streamingMsgId,
                role: "assistant",
                content: "",
                message_type: "text",
                created_at: new Date().toISOString(),
                is_compacted: false,
              },
            ]);
          } else if (event.type === "step") {
            // Append step as a separate message
            setMessages((prev) => [
              ...prev.filter((m) => m.id !== streamingMsgId),
              {
                id: `step-${Date.now()}-${Math.random()}`,
                role: "assistant",
                content: event.message,
                message_type: "step",
                created_at: new Date().toISOString(),
                is_compacted: false,
              },
              {
                id: streamingMsgId,
                role: "assistant",
                content: "",
                message_type: "text",
                created_at: new Date().toISOString(),
                is_compacted: false,
              },
            ]);
          } else if (event.type === "result") {
            // Replace placeholder with final content
            const resultContent = event.message?.trim() || "(No response — the AI model returned an empty reply)";
            setMessages((prev) =>
              prev.map((m) =>
                m.id === streamingMsgId
                  ? { ...m, content: resultContent, message_type: "text" }
                  : m
              )
            );
          } else if (event.type === "pending_operation") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === streamingMsgId
                  ? { ...m, content: JSON.stringify(event.operation), message_type: "pending_op" }
                  : m
              )
            );
          } else if (event.type === "compaction_banner") {
            setMessages((prev) => [
              ...prev.filter((m) => m.id !== streamingMsgId),
              {
                id: `compaction-${Date.now()}`,
                role: "assistant",
                content: event.message,
                message_type: "compaction_banner",
                created_at: new Date().toISOString(),
                is_compacted: false,
              },
              {
                id: streamingMsgId,
                role: "assistant",
                content: "",
                message_type: "text",
                created_at: new Date().toISOString(),
                is_compacted: false,
              },
            ]);
          } else if (event.type === "token_usage") {
            setTokenUsage({
              input: event.input_tokens ?? 0,
              output: event.output_tokens ?? 0,
              total: event.total_tokens ?? 0,
              conversationTotal: event.conversation_total ?? 0,
              source: event.source === "provider" ? "provider" : "estimate",
            });
          }
        }
      }

      // Flush any remaining buffered event (e.g. token_usage arriving with stream close)
      const remaining = buffer.trim();
      if (remaining.startsWith("data: ")) {
        try {
          const event = JSON.parse(remaining.substring(6));
          if (event.type === "token_usage") {
            setTokenUsage({
              input: event.input_tokens ?? 0,
              output: event.output_tokens ?? 0,
              total: event.total_tokens ?? 0,
              conversationTotal: event.conversation_total ?? 0,
              source: event.source === "provider" ? "provider" : "estimate",
            });
          }
        } catch { /* ignore malformed trailing data */ }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        setMessages((prev) => [
          ...prev,
          {
            id: `err-${Date.now()}`,
            role: "assistant",
            content: "Connection error. Please try again.",
            message_type: "text",
            created_at: new Date().toISOString(),
            is_compacted: false,
          },
        ]);
      }
    } finally {
      setIsStreaming(false);
      await loadConversations();
    }
  }, [activeConversationId, isStreaming, loadConversations]);

  const deleteConversation = useCallback(async (id: string) => {
    await api.delete(`/chat/conversations/${id}`);
    if (activeConversationId === id) {
      setActiveConversationId(null);
      setMessages([]);
      setTokenUsage(null);
    }
    await loadConversations();
  }, [activeConversationId, loadConversations]);

  const renameConversation = useCallback(async (id: string, title: string) => {
    await api.patch(`/chat/conversations/${id}`, { title });
    await loadConversations();
  }, [loadConversations]);

  return (
    <ChatContext.Provider value={{
      conversations,
      activeConversationId,
      messages,
      isStreaming,
      tokenUsage,
      panelOpen,
      setPanelOpen,
      loadConversations,
      startNewChat,
      loadConversation,
      sendMessage,
      deleteConversation,
      renameConversation,
    }}>
      {children}
    </ChatContext.Provider>
  );
}

export function useChatContext() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChatContext must be used within ChatProvider");
  return ctx;
}
