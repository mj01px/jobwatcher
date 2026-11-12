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

  it("has no saveFile on an app without save_file", () => {
    const bridge = getDesktopBridge({ pywebview: { api: { open_job: vi.fn() } } });
    expect(bridge?.saveFile).toBeNull();
  });

  it("sends the file to save_file as base64", async () => {
    const saveFile = vi.fn(() => Promise.resolve({ ok: true, path: "/tmp/cv.pdf" }));
    const bridge = getDesktopBridge({ pywebview: { api: { open_job: vi.fn(), save_file: saveFile } } });

    await bridge?.saveFile?.("cv.pdf", new Blob(["%PDF"], { type: "application/pdf" }));
    expect(saveFile).toHaveBeenCalledWith("cv.pdf", btoa("%PDF"));
  });

  it("treats a cancelled dialog as fine and a failed save as an error", async () => {
    const cancelled = getDesktopBridge({
      pywebview: { api: { open_job: vi.fn(), save_file: () => Promise.resolve({ ok: false, cancelled: true }) } },
    });
    await expect(cancelled?.saveFile?.("cv.pdf", new Blob(["x"]))).resolves.toBeUndefined();

    const failed = getDesktopBridge({
      pywebview: { api: { open_job: vi.fn(), save_file: () => Promise.resolve({ ok: false, error: "write_failed" }) } },
    });
    await expect(failed?.saveFile?.("cv.pdf", new Blob(["x"]))).rejects.toThrow("write_failed");
  });

  it("validates the application detected event detail", () => {
    expect(isApplicationDetectedDetail({ jobId: 1, applicationId: 2, changed: true })).toBe(true);
    expect(isApplicationDetectedDetail({ jobId: "1", applicationId: 2, changed: true })).toBe(false);
    expect(isApplicationDetectedDetail({ jobId: 1, applicationId: 2 })).toBe(false);
    expect(isApplicationDetectedDetail(null)).toBe(false);
  });
});
