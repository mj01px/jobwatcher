// Mirrors docs/API.md and docs/API-v3.md. Keep them in sync.

export type JobStatus = "active" | "archived";
export type ArchiveSource = "manual" | "source";
export type ManualArchiveReason =
  | "applied"
  | "not_interested"
  | "onsite"
  | "hybrid"
  | "remote"
  | "requirements"
  | "compensation"
  | "closed"
  | "other";
export type SystemArchiveReason = "source_removed" | "expired";
export type ArchiveReason = ManualArchiveReason | SystemArchiveReason;

export type SourceKind = "inhire" | "gupy" | "github" | "manual";
/** Kinds a person can add from the Sources page. */
export type CollectedSourceKind = Exclude<SourceKind, "manual">;
export type WorkMode = "remote" | "hybrid" | "onsite" | "unknown";
export type Seniority = "internship" | "junior" | "mid" | "senior" | "unknown";

export type ApplicationStatus =
  | "interest"
  | "applied"
  | "screening"
  | "challenge"
  | "interview"
  | "offer"
  | "rejected"
  | "withdrawn";

export interface ApplicationSummary {
  id: number;
  status: ApplicationStatus;
}

export interface Job {
  id: number;
  sourceId: number;
  sourceKind: SourceKind;
  sourceName: string;
  companyName: string;
  externalId: string;
  title: string;
  url: string;
  status: JobStatus;
  archiveSource: ArchiveSource | null;
  archiveReason: ArchiveReason | null;
  archiveNote: string | null;
  isHighlighted: boolean;
  isNew: boolean;
  firstSeenAt: string;
  lastSeenAt: string;
  archivedAt: string | null;
  reopenedAt: string | null;
  firstVisitedAt: string | null;
  lastVisitedAt: string | null;
  location: string;
  workMode: WorkMode;
  seniority: Seniority;
  publishedAt: string | null;
  score: number;
  scoreTags: string[];
  /** Positive scoring groups that matched; highlight needs one of the stack groups. */
  scoreGroups: string[];
  application: ApplicationSummary | null;
}

export interface Pitch {
  id: number;
  jobId: number;
  text: string;
  model: string;
  instruction: string;
  maxChars: number;
  chars: number;
  createdAt: string;
}

export type JobDetail = Job & { description: string; pitch: Pitch | null };

export interface Source {
  id: number;
  kind: CollectedSourceKind;
  name: string;
  target: string;
  isActive: boolean;
  lastCheckedAt: string | null;
  lastError: string | null;
  activeJobs: number;
  /** Active, highlighted and without an application. */
  highlightedJobs: number;
  /** Jobs of this source that have an application. */
  applications: number;
  /** Jobs returned in the latest run that checked this source; null when never checked. */
  lastRunJobs: number | null;
  createdAt: string;
  updatedAt: string;
}

