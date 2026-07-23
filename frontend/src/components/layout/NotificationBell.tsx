import { useEffect, useState, useCallback, type ReactNode } from "react";
import { Bell, CheckCircle2, XCircle, Loader2, Clock } from "lucide-react";
import { listNotifications, markNotificationRead, type AppNotification } from "../../lib/api";
import { useChatContext } from "../../context/ChatContext";

const STATUS_ICON: Record<AppNotification["status"], ReactNode> = {
  succeeded: <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />,
  failed: <XCircle className="w-4 h-4 text-red-500 shrink-0" />,
  watching: <Loader2 className="w-4 h-4 text-sky-500 shrink-0 animate-spin" />,
  timed_out: <Clock className="w-4 h-4 text-amber-500 shrink-0" />,
};

const POLL_INTERVAL_MS = 10000;

export default function NotificationBell() {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const { setPanelOpen, loadConversation } = useChatContext();

  const refresh = useCallback(async () => {
    try {
      setItems(await listNotifications());
    } catch {
      // Notifications outage must not break the app shell — keep last known state.
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, POLL_INTERVAL_MS);
    window.addEventListener("focus", refresh);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", refresh);
    };
  }, [refresh]);

  const unreadCount = items.filter((n) => !n.read).length;

  const handleSelect = async (notification: AppNotification) => {
    setIsOpen(false);
    setPanelOpen(true);
    if (!notification.read) {
      try {
        await markNotificationRead(notification.id);
      } catch {
        // Non-fatal — the chat panel still opens even if marking read fails.
      }
    }
    await loadConversation(notification.conversation_id);
    refresh();
  };

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen((o) => !o)}
        className="relative h-8 w-8 flex items-center justify-center rounded-lg border border-border bg-card text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
        aria-label="Notifications"
      >
        <Bell className="w-4 h-4" />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 flex items-center justify-center rounded-full bg-red-500 text-white text-[10px] font-semibold leading-none">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-[59]" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 top-full mt-2 w-80 max-h-96 overflow-y-auto bg-card border rounded-lg shadow-xl z-[60] animate-in fade-in zoom-in-95 duration-200">
            <div className="px-3 py-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider border-b">
              Notifications
            </div>
            {items.length === 0 ? (
              <p className="px-3 py-6 text-sm text-muted-foreground text-center">No notifications</p>
            ) : (
              items.map((notification) => (
                <button
                  key={notification.id}
                  onClick={() => handleSelect(notification)}
                  className={`w-full text-left px-3 py-2.5 flex gap-2 items-start hover:bg-secondary transition-colors border-b last:border-b-0 ${
                    notification.read ? "opacity-60" : ""
                  }`}
                >
                  {STATUS_ICON[notification.status]}
                  <span className="text-sm text-foreground/90">{notification.message}</span>
                  {!notification.read && (
                    <span className="w-2 h-2 rounded-full bg-primary shrink-0 mt-1 ml-auto" />
                  )}
                </button>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}
