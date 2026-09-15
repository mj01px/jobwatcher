import { describe, expect, it, vi } from "vitest";

import { getDesktopBridge, isApplicationDetectedDetail } from "./desktopBridge";

describe("desktop bridge", () => {
  it("is null in a plain browser or with an incomplete api", () => {
    expect(getDesktopBridge({})).toBeNull();
    expect(getDesktopBridge({ pywebview: null })).toBeNull();
    expect(getDesktopBridge({ pywebview: {} })).toBeNull();
    expect(getDesktopBridge({ pywebview: { api: { open_job: "nope" } } })).toBeNull();
  });

  it("calls open_job on the pywebview api with the job id", async () => {
    const openJob = vi.fn(() => Promise.resolve(null));
    const bridge = getDesktopBridge({ pywebview: { api: { open_job: openJob } } });

    expect(bridge).not.toBeNull();
    await bridge?.openJob(42);
    expect(openJob).toHaveBeenCalledWith(42);
  });

  it("propagates a failed desktop call so the caller can fall back", async () => {
    const bridge = getDesktopBridge({ pywebview: { api: { open_job: () => Promise.reject(new Error("closed")) } } });
    await expect(bridge?.openJob(1)).rejects.toThrow("closed");
  });

  it("validates the application detected event detail", () => {
    expect(isApplicationDetectedDetail({ jobId: 1, applicationId: 2, changed: true })).toBe(true);
    expect(isApplicationDetectedDetail({ jobId: "1", applicationId: 2, changed: true })).toBe(false);
    expect(isApplicationDetectedDetail({ jobId: 1, applicationId: 2 })).toBe(false);
    expect(isApplicationDetectedDetail(null)).toBe(false);
  });
});
