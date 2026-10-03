import type {
  ApiErrorCode,
  ApiErrorDetail,
  Application,
  ApplicationDetail,
  ApplicationStatus,
  ArchiveJobInput,
  AtsReport,
  Board,
  CheckRun,
  CreateJobInput,
  CreateSourceInput,
  Envelope,
  Interaction,
  InteractionInput,
  Job,
  JobDetail,
  JobView,
  MonitorStatus,
  Overview,
  PaginationMeta,
  Pitch,
  ProfileSettings,
  ResponseMeta,
  SaveProfileInput,
  SaveScoringInput,
  ScoringSettings,
  SecretsInput,
  SecretsStatus,
  Source,
  UpdateApplicationInput,
  UpdateSourceInput,
  VisitInfo,
} from "./types";

export const API_BASE = "/api/v1";
const CSRF_COOKIE = "csrftoken";
const CSRF_HEADER = "X-CSRFToken";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;
  readonly details: ApiErrorDetail[];
  readonly requestId: string | null;

  constructor(
    code: ApiErrorCode,
    message: string,
    options: { status: number; details?: ApiErrorDetail[]; requestId?: string | null; cause?: unknown },
  ) {
    super(message, { cause: options.cause });
    this.name = "ApiError";
    this.code = code;
    this.status = options.status;
    this.details = options.details ?? [];
    this.requestId = options.requestId ?? null;
  }
}

export interface ApiResult<T, M extends ResponseMeta = ResponseMeta> {
  data: T;
  meta: M;
}

export function readCookie(name: string): string | null {
  const prefix = `${name}=`;
  for (const part of document.cookie.split(";")) {
    const trimmed = part.trim();
    if (trimmed.startsWith(prefix)) return decodeURIComponent(trimmed.slice(prefix.length));
  }
  return null;
}

let csrfBootstrap: Promise<void> | null = null;

// GET /status sets the CSRF cookie. The layout polls it on load, so this only
// matters when a write happens before the first status response arrives.
async function ensureCsrfCookie(): Promise<string | null> {
  const existing = readCookie(CSRF_COOKIE);
  if (existing) return existing;
  csrfBootstrap ??= fetch(`${API_BASE}/status`, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  })
    .then(() => undefined)
    .catch(() => undefined)
    .finally(() => {
      csrfBootstrap = null;
    });
  await csrfBootstrap;
  return readCookie(CSRF_COOKIE);
}

function isEnvelope(value: unknown): value is Envelope<unknown> {
  return typeof value === "object" && value !== null && "data" in value && "error" in value && "meta" in value;
}

export interface RequestOptions {
  body?: unknown;
  /** Multipart body (file upload). The browser sets the Content-Type boundary. */
  form?: FormData;
  query?: Record<string, string | number | undefined>;
  signal?: AbortSignal;
  keepalive?: boolean;
}

