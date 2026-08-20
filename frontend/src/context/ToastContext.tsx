import { createContext, useContext, useState, useCallback, useRef } from "react";
import { createPortal } from "react-dom";
import { X, CheckCircle, AlertCircle } from "lucide-react";

interface Toast {
  id: number;
  message: string;
  type: "success" | "error";
}

interface ToastContextValue {
  showToast: (message: string, type?: "success" | "error") => void;
}

const ToastContext = createContext<ToastContextValue>({ showToast: () => {} });

export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(0);

  const showToast = useCallback(
    (message: string, type: "success" | "error" = "success") => {
      const id = ++nextId.current;
      setToasts((prev) => [...prev, { id, message, type }]);
      setTimeout(
        () => setToasts((prev) => prev.filter((t) => t.id !== id)),
        3000
      );
    },
    []
  );

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {createPortal(
        <div
          style={{
            position: "fixed",
            bottom: 24,
            right: 24,
            zIndex: 9999,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          {toasts.map((toast) => (
            <div
              key={toast.id}
              style={{
                backgroundColor:
                  toast.type === "success"
                    ? "var(--color-success)"
                    : "var(--color-danger)",
                color: "white",
                padding: "12px 16px",
                borderRadius: 8,
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontSize: 14,
                boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
                animation: "slideIn 0.2s ease-out",
                minWidth: 280,
              }}
            >
              {toast.type === "success" ? (
                <CheckCircle size={16} />
              ) : (
                <AlertCircle size={16} />
              )}
              {toast.message}
              <button
                onClick={() =>
                  setToasts((prev) => prev.filter((t) => t.id !== toast.id))
                }
                style={{
                  marginLeft: "auto",
                  opacity: 0.7,
                  background: "none",
                  border: "none",
                  color: "inherit",
                  cursor: "pointer",
                  padding: 0,
                }}
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>,
        document.body
      )}
    </ToastContext.Provider>
  );
}
