import type {
  ApiErrorCode,
  ApiErrorDetail,
  Application,
  ApplicationDetail,
  ApplicationStatus,
  ArchiveJobInput,
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
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (UNSAFE_METHODS.has(method)) {
    const token = await ensureCsrfCookie();
    if (token) headers[CSRF_HEADER] = token;
  }

  let response: Response;
  try {
    response = await fetch(`${url.pathname}${url.search}`, {
      method,
      headers,
      credentials: "same-origin",
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
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
