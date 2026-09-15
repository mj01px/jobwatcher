"""Domain constants shared by the API, the monitor and the tests."""

from __future__ import annotations

WORKER_HEARTBEAT_KEY = "worker_heartbeat"

# Settings table keys.
SCORING_PROFILE_KEY = "scoring_profile"
HIGHLIGHT_MIN_SCORE_KEY = "highlight_min_score"
HIGHLIGHT_STACK_GROUPS_KEY = "highlight_stack_groups"
NOTIFICATIONS_ENABLED_KEY = "notifications_enabled"
OVERDUE_NOTICE_LAST_ON_KEY = "overdue_notice_last_on"
VISIT_LAST_PING_KEY = "visit_last_ping_at"
VISIT_STARTED_KEY = "visit_started_at"
VISIT_PREVIOUS_END_KEY = "visit_previous_end_at"
DOSSIER_KEY = "dossier"
PITCH_MAX_CHARS_KEY = "pitch_max_chars"
GEMINI_MODEL_KEY = "gemini_model"

# v2 used 20. Measured on real data: with the stack gate, 25 keeps developer
# jobs and drops the long tail of weak matches.
DEFAULT_HIGHLIGHT_MIN_SCORE = 25
# A job is highlighted only when one of these positive groups matched. Without
# the gate, finance and junior terms alone lifted non developer jobs (64% of
# the highlights on real data had no stack term at all).
DEFAULT_HIGHLIGHT_STACK_GROUPS: tuple[str, ...] = ("core", "adjacent")
# A visit ends after this long without a ping from a visible dashboard.
VISIT_GAP_MINUTES = 20
# Gupy does not document the limit of its "introduce yourself" field. 1200
# characters fits any plausible limit and is already longer than a recruiter
# reads carefully.
DEFAULT_PITCH_MAX_CHARS = 1200
PITCH_MAX_CHARS_MIN = 300
PITCH_MAX_CHARS_MAX = 5000

SCHEDULE_HOURS: tuple[int, ...] = (9, 12, 15, 18)
PAGE_SIZE = 20

# A running check with no heartbeat for this many seconds is treated as stalled.
STALE_RUN_SECONDS = 180
# The worker counts as online while its heartbeat is younger than this.
WORKER_ONLINE_SECONDS = 60
WORKER_POLL_SECONDS = 2
WORKER_HEARTBEAT_SECONDS = 10

ACTIVITY_HISTORY_LIMIT = 20
ACTIVITY_HISTORY_MAX = 100
RECENT_JOBS_LIMIT = 8
OVERDUE_APPLICATIONS_LIMIT = 5

INTERRUPTED_RUN_ERROR = "Interrupted before completion"

# A month easily covers the life of a real opening. Gupy barely returns older
# jobs; the cut mostly catches the eternal "talent pool" posts and GitHub issues
# from years ago that nobody closed.
MAX_JOB_AGE_DAYS = 30

# Slugs a user may pick when archiving manually. "source_removed" and "expired"
# are system only. "applied" is gone since v3: applying moves a job into the
# funnel, and the v1 "applied" archives were converted into applications.
ARCHIVE_REASON_SLUGS: frozenset[str] = frozenset(
    {
        "not_interested",
        "onsite",
        "hybrid",
        "remote",
        "requirements",
        "compensation",
        "closed",
        "other",
    }
)
LEGACY_APPLIED_REASON = "applied"
SOURCE_REMOVED_REASON = "source_removed"
EXPIRED_REASON = "expired"
ARCHIVE_NOTE_MAX_LENGTH = 500
SOURCE_ERROR_MAX_LENGTH = 500
RUN_ERROR_MAX_LENGTH = 4000

# Source kinds listed and collected, in display order.
COLLECTED_SOURCE_KINDS: tuple[str, ...] = ("inhire", "gupy", "github")
EXPIRING_SOURCE_KINDS: tuple[str, ...] = ("gupy", "github")

MANUAL_SOURCE_TARGET = "manual"
IMPORTED_SOURCE_TARGET = "imported:vaggio"
IMPORT_NOTE = "Imported from Vaggio"
