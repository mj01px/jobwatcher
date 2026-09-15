"""Applications funnel, its timeline and AI cover letters (ported from Vaggio)."""

from __future__ import annotations

from datetime import date

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from pipeline.dates import local_today


class Application(models.Model):
    """Follow up of one job: where it is in the funnel and what to do next."""

    class Status(models.TextChoices):
        INTEREST = "interest"
        APPLIED = "applied"
        SCREENING = "screening"
        CHALLENGE = "challenge"
        INTERVIEW = "interview"
        OFFER = "offer"
        REJECTED = "rejected"
        WITHDRAWN = "withdrawn"

    job = models.OneToOneField("watcher.Job", on_delete=models.CASCADE, related_name="application")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.INTEREST, db_index=True
    )
    # 1 is the highest priority, 5 the lowest.
    priority = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    applied_on = models.DateField(null=True, blank=True)
    next_step = models.CharField(max_length=300, default="", blank=True)
    next_step_on = models.DateField(null=True, blank=True, db_index=True)
    # Recruiter, referral, whoever answered.
    contact = models.CharField(max_length=200, default="", blank=True)
    has_referral = models.BooleanField(default=False)
    notes = models.TextField(default="", blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "applications"
        indexes = [models.Index(fields=["status", "priority"], name="idx_applications_status")]

    def __str__(self) -> str:
        return f"Application {self.pk} ({self.status})"

    @property
    def is_active(self) -> bool:
        return self.status not in CLOSED_STATUSES

    def is_overdue(self, today: date | None = None) -> bool:
        """Next step date already passed while still in the active funnel."""
        if self.next_step_on is None or not self.is_active:
            return False
        return self.next_step_on < (today or local_today())


# Board columns, in order. Rejected and withdrawn are out of the active flow.
ACTIVE_STATUSES: tuple[str, ...] = (
    Application.Status.INTEREST,
    Application.Status.APPLIED,
    Application.Status.SCREENING,
    Application.Status.CHALLENGE,
    Application.Status.INTERVIEW,
    Application.Status.OFFER,
)
CLOSED_STATUSES: tuple[str, ...] = (Application.Status.REJECTED, Application.Status.WITHDRAWN)


class Interaction(models.Model):
    """Application timeline: every e-mail, test, interview and answer."""

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="interactions"
    )
    date = models.DateField(default=local_today)
    title = models.CharField(max_length=200)
    detail = models.TextField(default="", blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "interactions"
        indexes = [models.Index(fields=["application", "-date"], name="idx_interactions_app")]

    def __str__(self) -> str:
        return f"{self.date} {self.title}"


class Pitch(models.Model):
    """The cover letter generated for a job. Generating again replaces it."""

    job = models.ForeignKey("watcher.Job", on_delete=models.CASCADE, related_name="pitches")
    text = models.TextField()
    model = models.CharField(max_length=80)
    instruction = models.CharField(max_length=300, default="", blank=True)
    max_chars = models.PositiveIntegerField()
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    thinking_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "pitches"
        indexes = [models.Index(fields=["job", "-created_at"], name="idx_pitches_job")]

    def __str__(self) -> str:
        return f"Pitch {self.pk} for job {self.job_id}"
