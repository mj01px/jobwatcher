# Job Watcher API contract (v3)

Single source of truth shared by `backend/` (Django + DRF) and `frontend/` (React + Vite).
v2 brought Vaggio in (scoring, Gupy and GitHub sources, applications funnel, AI cover letters,
manual jobs, data import) while keeping Job Watcher's flow, interface and architecture. v3 is about less noise: highlights need a stack
hit, "new" means new since your last visit, sources show their yield, v1 "applied" archives became
applications, and the desktop app notifies and detects InHire applications.

**Out of scope on purpose:** login, users, roles, invites, 2FA, password or e-mail flows, Radar
filters. Job Watcher is a local single user app without authentication.

## Architecture

```
frontend (React SPA) ──/api/v1──▶ web (Django + DRF, waitress)
                                      │  SQLite (WAL) in the data directory
                                      ▼
                          worker (manage.py run_worker, or a thread in the desktop app)
                          APScheduler cron 09,12,15,18 + catch up
                          polls queued check runs every 2s
```

- `web` never collects jobs. "Check now" inserts a `queued` check run; the worker picks it up.
- Only one run executes at a time. Live progress is persisted per source (`CheckRunSource`) so the web process can read it.
- The worker writes a heartbeat (`Setting` key `worker_heartbeat`) every 10s.
- Production: Django serves the built SPA (`index.html` for non API routes) and assets through WhiteNoise.
- Dev: Django on `127.0.0.1:8000`, Vite on `5173` proxying `/api` and `/healthz` to Django.

## Conventions

- Base path `/api/v1`. JSON keys are **camelCase**. Timestamps ISO 8601 UTC (`2026-09-14T09:00:00Z`), calendar dates `YYYY-MM-DD` in `JOB_WATCHER_TIMEZONE`, `null` when absent (never missing keys).
- Envelope on every response:
  - success: `{ "data": ..., "error": null, "meta": { "requestId": "..." , ...extra } }`
  - error: `{ "data": null, "error": { "code": "...", "message": "...", "details": [...] }, "meta": { "requestId": "..." } }`
- `X-Request-ID` response header mirrors `meta.requestId` (reuse incoming header when present).
- CSRF: unsafe methods require `X-CSRFToken` header matching the `csrftoken` cookie. `GET /api/v1/status` (and the SPA index) set the cookie.
- No authentication (local self hosted tool, port bound to 127.0.0.1).

| HTTP | code | when |
|---|---|---|
| 400 | `VALIDATION_ERROR` | bad body or query (details: `[{ field, issue }]`) |
| 403 | `CSRF_FAILED` | missing or wrong CSRF token |
| 403 | `FORBIDDEN` | any other permission failure |
| 404 | `NOT_FOUND` | unknown id or route |
| 405 | `METHOD_NOT_ALLOWED` | wrong HTTP method |
| 409 | `CONFLICT` | duplicate source target, manual job URL or application |
| 409 | `PITCH_IN_PROGRESS` | a cover letter is already being generated |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | body is not JSON |
| 422 | `INVALID_ARCHIVE_REASON` | archive reason not in the list |
| 422 | `DOSSIER_EMPTY` | dossier has fewer than 400 useful characters |
| 500 | `INTERNAL_ERROR` | unhandled failure, never a stack trace |
| 502 | `AI_UNAVAILABLE` | Gemini failed, timed out or returned no text |
| 503 | `GEMINI_NOT_CONFIGURED` | no Gemini API key |
| other | `ERROR` | any other DRF error |

## Data model

