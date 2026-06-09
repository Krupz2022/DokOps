import React, { useRef } from "react";
import ReactDOM from "react-dom";
import { X } from "lucide-react";
import { Button } from "./Button";
import { cn } from "../../lib/utils";

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
}

export function Modal({ isOpen, onClose, title, children, footer, className }: ModalProps) {
  const mousedownOnBackdrop = useRef(false);

  if (!isOpen) return null;

  return ReactDOM.createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
      onMouseDown={(e) => { mousedownOnBackdrop.current = e.target === e.currentTarget; }}
      onClick={(e) => { if (mousedownOnBackdrop.current && e.target === e.currentTarget) onClose(); }}
    >
      <div
        className={cn(
          "bg-white dark:bg-card border border-slate-200 dark:border-border rounded-2xl shadow-2xl w-full",
          "animate-in fade-in zoom-in-95 duration-200 max-h-[90vh] flex flex-col",
          className ?? "max-w-md"
        )}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 dark:border-border flex-shrink-0">
          <h3 className="text-base font-semibold text-slate-900 dark:text-foreground">{title}</h3>
          <Button variant="ghost" size="icon" onClick={onClose} className="h-7 w-7 -mr-1">
            <X className="w-4 h-4" />
          </Button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4">{children}</div>

        {/* Footer */}
        {footer && (
          <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-slate-100 dark:border-border bg-slate-50 dark:bg-muted/30 rounded-b-2xl flex-shrink-0">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