export interface Application {
  id: number;
  job: Job;
  status: ApplicationStatus;
  priority: 1 | 2 | 3 | 4 | 5;
  /** YYYY-MM-DD */
  appliedOn: string | null;
  nextStep: string;
  /** YYYY-MM-DD */
  nextStepOn: string | null;
  contact: string;
  hasReferral: boolean;
  notes: string;
  isOverdue: boolean;
  daysIdle: number;
  interactionsCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface Interaction {
  id: number;
  applicationId: number;
  /** YYYY-MM-DD */
  date: string;
  title: string;
  detail: string;
  createdAt: string;
}

export type ApplicationDetail = Application & { interactions: Interaction[] };

export interface BoardColumn {
  status: ApplicationStatus;
  applications: Application[];
}

export interface Board {
  columns: BoardColumn[];
  overdue: Application[];
  counts: Record<ApplicationStatus, number>;
}

export type RunStatus = "queued" | "running" | "success" | "partial" | "failed";
export type RunTrigger = "scheduled" | "catch_up" | "manual";

export interface CheckRun {
  id: number;
  trigger: RunTrigger;
  status: RunStatus;
  requestedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  heartbeatAt: string | null;
  sourcesTotal: number;
  sourcesChecked: number;
  jobsFound: number;
  jobsNew: number;
  jobsArchived: number;
  error: string | null;
  durationSeconds: number | null;
  isStalled: boolean;
}

export type SourceRunState = "pending" | "collecting" | "done" | "error";

export interface RunProgressSource {
  sourceId: number;
  kind: SourceKind;
  name: string;
  state: SourceRunState;
  jobs: number | null;
}

export interface RunProgress {
  runId: number;
  startedAt: string | null;
  updatedAt: string;
  total: number;
  settled: number;
  counts: Record<SourceRunState, number>;
  sources: RunProgressSource[];
}

export interface MonitorStatus {
  lastRun: CheckRun | null;
  isRunning: boolean;
  isStalled: boolean;
  progress: RunProgress | null;
  nextRunAt: string | null;
  workerOnline: boolean;
}

export interface Overview {
  jobStats: { active: number; new: number; highlighted: number; archived: number };
  sourceStats: { active: number; errors: number };
  pipelineStats: { active: number; overdue: number; interviews: number };
  recentJobs: Job[];
  overdueApplications: Application[];
}

export type JobView = "all" | "highlighted" | "archived";

export interface ScoringGroup {
  weight: number;
  terms: string[];
}

export interface ScoringSettings {
  groups: Record<string, ScoringGroup>;
  minScore: number;
  /** Group keys that count as stack: a highlight needs a hit in one of them. */
  stackGroups: string[];
  isDefault: boolean;
}

export interface SaveScoringInput {
  groups: Record<string, ScoringGroup> | null;
  minScore: number;
  stackGroups: string[];
}

export interface VisitInfo {
  visitStartedAt: string;
  previousVisitEndedAt: string | null;
}

export interface ProfileSettings {
  dossier: string;
  pitchMaxChars: number;
  geminiModel: string;
  geminiConfigured: boolean;
  githubConfigured: boolean;
}

export interface SaveProfileInput {
  dossier?: string;
  pitchMaxChars?: number;
  geminiModel?: string;
}

export interface SecretsInput {
  geminiApiKey?: string;
  githubToken?: string;
}

export interface SecretsStatus {
  geminiConfigured: boolean;
  githubConfigured: boolean;
}

export interface ResponseMeta {
  requestId: string;
}

export interface PaginationMeta extends ResponseMeta {
  page: number;
  perPage: number;
  total: number;
  totalPages: number;
}

export type ApiErrorCode =
  | "VALIDATION_ERROR"
  | "CSRF_FAILED"
  | "FORBIDDEN"
  | "NOT_FOUND"
  | "METHOD_NOT_ALLOWED"
  | "CONFLICT"
  | "UNSUPPORTED_MEDIA_TYPE"
  | "INVALID_ARCHIVE_REASON"
  | "DOSSIER_EMPTY"
  | "GEMINI_NOT_CONFIGURED"
  | "AI_UNAVAILABLE"
  | "INTERNAL_ERROR"
  | "ERROR"
  // Client side only: the request never produced a valid envelope.
  | "NETWORK_ERROR";

export interface ApiErrorDetail {
  field: string;
  issue: string;
}

export interface ApiErrorBody {
  code: ApiErrorCode;
  message: string;
  details?: ApiErrorDetail[];
}

export interface Envelope<T, M extends ResponseMeta = ResponseMeta> {
  data: T;
  error: ApiErrorBody | null;
  meta: M;
}

export interface CreateSourceInput {
  kind: CollectedSourceKind;
  name: string;
  target: string;
}

export interface UpdateSourceInput {
  name?: string;
  target?: string;
  isActive?: boolean;
}

export interface ArchiveJobInput {
  reason: ManualArchiveReason;
  note?: string;
}

export interface CreateJobInput {
  title: string;
  url: string;
  companyName?: string;
  location?: string;
  workMode?: WorkMode;
  seniority?: Seniority;
  description?: string;
}

export interface UpdateApplicationInput {
  status?: ApplicationStatus;
  priority?: number;
  appliedOn?: string | null;
  nextStep?: string;
  nextStepOn?: string | null;
  contact?: string;
  hasReferral?: boolean;
  notes?: string;
}

export interface InteractionInput {
  date?: string;
  title: string;
  detail?: string;
}
