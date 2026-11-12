// The Windows desktop app (desktop/app.py) exposes a pywebview js_api on the main
// window. In a plain browser none of this exists and every helper returns null.
// See docs/API-v3.md, section 9.

export const APPLICATION_DETECTED_EVENT = "jobwatcher:application-detected";

export interface ApplicationDetectedDetail {
  jobId: number;
  applicationId: number;
  changed: boolean;
}

export interface DesktopBridge {
  /** Opens the job inside the desktop app, which watches for the InHire application submit. */
  openJob: (jobId: number) => Promise<void>;
  /**
   * Saves a file through the native "Save as" dialog. The webview cannot download a
   * blob (WKWebView opens a PDF in place of the dashboard). Null on an older app.
   */
  saveFile: ((filename: string, blob: Blob) => Promise<void>) | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** The blob as base64, the only way to pass bytes through the pywebview bridge. */
function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const url = typeof reader.result === "string" ? reader.result : "";
      resolve(url.slice(url.indexOf(",") + 1));
    };
    reader.onerror = () => reject(reader.error ?? new Error("Could not read the file"));
    reader.readAsDataURL(blob);
  });
}

/** The desktop bridge when this page runs inside the Job Watcher window, otherwise null. */
export function getDesktopBridge(target: object = window): DesktopBridge | null {
  const pywebview: unknown = Reflect.get(target, "pywebview");
  if (!isRecord(pywebview)) return null;
  const api = pywebview.api;
  if (!isRecord(api)) return null;
  const openJob = api.open_job;
  if (typeof openJob !== "function") return null;
  const saveFile = api.save_file;
  return {
    openJob: async (jobId) => {
      await Reflect.apply(openJob, api, [jobId]);
    },
    saveFile:
      typeof saveFile === "function"
        ? async (filename, blob) => {
            const result: unknown = await Reflect.apply(saveFile, api, [
              filename,
              await blobToBase64(blob),
            ]);
            if (isRecord(result) && result.ok !== true && result.cancelled !== true) {
              throw new Error(`Could not save the file: ${String(result.error)}`);
            }
          }
        : null,
  };
}

export function isApplicationDetectedDetail(value: unknown): value is ApplicationDetectedDetail {
  return (
    isRecord(value) &&
    typeof value.jobId === "number" &&
    typeof value.applicationId === "number" &&
    typeof value.changed === "boolean"
  );
}