export async function request<T, M extends ResponseMeta = ResponseMeta>(
  method: HttpMethod,
  path: string,
  options: RequestOptions = {},
): Promise<ApiResult<T, M>> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined) url.searchParams.set(key, String(value));
  }

  const headers: Record<string, string> = { Accept: "application/json" };
  // FormData sets its own multipart Content-Type (with the boundary); JSON we set.
  if (options.form === undefined && options.body !== undefined) headers["Content-Type"] = "application/json";
  if (UNSAFE_METHODS.has(method)) {
    const token = await ensureCsrfCookie();
    if (token) headers[CSRF_HEADER] = token;
  }

  const body =
    options.form !== undefined
      ? options.form
      : options.body === undefined
        ? undefined
        : JSON.stringify(options.body);

  let response: Response;
  try {
    response = await fetch(`${url.pathname}${url.search}`, {
      method,
      headers,
      credentials: "same-origin",
      body,
      signal: options.signal,
      keepalive: options.keepalive,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("NETWORK_ERROR", `Request to ${path} failed`, { status: 0, cause: error });
  }

  if (response.status === 204) {
    return { data: null as T, meta: { requestId: response.headers.get("X-Request-ID") ?? "" } as M };
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    throw new ApiError(
      response.ok ? "NETWORK_ERROR" : "INTERNAL_ERROR",
      `Invalid JSON from ${path} (HTTP ${response.status})`,
      { status: response.status, requestId: response.headers.get("X-Request-ID"), cause: error },
    );
  }

  if (!isEnvelope(payload)) {
    throw new ApiError("INTERNAL_ERROR", `Unexpected response shape from ${path}`, {
      status: response.status,
      requestId: response.headers.get("X-Request-ID"),
    });
  }

  const meta = payload.meta as M;
  if (!response.ok || payload.error) {
    const body = payload.error;
    throw new ApiError(body?.code ?? "INTERNAL_ERROR", body?.message ?? `HTTP ${response.status}`, {
      status: response.status,
      details: body?.details,
      requestId: meta?.requestId ?? null,
    });
  }

  return { data: payload.data as T, meta };
}

/** Pull the download filename out of a Content-Disposition header. */
function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null;
  const value = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header)?.[1];
  return value ? decodeURIComponent(value) : null;
}

