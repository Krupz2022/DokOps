import React from "react";
import { Info, ShieldAlert, Trash2 } from "lucide-react";
import { Modal } from "./Modal";
import { Button } from "./Button";
import { cn } from "../../lib/utils";

export type ConfirmVariant = "danger" | "warning" | "info";

interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  description: string;
  variant: ConfirmVariant;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

const VARIANT_CONFIG: Record<
  ConfirmVariant,
  { icon: React.ElementType; iconClass: string; borderClass: string; btnClass: string }
> = {
  danger: {
    icon: Trash2,
    iconClass: "text-red-500",
    borderClass: "border-l-4 border-l-red-500",
    btnClass: "bg-red-500 hover:bg-red-600 text-white",
  },
  warning: {
    icon: ShieldAlert,
    iconClass: "text-amber-500",
    borderClass: "border-l-4 border-l-amber-500",
    btnClass: "bg-amber-500 hover:bg-amber-600 text-white",
  },
  info: {
    icon: Info,
    iconClass: "text-blue-500",
    borderClass: "border-l-4 border-l-blue-500",
    btnClass: "bg-blue-500 hover:bg-blue-600 text-white",
  },
};

export function ConfirmDialog({
  isOpen,
  title,
  description,
  variant,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const { icon: Icon, iconClass, borderClass, btnClass } = VARIANT_CONFIG[variant];

  return (
    <Modal
      isOpen={isOpen}
      onClose={onCancel}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>{cancelLabel}</Button>
          <button
            onClick={onConfirm}
            className={cn("px-4 py-2 rounded-lg text-sm font-medium transition-colors", btnClass)}
          >
            {confirmLabel}
          </button>
        </>
      }
    >
      <div className={cn("flex gap-3 p-3 rounded-lg bg-slate-50 dark:bg-muted/30", borderClass)}>
        <Icon className={cn("w-5 h-5 mt-0.5 flex-shrink-0", iconClass)} />
        <p className="text-sm text-slate-700 dark:text-foreground">{description}</p>
      </div>
    </Modal>
  );
}