### Source (`watcher`, table `sources`)
`id, kind (inhire|gupy|github|manual), name, target, is_active, is_removed, is_hidden, created_at, updated_at, last_checked_at, last_error`
- `target`: InHire career page URL, Gupy search term or GitHub `owner/repo`. Unique `(kind, target)`.
- `is_hidden`: the single `manual` source and the `imported:vaggio` placeholders (kind gupy or github, inactive). Hidden sources are never listed nor collected.
- Seeds: 74 InHire companies, 38 Gupy terms, 4 GitHub repos (Vaggio's measured lists), plus the hidden manual source.

### Job (`watcher`, table `jobs`)
`source (FK), external_id, key (unique), title, url, company_name, location, work_mode, seniority, description, published_at, score, score_tags, score_groups, status, archive_source, archive_reason, archive_note, is_highlighted, arrived_new, first_seen_at, last_seen_at, archived_at, reopened_at, first_visited_at, last_visited_at`
- `key`: `inhire:<jobId>`, `gupy:<gupy id>` (URL when the id is missing), `github:<issue html_url>`, `manual:<sha256 of lowercased url>`. A job keeps the source that found it first; later sources returning the same key only update it. Exception: a job still owned by a hidden `imported:vaggio` placeholder moves to the real source that returns it.
- `score_groups`: keys of the positive scoring groups that matched.
- `arrived_new` (v1/v2 `is_new`, renamed): true when inserted outside a baseline or reopened; never reset by a run; cleared by archive, source removal, expiry and entering the funnel. `arrived_at = reopened_at or first_seen_at`.
- Archive reasons: manual `not_interested`, `onsite`, `hybrid`, `remote`, `requirements`, `compensation`, `closed`, `other`; system `source_removed` and `expired`. The v1 manual `applied` reason is rejected since v3: migration `pipeline.0002` turned every such archive into an `applied` Application (`applied_on` = local date of `archived_at`, created and updated at `archived_at`, timeline "Entered the funnel") and restored the job to active.

### pipeline app
- `Application` (table `applications`): one to one with Job. `status` (interest|applied|screening|challenge|interview|offer|rejected|withdrawn), `priority` 1..5 (default 3), `applied_on`, `next_step`, `next_step_on`, `contact`, `has_referral`, `notes`, timestamps. Active = not rejected nor withdrawn. Overdue = active and `next_step_on < today`.
- `Interaction` (table `interactions`): application, `date`, `title`, `detail`, timestamps. Entering the funnel writes "Entered the funnel"; every status change writes "`Old` -> `New`".
- `Pitch` (table `pitches`): job, `text`, `model`, `instruction`, `max_chars`, token counters, timestamps. One per job: generating again replaces it only after the new text exists.

### Settings (`Setting` table unless noted)
- `scoring_profile` (groups JSON, empty means the default profile), `highlight_min_score` (default 25; migration `watcher.0007` moved a saved 20 to 25 and rescored every job), `highlight_stack_groups` (JSON list, default `["core", "adjacent"]`).
- Visits: `visit_last_ping_at`, `visit_started_at`, `visit_previous_end_at` (ISO strings; absent means never).
- Desktop: `notifications_enabled` (bool, default true), `overdue_notice_last_on` (`YYYY-MM-DD`).
- `dossier`, `pitch_max_chars` (default 1200), `gemini_model` (default `GEMINI_MODEL`, `gemini-3.7-flash`).
- Secrets `gemini_api_key` and `github_token` are **not** in the database: `<JOB_WATCHER_DATA_DIR>/secrets.json` (or `JOB_WATCHER_SECRETS_FILE`). Env vars `GEMINI_API_KEY` / `GITHUB_TOKEN` win. Never logged nor returned.

## Types

```ts
type SourceKind = "inhire" | "gupy" | "github" | "manual";
type JobStatus = "active" | "archived";
type ArchiveSource = "manual" | "source";
type ArchiveReason =
  | "not_interested" | "onsite" | "hybrid" | "remote"
  | "requirements" | "compensation" | "closed" | "other"
  | "source_removed" | "expired"   // only set by the system
  | "applied";                     // legacy, never accepted and converted away by v3
type WorkMode = "remote" | "hybrid" | "onsite" | "unknown";
type Seniority = "internship" | "junior" | "mid" | "senior" | "unknown";
type ApplicationStatus =
  | "interest" | "applied" | "screening" | "challenge" | "interview" | "offer"
  | "rejected" | "withdrawn";

interface Job {
  id: number;
  sourceId: number;
  sourceKind: SourceKind;
  sourceName: string;
  companyName: string;          // "" when unknown
  externalId: string;
  title: string;
  url: string;
  location: string;
  workMode: WorkMode;
  seniority: Seniority;
  publishedAt: string | null;
  score: number;
  scoreTags: string[];
  scoreGroups: string[];        // positive groups that matched
  status: JobStatus;
  archiveSource: ArchiveSource | null;
  archiveReason: ArchiveReason | null;
  archiveNote: string | null;
  isHighlighted: boolean;       // score >= minScore and (stackGroups empty or a stack group matched)
  isNew: boolean;               // arrived_new and (no previous visit or arrived_at > previousVisitEndedAt)
  firstSeenAt: string;
  lastSeenAt: string;
  archivedAt: string | null;
  reopenedAt: string | null;
  firstVisitedAt: string | null;
  lastVisitedAt: string | null;
  application: { id: number; status: ApplicationStatus } | null;
}

type JobDetail = Job & { description: string; pitch: Pitch | null };

interface Source {
  id: number;
  kind: Exclude<SourceKind, "manual">;
  name: string;
  target: string;
  isActive: boolean;
  lastCheckedAt: string | null;
  lastError: string | null;
  activeJobs: number;
  highlightedJobs: number;      // active, highlighted, without application
  applications: number;         // jobs of this source with an Application
  lastRunJobs: number | null;   // jobs returned in the latest finished run that checked it
  createdAt: string;
  updatedAt: string;
}

type RunStatus = "queued" | "running" | "success" | "partial" | "failed";
type RunTrigger = "scheduled" | "catch_up" | "manual";

interface CheckRun {
  id: number;
  trigger: RunTrigger;
  status: RunStatus;
  requestedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  heartbeatAt: string | null;
  sourcesTotal: number;
  sourcesChecked: number;       // includes partial sources
  jobsFound: number;
  jobsNew: number;
  jobsArchived: number;         // includes expired jobs
  error: string | null;
  durationSeconds: number | null;
  isStalled: boolean;           // running and heartbeat (or startedAt) older than 180s
}

type SourceRunState = "pending" | "collecting" | "done" | "error";

interface RunProgress {
  runId: number;
  startedAt: string | null;
  updatedAt: string;
  total: number;
  settled: number; // done + error
  counts: Record<SourceRunState, number>;
  sources: { sourceId: number; kind: SourceKind; name: string; state: SourceRunState; jobs: number | null }[];
}

interface Application {
  id: number;
  job: Job;
  status: ApplicationStatus;
  priority: 1 | 2 | 3 | 4 | 5;
  appliedOn: string | null;     // YYYY-MM-DD
  nextStep: string;
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

interface Interaction { id: number; applicationId: number; date: string; title: string; detail: string; createdAt: string }

interface Pitch { id: number; jobId: number; text: string; model: string; instruction: string; maxChars: number; chars: number; createdAt: string }
```

## Endpoints

### `GET /healthz`
`{ "status": "ok", "time": "<iso>" }` (no envelope, used to check the app is up).

### `GET /api/v1/status`
Global monitor state. Sets the CSRF cookie.
```json
{ "lastRun": CheckRun | null, "isRunning": true, "isStalled": false,
  "progress": RunProgress | null, "nextRunAt": "<iso>" | null, "workerOnline": true }
```

### `GET /api/v1/overview`
```json
{ "jobStats": { "active": 0, "new": 0, "highlighted": 0, "archived": 0 },
  "sourceStats": { "active": 0, "errors": 0 },
  "pipelineStats": { "active": 0, "overdue": 0, "interviews": 0 },
  "overdueApplications": Application[],
  "recentJobs": Job[] }
```
- `jobStats.active|new|highlighted` count active jobs without an application; `archived` counts every archived job.
- `sourceStats`: visible (not removed, not hidden) sources; `active` also requires `isActive`, `errors` requires `lastError`.
- `jobStats.new` uses the computed `isNew`.
- `overdueApplications`: up to 5, `nextStepOn asc`. `recentJobs`: the 8 most recent **highlighted** active jobs without an application, `isNew desc, firstSeenAt desc`.

### Jobs
- `GET /jobs?view=all|highlighted|archived&page=N`: 20 per page, `meta: { requestId, page, perPage, total, totalPages }`. Unknown view: 400. `page` normalized (non int or < 1 becomes 1, clamped to the last page, 1 when empty).
  - `all`: active without application, `isNew desc, firstSeenAt desc, title` (case insensitive).
  - `highlighted`: active without application and `isHighlighted`, `score desc, isNew desc, firstSeenAt desc, title`.
  - `archived`: archived (application or not), v1 order.
- `GET /jobs/{id}` → `JobDetail`.
- `POST /jobs` manual entry `{ title, url, companyName?, location?, workMode?, seniority?, description? }` → 201 `Job`. Hidden manual source, scored, not new; a given `workMode`/`seniority` other than `unknown` wins over detection. 409 `CONFLICT` when the key exists.
- `POST /jobs/{id}/archive` `{ reason, note? }` → `Job` (manual source, note trimmed to 500 or null, `arrived_new=false`). 422 bad reason (including system reasons and the legacy `applied`), 404.
- `POST /jobs/{id}/restore` → `Job` (clears archive fields and `reopenedAt`).
- `POST /jobs/{id}/visit` → `Job` (`firstVisitedAt` kept, `lastVisitedAt` now).
- `POST /jobs/{id}/application` `{ status?: "interest" | "applied" }` (default `applied`, which sets `appliedOn = today`) → 201 `Application`. 409 when one exists, 400 other status, 404.
- `GET /jobs/{id}/pitch` → `Pitch | null`.
- `POST /jobs/{id}/pitch` `{ instruction? }` (up to 300 chars) → 201 `Pitch`. Errors: 422 `DOSSIER_EMPTY`, 503 `GEMINI_NOT_CONFIGURED`, 502 `AI_UNAVAILABLE`, 409 `PITCH_IN_PROGRESS`.

### Sources
- `GET /sources` → `Source[]` visible, ordered by kind (`inhire`, `gupy`, `github`) then name case insensitive.
- `POST /sources { kind, name, target }` → 201. Validation: inhire http/https with host ending in `.inhire.app` (trailing slash stripped); gupy term 2..100 chars; github `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`. Upsert by `(kind, target)`: an existing row (even removed) gets the new name and becomes active and visible.
- `PATCH /sources/{id}` any of `{ name, target, isActive }` (target validated with the source kind) → `Source`. 409 when the target belongs to another source of the kind, 404 for removed or hidden.
- `DELETE /sources/{id}` → 204. Soft remove; active jobs of the source become `source / source_removed`.

### Visits
- `POST /visits` (no body) → `{ visitStartedAt, previousVisitEndedAt }`. When there is no current visit, or the last ping is more than 20 minutes old, the previous visit ends at that last ping (null on the first ever) and a new visit starts now. Every call records the ping.
- The frontend pings on load, when the document becomes visible, and every 60 s only while visible.

### Check runs
- `GET /check-runs?limit=20` (max 100), newest first by `requestedAt`.
- `POST /check-runs` → 202 `CheckRun`; returns the queued or running run instead of creating another.

### Applications
- `GET /applications/board` → `{ columns: { status, applications: Application[] }[], overdue: Application[], counts: Record<ApplicationStatus, number> }`. Columns are the 6 active statuses in order, each ordered `priority asc, updatedAt desc`. `overdue` ordered `nextStepOn asc`. `counts` covers all 8 statuses.
- `GET /applications/closed` → `Application[]` (rejected + withdrawn, `updatedAt desc`).
- `GET /applications/{id}` → `Application & { interactions: Interaction[] }` (interactions `date desc`).
- `PATCH /applications/{id}` any of `{ status, priority, appliedOn, nextStep, nextStepOn, contact, hasReferral, notes }` → `Application`. Reaching `applied` with null `appliedOn` sets today; a status change adds a timeline entry.
- `DELETE /applications/{id}` → 204 (job goes back to the lists, timeline deleted).
- `POST /applications/{id}/interactions { date?, title, detail? }` → 201 `Interaction` (date defaults to today, title 1..200 chars).
- `PATCH /interactions/{id}` any of `{ date, title, detail }` → `Interaction`; `DELETE /interactions/{id}` → 204.

### Settings
- `GET /settings/scoring` → `{ groups: Record<string, { weight: number; terms: string[] }>, minScore: number, stackGroups: string[], isDefault: boolean }`.
- `PUT /settings/scoring { groups?, minScore?, stackGroups? }` → same shape. `groups: null` resets to the default profile; an omitted key keeps the saved one. `stackGroups` must list keys of the effective groups (400 on `stackGroups` otherwise; duplicates dropped; `[]` disables the gate); when omitted, the saved list is kept minus keys missing from the effective groups. Validation: key `^[a-z0-9_]{1,40}$`, integer weight -100..100, up to 300 terms of 1..80 chars (blank terms are dropped). Rescores every job and recomputes `isHighlighted` immediately.
- `GET /settings/profile` → `{ dossier, pitchMaxChars, geminiModel, geminiConfigured, githubConfigured }`.
- `PUT /settings/profile { dossier?, pitchMaxChars? (300..5000), geminiModel? }` → same shape.
- `PUT /settings/secrets { geminiApiKey?, githubToken? }` → `{ geminiConfigured, githubConfigured }`. Empty string removes that secret.

## Monitoring rules

- Schedule: every day 09:00, 12:00, 15:00, 18:00 in `JOB_WATCHER_TIMEZONE` (default `America/Sao_Paulo`), weekends included, `coalesce`, `max_instances=1`, `misfire_grace_time=3600`.
- Worker start: runs still `running` become `failed` (`Interrupted before completion`); a `catch_up` run is queued when the latest `success|partial` run finished before the latest scheduled slot.
- Run start (no flag reset since v3): sources = active, not removed, not hidden, ordered like `GET /sources`; one progress row per source. Concurrency per kind: InHire 5, Gupy 2, GitHub 1.
- Every collector returns `(jobs, authoritative, warning)`. A failure raises `CollectionError` (source state `error`, `lastError` set, nothing archived). A `warning` means a partial failure: the jobs that arrived are applied, the source is marked `error` with its job count and the run ends `partial`.
  - InHire: `GET https://api.inhire.app/job-posts/public/pages/lean` with `X-Tenant: <first host label>`; timeout 15s (connect 10s), 3 attempts with backoff `1s * attempt` on timeout, transport error, 429, 500, 502, 503, 504. Career page = first path segment before `vagas`, else `default`; a non default page missing from the response raises. Always authoritative.
    Job pages: the lean listing has titles only, so `GET https://api.inhire.app/job-posts/public/pages/<jobId>` (same header, timeouts and retries, 5 concurrent requests shared by every InHire source in the run) fills `description` (HTML stripped), `location`, `published_at`, and appends the `workplaceType` label (Remoto, Híbrido, Presencial) to the location when the text does not state the work mode. Fetched for new keys, reopening jobs and up to 20 jobs per source still without a description. A page failure only logs a warning: the job keeps its title, the snapshot stays authoritative, and it is retried next run. `manage.py fetch_inhire_details [--limit N]` backfills every active InHire job without a description and rescores it.
  - Gupy: `GET <GUPY_API>?jobName=<term>&offset=<n>&limit=100` with browser headers; stops on the first short or empty page (never trusts `pagination.total`), 20 page lock, each page retried 3 times (waits 1s, 3s). First page failure raises; later failure is a warning. Never authoritative.
  - GitHub: `GET https://api.github.com/repos/<repo>/issues?state=open&sort=created&direction=desc&per_page=100&page=<n>`, up to 3 pages, `Authorization: Bearer <token>` when configured; pull requests and rules issues skipped, company read from the body template. Transient errors retried like InHire, other HTTP errors raise. Authoritative only when the last read page was short (or empty); a later page failure is a warning.
- Snapshot per source (one transaction): baseline when the source was never checked (inserted rows are not new). Upsert by key. For gupy and github, a job published more than 30 days ago is not inserted but still counts as seen. Jobs owned by a hidden `imported:vaggio` placeholder move to this source. Source archived jobs that reappear (and are not too old) reopen with `arrived_new=true` and `reopenedAt`, counting as new. Manually archived jobs stay archived but get their fields refreshed. Authoritative snapshots archive the source's active jobs missing from the response as `source / source_removed`. Source `lastCheckedAt=now`, `lastError=null`.
- Expiry, at the end of every run: active gupy and github jobs (including imported placeholders) without an application whose `published_at`, or `first_seen_at` when null, is older than 30 days become `source / expired` and are added to `jobsArchived`.
- Scoring (Vaggio engine): normalized text, word boundary matching, title hit counts double, one hit per group, tags only for positive groups, years of experience penalty (3+ years -12, 5+ years -25), seniority and work mode detection. Applied on insert and on every update, and to every job when the scoring settings are saved. `isHighlighted = score >= minScore AND (stackGroups is empty OR score_groups ∩ stackGroups ≠ ∅)`.
- Run end: `success` without errors or warnings, else `partial` with `"<source name>: <message>"` lines truncated to 4000; unexpected crash: `failed`.

## Vaggio import

`python manage.py import_vaggio <path to vaggio.sqlite3>` reads the Vaggio SQLite file directly. Idempotent. Prints the counts (`jobs_created`, `jobs_updated`, `jobs_skipped`, `jobs_archived`, `applications_created`, `applications_updated`, `interactions_created`, `pitches_imported`, `profile_imported`, `expired`).
- Jobs → Job with the keys above under the hidden placeholder source of their kind (manual jobs go to the manual source); unknown Vaggio sources are skipped. An existing key keeps its row and only fills empty `company_name`, `location`, `description`, `published_at`.
- `first_seen_at/last_seen_at = created_at/updated_at`, `arrived_new = false`. `discarded` → archived `manual / not_interested` with note `Imported from Vaggio`.
- Applications, interactions (deduplicated by application, date, title and creation time) and the latest pitch per job are copied with their dates. Profile `dossie` → `dossier`, `pitch_max_chars`, non empty `termos` → `scoring_profile`.
- Then every job is rescored with the current profile and the expiry rule runs once.

`python manage.py rescore` reapplies the saved profile to every job.

## Frontend rules (v3)

- Routes: `/` = Overview, `/jobs/highlighted` = Highlights, `/jobs` = All jobs, `/overview` redirects to `/`. Sidebar: Overview, Highlights, Applications, All jobs, Archive, Sources, Settings, Activity.
- No modal after "Open job": the last opened row shows an inline "Did you apply? Applied / Interested / Not now" prompt. Archive keeps its modal.
- Brazilian Portuguese is the default language; a stored choice in localStorage wins.

## Desktop integration

Backend services the Windows app calls directly:
- `watcher.services.notifications.new_highlights_for_run(run_id) -> list[Job]`: active, highlighted, without application, `arrived_new`, `arrived_at >= run.started_at`, `score desc`. Unknown or unstarted runs return `[]`.
- `watcher.services.notifications.overdue_applications() -> list[Application]`: active, `next_step_on` before today, `nextStepOn asc`.
- `watcher.services.preferences`: `notifications_enabled()`, `set_notifications_enabled(bool)`, `overdue_notice_last_on()`, `set_overdue_notice_last_on(date)`.
- `pipeline.services.register_detected_application(job_id) -> (Application, changed)`: no application → `applied` with `applied_on=today`; `interest` → `applied` (`applied_on` set when null); any other status unchanged. When changed, adds the timeline entry "Application sent through Job Watcher". An unknown job raises `Job.DoesNotExist`.

Desktop behavior: after each finished run, one tray notification when there are new highlights (if enabled); once per day, one for overdue applications. InHire jobs open in an app window (`window.pywebview.api.open_job(id)`), where a hook watches `POST /job-talents/public/<external_id>/talents` answered 2xx and reports it; the desktop records it with `register_detected_application`, dispatches `jobwatcher:application-detected` (`{ jobId, applicationId, changed }`) in the main window and notifies.
