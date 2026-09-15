// "New" means new since the previous visit (docs/API-v3.md, section 5). The backend
// decides where a visit starts; the page only has to say it is being looked at.

export const VISIT_PING_INTERVAL_MS = 60_000;

/**
 * Pings on start and whenever the document becomes visible, then every interval
 * while it stays visible. A hidden page (minimized window, background tab) never
 * pings, so the backend can tell when a visit ended. Returns a cleanup function.
 */
export function startVisitPings(
  ping: () => void,
  doc: Document = document,
  intervalMs: number = VISIT_PING_INTERVAL_MS,
): () => void {
  let timer: ReturnType<typeof setInterval> | null = null;

  const stopTimer = () => {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  };

  const startVisible = () => {
    ping();
    stopTimer();
    timer = setInterval(ping, intervalMs);
  };

  const handleVisibility = () => {
    if (doc.visibilityState === "visible") startVisible();
    else stopTimer();
  };

  if (doc.visibilityState === "visible") startVisible();
  doc.addEventListener("visibilitychange", handleVisibility);

  return () => {
    doc.removeEventListener("visibilitychange", handleVisibility);
    stopTimer();
  };
}

/** A visit that started around the time of this ping means isNew values changed. */
export function visitJustStarted(visitStartedAt: string, requestedAt: number, toleranceMs = 5_000): boolean {
  const started = Date.parse(visitStartedAt);
  return Number.isFinite(started) && started >= requestedAt - toleranceMs;
}
