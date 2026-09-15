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
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** The desktop bridge when this page runs inside the Job Watcher window, otherwise null. */
export function getDesktopBridge(target: object = window): DesktopBridge | null {
  const pywebview: unknown = Reflect.get(target, "pywebview");
  if (!isRecord(pywebview)) return null;
  const api = pywebview.api;
  if (!isRecord(api)) return null;
  const openJob = api.open_job;
  if (typeof openJob !== "function") return null;
  return {
    openJob: async (jobId) => {
      await Reflect.apply(openJob, api, [jobId]);
    },
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
