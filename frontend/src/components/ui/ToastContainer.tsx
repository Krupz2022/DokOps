import ReactDOM from "react-dom";
import { useToast } from "../../context/ToastContext";
import { Toast } from "./Toast";

export function ToastContainer() {
  const { toasts, dismiss } = useToast();

  if (toasts.length === 0) return null;

  return ReactDOM.createPortal(
    <div className="fixed bottom-4 right-4 z-[200] flex flex-col gap-2 w-80">
      {toasts.map((t) => (
        <Toast
          key={t.id}
          message={t.message}
          type={t.type}
          onClose={() => dismiss(t.id)}
          duration={t.type === "error" ? 0 : 4000}
        />
      ))}
    </div>,
    document.body
  );
}
