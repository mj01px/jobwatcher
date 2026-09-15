export const MODAL_MOTION_MS = 180;
export const TOAST_MOTION_MS = 220;
export const TOAST_DURATION_MS = 5000;
export const ROW_LEAVE_PHASE_MS = 180;
export const ROW_COLLAPSE_PHASE_MS = 220;
export const ROW_ENTER_MS = 240;

export function prefersReducedMotion(): boolean {
  if (typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Runs `apply` after two animation frames so the browser paints the "before"
 * state first. Returns a cancel function.
 */
export function nextFrame(apply: () => void): () => void {
  let inner = 0;
  const outer = requestAnimationFrame(() => {
    inner = requestAnimationFrame(apply);
  });
  return () => {
    cancelAnimationFrame(outer);
    cancelAnimationFrame(inner);
  };
}
