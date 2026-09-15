"""Persistence model for sources, jobs, check runs and settings."""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class Source(models.Model):
    """Something the monitor collects from: an InHire career page, a Gupy search or a repo."""

    class Kind(models.TextChoices):
        INHIRE = "inhire"
        GUPY = "gupy"
        GITHUB = "github"
        MANUAL = "manual"

    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.INHIRE)
    name = models.CharField(max_length=255)
    # InHire career page URL, Gupy search term or GitHub "owner/repo".
    target = models.CharField(max_length=500)
    is_active = models.BooleanField(default=True)
    is_removed = models.BooleanField(default=False)
    # The manual source and the Vaggio import placeholders: never listed nor collected.
    is_hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "sources"
        constraints = [
            models.UniqueConstraint(fields=["kind", "target"], name="uniq_sources_kind_target")
        ]
        indexes = [models.Index(fields=["is_active", "is_removed"], name="idx_sources_active")]

    def __str__(self) -> str:
        return f"{self.kind}: {self.name}"


class Job(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active"
        ARCHIVED = "archived"

    class ArchiveSource(models.TextChoices):
        MANUAL = "manual"
        SOURCE = "source"

    class WorkMode(models.TextChoices):
        REMOTE = "remote"
        HYBRID = "hybrid"
        ONSITE = "onsite"
        UNKNOWN = "unknown"

    class Seniority(models.TextChoices):
        INTERNSHIP = "internship"
        JUNIOR = "junior"
        MID = "mid"
        SENIOR = "senior"
        UNKNOWN = "unknown"

    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="jobs")
    external_id = models.CharField(max_length=1000)
    # Global dedup key: "<kind>:<external id>", "manual:<sha256 of url>".
    key = models.CharField(max_length=1100, unique=True)
    title = models.CharField(max_length=500)
    url = models.CharField(max_length=1000)
    company_name = models.CharField(max_length=255, default="", blank=True)
    location = models.CharField(max_length=255, default="", blank=True)
    work_mode = models.CharField(max_length=16, choices=WorkMode.choices, default=WorkMode.UNKNOWN)
    seniority = models.CharField(
        max_length=16, choices=Seniority.choices, default=Seniority.UNKNOWN
    )
    description = models.TextField(default="", blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    score = models.IntegerField(default=0)
    score_tags = models.JSONField(default=list, blank=True)
    # Positive scoring groups that matched; the highlight requires a stack group.
    score_groups = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    archive_source = models.CharField(
        max_length=16, choices=ArchiveSource.choices, null=True, blank=True
    )
    archive_reason = models.CharField(max_length=32, null=True, blank=True)
    archive_note = models.TextField(null=True, blank=True)
    is_highlighted = models.BooleanField(default=False)
    # Arrived as new (inserted outside a baseline, or reopened). Never reset by a
    # run: whether it is still new depends on the last visit, see services.visits.
    arrived_new = models.BooleanField(default=False)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    archived_at = models.DateTimeField(null=True, blank=True)
    reopened_at = models.DateTimeField(null=True, blank=True)
    first_visited_at = models.DateTimeField(null=True, blank=True)
    last_visited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "jobs"
        indexes = [
            models.Index(fields=["status", "-last_seen_at"], name="idx_jobs_status_seen"),
            models.Index(fields=["is_highlighted", "status"], name="idx_jobs_highlighted_status"),
            models.Index(fields=["source", "status"], name="idx_jobs_source_status"),
            models.Index(fields=["status", "-first_seen_at"], name="idx_jobs_listing_order"),
            models.Index(fields=["status", "-score"], name="idx_jobs_status_score"),
            models.Index(fields=["status", "published_at"], name="idx_jobs_status_published"),
        ]

    def __str__(self) -> str:
        return self.title


class CheckRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        SUCCESS = "success"
        PARTIAL = "partial"
        FAILED = "failed"

    class Trigger(models.TextChoices):
        SCHEDULED = "scheduled"
        CATCH_UP = "catch_up"
        MANUAL = "manual"

    trigger = models.CharField(max_length=16, choices=Trigger.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    requested_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    sources_total = models.PositiveIntegerField(default=0)
    sources_checked = models.PositiveIntegerField(default=0)
    jobs_found = models.PositiveIntegerField(default=0)
    jobs_new = models.PositiveIntegerField(default=0)
    jobs_archived = models.PositiveIntegerField(default=0)
    error = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "check_runs"
        indexes = [
            models.Index(fields=["status", "-finished_at"], name="idx_runs_status_finished"),
            models.Index(fields=["-requested_at"], name="idx_runs_requested"),
        ]

    def __str__(self) -> str:
        return f"CheckRun {self.pk} ({self.status})"


class CheckRunSource(models.Model):
    """Live per source progress of a run, readable from the web process."""

    class State(models.TextChoices):
        PENDING = "pending"
        COLLECTING = "collecting"
        DONE = "done"
        ERROR = "error"

    run = models.ForeignKey(CheckRun, on_delete=models.CASCADE, related_name="source_states")
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="run_states")
    kind = models.CharField(max_length=16, default=Source.Kind.INHIRE)
    name = models.CharField(max_length=255)
    position = models.PositiveIntegerField(default=0)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    jobs = models.PositiveIntegerField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "check_run_sources"
        constraints = [models.UniqueConstraint(fields=["run", "source"], name="uniq_run_source")]
        indexes = [models.Index(fields=["run", "position"], name="idx_run_sources_position")]

    def __str__(self) -> str:
        return f"{self.name}: {self.state}"


class Setting(models.Model):
    key = models.CharField(max_length=100, primary_key=True)
    value = models.JSONField()
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "settings"

    def __str__(self) -> str:
        return self.key