const RESUME_POLL_INTERVAL_MS = 2000;
const RESUME_POLL_TIMEOUT_MS = 4 * 60_000; // the AI can take ~100s; give it headroom

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** One poll of a resume generation: the PDF when ready, null while still pending. */
async function pollResumePdf(
  jobId: number,
  token: string,
): Promise<{ blob: Blob; filename: string } | null> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/jobs/${jobId}/resume/${token}`, {
      method: "GET",
      headers: { Accept: "application/pdf, application/json" },
      credentials: "same-origin",
    });
  } catch (error) {
    throw new ApiError("NETWORK_ERROR", `Request to /jobs/${jobId}/resume failed`, {
      status: 0,
      cause: error,
    });
  }

  if (response.status === 202) return null; // still generating

  if (!response.ok) {
    let code: ApiErrorCode = "INTERNAL_ERROR";
    let message = `HTTP ${response.status}`;
    try {
      const payload: unknown = await response.json();
      if (isEnvelope(payload) && payload.error) {
        code = payload.error.code;
        message = payload.error.message;
      }
    } catch {
      // Non-JSON error body: keep the generic defaults.
    }
    throw new ApiError(code, message, {
      status: response.status,
      requestId: response.headers.get("X-Request-ID"),
    });
  }

  const blob = await response.blob();
  const filename =
    filenameFromDisposition(response.headers.get("Content-Disposition")) ?? "curriculo.pdf";
  return { blob, filename };
}

/**
 * Start a tailored-resume generation and poll until the PDF is ready.
 *
 * Generation runs in the background on the server (it can take ~100s), so a plain
 * request would outlive the webview's timeout. The POST returns a token; we then
 * poll for the PDF.
 */
async function requestResumePdf(
  jobId: number,
  resume: File,
): Promise<{ blob: Blob; filename: string }> {
  const form = new FormData();
  form.append("resume", resume);
  const { data } = await request<{ token: string }>("POST", `/jobs/${jobId}/resume`, { form });

  const deadline = Date.now() + RESUME_POLL_TIMEOUT_MS;
  for (;;) {
    await delay(RESUME_POLL_INTERVAL_MS);
    const result = await pollResumePdf(jobId, data.token);
    if (result) return result;
    if (Date.now() > deadline) {
      throw new ApiError("AI_UNAVAILABLE", "Resume generation timed out", { status: 504 });
    }
  }
}

export const api = {
  status: (signal?: AbortSignal) => request<MonitorStatus>("GET", "/status", { signal }),
  overview: (signal?: AbortSignal) => request<Overview>("GET", "/overview", { signal }),
  jobs: (view: JobView, page: number, signal?: AbortSignal) =>
    request<Job[], PaginationMeta>("GET", "/jobs", { query: { view, page }, signal }),
  job: (id: number, signal?: AbortSignal) => request<JobDetail>("GET", `/jobs/${id}`, { signal }),
  createJob: (input: CreateJobInput) => request<Job>("POST", "/jobs", { body: input }),
  archiveJob: (id: number, input: ArchiveJobInput) =>
    request<Job>("POST", `/jobs/${id}/archive`, { body: { reason: input.reason, note: input.note ?? "" } }),
  restoreJob: (id: number) => request<Job>("POST", `/jobs/${id}/restore`),
  visitJob: (id: number) => request<Job>("POST", `/jobs/${id}/visit`, { keepalive: true }),
  createApplication: (jobId: number, status: Extract<ApplicationStatus, "interest" | "applied">) =>
    request<Application>("POST", `/jobs/${jobId}/application`, { body: { status } }),
  pitch: (jobId: number, signal?: AbortSignal) => request<Pitch | null>("GET", `/jobs/${jobId}/pitch`, { signal }),
  generatePitch: (jobId: number, instruction: string) =>
    request<Pitch>("POST", `/jobs/${jobId}/pitch`, { body: { instruction } }),
  ats: (jobId: number, signal?: AbortSignal) =>
    request<AtsReport | null>("GET", `/jobs/${jobId}/ats`, { signal }),
  generateAts: (jobId: number, resume: File) => {
    const form = new FormData();
    form.append("resume", resume);
    return request<AtsReport>("POST", `/jobs/${jobId}/ats`, { form });
  },
  generateResume: (jobId: number, resume: File) => requestResumePdf(jobId, resume),

  board: (signal?: AbortSignal) => request<Board>("GET", "/applications/board", { signal }),
  closedApplications: (signal?: AbortSignal) => request<Application[]>("GET", "/applications/closed", { signal }),
  application: (id: number, signal?: AbortSignal) =>
    request<ApplicationDetail>("GET", `/applications/${id}`, { signal }),
  updateApplication: (id: number, input: UpdateApplicationInput) =>
    request<Application>("PATCH", `/applications/${id}`, { body: input }),
  deleteApplication: (id: number) => request<null>("DELETE", `/applications/${id}`),
  createInteraction: (applicationId: number, input: InteractionInput) =>
    request<Interaction>("POST", `/applications/${applicationId}/interactions`, { body: input }),
  updateInteraction: (id: number, input: Partial<InteractionInput>) =>
    request<Interaction>("PATCH", `/interactions/${id}`, { body: input }),
  deleteInteraction: (id: number) => request<null>("DELETE", `/interactions/${id}`),

  sources: (signal?: AbortSignal) => request<Source[]>("GET", "/sources", { signal }),
  createSource: (input: CreateSourceInput) => request<Source>("POST", "/sources", { body: input }),
  updateSource: (id: number, input: UpdateSourceInput) => request<Source>("PATCH", `/sources/${id}`, { body: input }),
  deleteSource: (id: number) => request<null>("DELETE", `/sources/${id}`),

  scoring: (signal?: AbortSignal) => request<ScoringSettings>("GET", "/settings/scoring", { signal }),
  saveScoring: (input: SaveScoringInput) => request<ScoringSettings>("PUT", "/settings/scoring", { body: input }),
  profile: (signal?: AbortSignal) => request<ProfileSettings>("GET", "/settings/profile", { signal }),
  saveProfile: (input: SaveProfileInput) => request<ProfileSettings>("PUT", "/settings/profile", { body: input }),
  saveSecrets: (input: SecretsInput) => request<SecretsStatus>("PUT", "/settings/secrets", { body: input }),

  checkRuns: (limit: number, signal?: AbortSignal) =>
    request<CheckRun[]>("GET", "/check-runs", { query: { limit }, signal }),
  startCheck: () => request<CheckRun>("POST", "/check-runs"),

  visit: () => request<VisitInfo>("POST", "/visits", { keepalive: true }),
};
