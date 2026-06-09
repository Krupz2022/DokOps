import { useEffect, useState } from "react";
import { CheckCircle, XCircle, AlertTriangle, Info, X } from "lucide-react";
import { cn } from "../../lib/utils";

export type ToastType = "success" | "error" | "warning" | "info";

export interface ToastProps {
  message: string;
  type: ToastType;
  onClose: () => void;
  duration?: number;
}

const TOAST_STYLES: Record<ToastType, { border: string; icon: React.ElementType; iconClass: string }> = {
  success: { border: "border-l-green-500",  icon: CheckCircle,    iconClass: "text-green-500" },
  error:   { border: "border-l-red-500",    icon: XCircle,        iconClass: "text-red-500" },
  warning: { border: "border-l-amber-500",  icon: AlertTriangle,  iconClass: "text-amber-500" },
  info:    { border: "border-l-blue-500",   icon: Info,           iconClass: "text-blue-500" },
};

export function Toast({ message, type, onClose, duration = 4000 }: ToastProps) {
  const [visible, setVisible] = useState(false);
  const { border, icon: Icon, iconClass } = TOAST_STYLES[type];

  useEffect(() => {
    setVisible(true);
    if (duration === 0) return; // pinned — user must close manually
    const t = setTimeout(() => { setVisible(false); setTimeout(onClose, 300); }, duration);
    return () => clearTimeout(t);
  }, [duration, onClose]);

  return (
    <div
      className={cn(
        "flex items-start gap-3 bg-white dark:bg-card border border-slate-200 dark:border-border border-l-4 rounded-xl px-4 py-3 shadow-lg",
        "transition-all duration-300",
        border,
        visible ? "translate-y-0 opacity-100" : "translate-y-2 opacity-0"
      )}
    >
      <Icon className={cn("w-4 h-4 mt-0.5 flex-shrink-0", iconClass)} />
      <span className="text-sm text-slate-700 dark:text-foreground flex-1">{message}</span>
      <button
        onClick={() => { setVisible(false); setTimeout(onClose, 300); }}
        className="text-slate-400 hover:text-slate-600 dark:hover:text-foreground ml-1 -mt-0.5"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
