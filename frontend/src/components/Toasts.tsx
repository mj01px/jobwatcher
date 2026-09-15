import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { TOAST_DURATION_MS, TOAST_MOTION_MS, nextFrame, prefersReducedMotion } from "../lib/motion";

export interface ToastOptions {
  onUndo?: () => Promise<void>;
  onUndoSuccess?: () => void;
}

interface ToastEntry extends ToastOptions {
  id: number;
  message: string;
}

interface ToastValue {
  showToast: (message: string, options?: ToastOptions) => void;
}

const ToastContext = createContext<ToastValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const nextId = useRef(1);

  const showToast = useCallback((message: string, options: ToastOptions = {}) => {
    const id = nextId.current;
    nextId.current += 1;
    setToasts((current) => [...current, { id, message, ...options }]);
  }, []);

  const removeToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const value = useMemo(() => ({ showToast }), [showToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-region" aria-live="polite">
        {toasts.map((toast) => (
          <Toast key={toast.id} toast={toast} onRemove={removeToast} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToasts(): ToastValue {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToasts must be used inside ToastProvider");
  return value;
}

type ToastPhase = "entering" | "open" | "leaving";

function Toast({ toast, onRemove }: { toast: ToastEntry; onRemove: (id: number) => void }) {
  const { t } = useI18n();
  // Labels are fixed at creation, so a language switch never relabels a live toast.
  const [labels] = useState(() => ({ undo: t("toast.undo"), close: t("common.close") }));
  const [phase, setPhase] = useState<ToastPhase>("entering");
  const [paused, setPaused] = useState(false);
  const [undoBusy, setUndoBusy] = useState(false);

  const timerId = useRef<number | null>(null);
  const removalTimer = useRef<number | null>(null);
  const remaining = useRef(TOAST_DURATION_MS);
  const startedAt = useRef(0);
  const hovered = useRef(false);
  const focused = useRef(false);
  const dismissed = useRef(false);

  const dismiss = useCallback(() => {
    if (dismissed.current) return;
    dismissed.current = true;
    if (timerId.current !== null) {
      window.clearTimeout(timerId.current);
      timerId.current = null;
    }
    setPhase("leaving");
    if (prefersReducedMotion()) {
      onRemove(toast.id);
      return;
    }
    removalTimer.current = window.setTimeout(() => onRemove(toast.id), TOAST_MOTION_MS);
  }, [onRemove, toast.id]);

  const startTimer = useCallback(() => {
    if (timerId.current !== null || dismissed.current) return;
    startedAt.current = Date.now();
    timerId.current = window.setTimeout(dismiss, remaining.current);
    setPaused(false);
  }, [dismiss]);

  const pauseTimer = useCallback(() => {
    if (timerId.current === null) return;
    window.clearTimeout(timerId.current);
    timerId.current = null;
    remaining.current -= Date.now() - startedAt.current;
    setPaused(true);
  }, []);

  const syncPause = useCallback(() => {
    if (hovered.current || focused.current) pauseTimer();
    else startTimer();
  }, [pauseTimer, startTimer]);

  useEffect(() => {
    const cancelFrame = nextFrame(() => setPhase((current) => (current === "entering" ? "open" : current)));
    startTimer();
    return () => {
      cancelFrame();
      if (timerId.current !== null) window.clearTimeout(timerId.current);
      if (removalTimer.current !== null) window.clearTimeout(removalTimer.current);
    };
  }, [startTimer]);

  const handleUndo = async () => {
    if (!toast.onUndo) return;
    pauseTimer();
    setUndoBusy(true);
    try {
      await toast.onUndo();
      toast.onUndoSuccess?.();
      dismiss();
    } catch {
      setUndoBusy(false);
      syncPause();
    }
  };

  const className = [
    "toast",
    phase === "open" ? "is-open" : "",
    phase === "leaving" ? "is-leaving" : "",
    paused ? "is-paused" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={className}
      role="status"
      onMouseEnter={() => {
        hovered.current = true;
        syncPause();
      }}
      onMouseLeave={() => {
        hovered.current = false;
        syncPause();
      }}
      onFocus={() => {
        focused.current = true;
        syncPause();
      }}
      onBlur={() => {
        focused.current = false;
        syncPause();
      }}
    >
      <button type="button" className="toast-close" aria-label={labels.close} onClick={dismiss}>
        <span aria-hidden="true">×</span>
      </button>
      <div className="toast-body">
        <p>{toast.message}</p>
        {toast.onUndo ? (
          <button type="button" className="toast-undo" disabled={undoBusy} onClick={() => void handleUndo()}>
            {labels.undo}
          </button>
        ) : null}
      </div>
      <div className="toast-progress" />
    </div>
  );
}
