import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { startVisitPings, visitJustStarted } from "./visits";

let visibility: DocumentVisibilityState = "visible";

function setVisibility(next: DocumentVisibilityState) {
  visibility = next;
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("visit pings", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    visibility = "visible";
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("pings on start and every interval while visible", () => {
    const ping = vi.fn();
    const stop = startVisitPings(ping, document, 60_000);

    expect(ping).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(59_999);
    expect(ping).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(ping).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(120_000);
    expect(ping).toHaveBeenCalledTimes(4);

    stop();
  });

  it("stops while hidden and pings again as soon as the page is visible", () => {
    const ping = vi.fn();
    const stop = startVisitPings(ping, document, 60_000);

    setVisibility("hidden");
    vi.advanceTimersByTime(10 * 60_000);
    expect(ping).toHaveBeenCalledTimes(1);

    setVisibility("visible");
    expect(ping).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(60_000);
    expect(ping).toHaveBeenCalledTimes(3);

    stop();
  });

  it("does not ping when it starts hidden, until the page becomes visible", () => {
    visibility = "hidden";
    const ping = vi.fn();
    const stop = startVisitPings(ping, document, 60_000);

    vi.advanceTimersByTime(5 * 60_000);
    expect(ping).not.toHaveBeenCalled();

    setVisibility("visible");
    expect(ping).toHaveBeenCalledTimes(1);

    stop();
  });

  it("never restarts after cleanup", () => {
    const ping = vi.fn();
    const stop = startVisitPings(ping, document, 60_000);
    stop();

    vi.advanceTimersByTime(5 * 60_000);
    setVisibility("hidden");
    setVisibility("visible");
    expect(ping).toHaveBeenCalledTimes(1);
  });

  it("repeated visible events do not stack intervals", () => {
    const ping = vi.fn();
    const stop = startVisitPings(ping, document, 60_000);

    setVisibility("visible");
    setVisibility("visible");
    expect(ping).toHaveBeenCalledTimes(3);
    vi.advanceTimersByTime(60_000);
    expect(ping).toHaveBeenCalledTimes(4);

    stop();
  });
});

describe("visitJustStarted", () => {
  it("is true for a visit opened by this ping and false for an ongoing one", () => {
    const requestedAt = Date.parse("2026-09-15T12:00:00Z");
    expect(visitJustStarted("2026-09-15T12:00:00.300Z", requestedAt)).toBe(true);
    expect(visitJustStarted("2026-09-15T11:59:58Z", requestedAt)).toBe(true);
    expect(visitJustStarted("2026-09-15T11:40:00Z", requestedAt)).toBe(false);
    expect(visitJustStarted("not a date", requestedAt)).toBe(false);
  });
});
