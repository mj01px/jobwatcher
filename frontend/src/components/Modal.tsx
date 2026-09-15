import { useEffect, useRef, type ReactNode, type RefObject } from "react";

import { MODAL_MOTION_MS, nextFrame, prefersReducedMotion } from "../lib/motion";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  labelledBy: string;
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** Extra class on the dialog, e.g. "modal-drawer" for the side panel. */
  className?: string;
  children: ReactNode;
}

/**
 * Native <dialog> opened with showModal(), so the rest of the page is inert
 * (the browser keeps focus inside) and Escape fires "cancel". The is-open
 * class drives the enter and exit transitions.
 */
export function Modal({ open, onClose, labelledBy, initialFocusRef, className, children }: ModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return undefined;

    if (open) {
      if (!dialog.open) dialog.showModal();
      initialFocusRef?.current?.focus();
      if (prefersReducedMotion()) {
        dialog.classList.add("is-open");
        return undefined;
      }
      dialog.classList.remove("is-open");
      return nextFrame(() => dialog.classList.add("is-open"));
    }

    if (!dialog.open) return undefined;
    dialog.classList.remove("is-open");
    if (prefersReducedMotion()) {
      dialog.close();
      return undefined;
    }
    const timer = window.setTimeout(() => {
      if (!dialog.classList.contains("is-open")) dialog.close();
    }, MODAL_MOTION_MS);
    return () => window.clearTimeout(timer);
  }, [open, initialFocusRef]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return undefined;
    const handleCancel = (event: Event) => {
      // Escape would otherwise close the dialog instantly, skipping the exit animation.
      event.preventDefault();
      onCloseRef.current();
    };
    const handleClick = (event: MouseEvent) => {
      if (event.target === dialog) onCloseRef.current();
    };
    dialog.addEventListener("cancel", handleCancel);
    dialog.addEventListener("click", handleClick);
    return () => {
      dialog.removeEventListener("cancel", handleCancel);
      dialog.removeEventListener("click", handleClick);
      if (dialog.open) dialog.close();
    };
  }, []);

  return (
    <dialog ref={dialogRef} className={className ? `modal ${className}` : "modal"} aria-labelledby={labelledBy} aria-modal="true">
      {children}
    </dialog>
  );
}
