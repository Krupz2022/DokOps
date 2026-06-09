// frontend/src/components/ai/ConversationList.tsx
import React from "react";
import { MessageSquare, Trash2, X } from "lucide-react";
import { cn } from "../../lib/utils";
import { useChatContext } from "../../context/ChatContext";
import { useConfirm } from "../../context/ConfirmContext";

interface ConversationListProps {
  onClose: () => void;
  onSelect: (id: string) => void;
}

export function ConversationList({ onClose, onSelect }: ConversationListProps) {
  const { conversations, activeConversationId, deleteConversation, startNewChat } = useChatContext();
  const { confirm } = useConfirm();

  const handleNew = async () => {
    await startNewChat();
    onClose();
  };

  const handleSelect = async (id: string) => {
    onSelect(id);
    onClose();
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    const ok = await confirm({
      title: "Delete Conversation",
      description: "This conversation and all its messages will be permanently deleted.",
      variant: "danger",
      confirmLabel: "Delete",
    });
    if (ok) {
      await deleteConversation(id);
    }
  };

  const formatDate = (iso: string) => {
    const d = new Date(iso);
    const now = new Date();
    const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000);
    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  };

  return (
    <div className="flex flex-col h-full bg-background border-r border-border w-64 absolute left-0 top-0 bottom-0 z-10 shadow-xl">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <span className="text-sm font-semibold text-foreground">Conversations</span>
        <div className="flex items-center gap-2">
          <button
            onClick={handleNew}
            className="text-xs px-2 py-1 bg-primary text-primary-foreground rounded hover:bg-primary/90"
          >
            + New
          </button>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-2">
        {conversations.length === 0 && (
          <p className="text-xs text-muted-foreground px-4 py-3">No conversations yet.</p>
        )}
        {conversations.map((conv) => (
          <button
            key={conv.id}
            onClick={() => handleSelect(conv.id)}
            className={cn(
              "w-full flex items-start gap-2 px-3 py-2.5 hover:bg-accent group text-left",
              activeConversationId === conv.id && "bg-accent border-l-2 border-primary"
            )}
          >
            <MessageSquare className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-muted-foreground" />
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-foreground truncate">{conv.title}</p>
              <p className="text-[10px] text-muted-foreground">
                {formatDate(conv.updated_at)} · {conv.message_count} msg
              </p>
            </div>
            <button
              onClick={(e) => handleDelete(e, conv.id)}
              className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive flex-shrink-0"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </button>
        ))}
      </div>
    </div>
  );
}
