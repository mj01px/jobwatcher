"""Funnel rules that do not belong to a view (ported from Vaggio).

Entering the funnel and changing status write to the timeline, so the API, the
import and any future command follow the same rule.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from pipeline.dates import local_today
from pipeline.models import Application, Interaction
from watcher.models import Job

# Timeline titles written by the system. They are stored data shown as is, so
# they use the app's language (Brazilian Portuguese), like the Vaggio imports.
ENTERED_TITLE = "Entrou no funil"
DETECTED_TITLE = "Candidatura enviada pelo Job Watcher"
LEGACY_APPLIED_REASON = "applied"
STATUS_LABELS: dict[str, str] = {
    Application.Status.INTEREST: "Tenho interesse",
    Application.Status.APPLIED: "Aplicada",
    Application.Status.SCREENING: "Em triagem",
    Application.Status.CHALLENGE: "Teste ou desafio",
    Application.Status.INTERVIEW: "Entrevista",
    Application.Status.OFFER: "Proposta",
    Application.Status.REJECTED: "Rejeitada",
    Application.Status.WITHDRAWN: "Desisti",
}


def transition_title(previous_status: str, status: str) -> str:
    return f"{STATUS_LABELS[previous_status]} -> {STATUS_LABELS[status]}"


class ApplicationExistsError(RuntimeError):
    """The job is already in the funnel."""


@transaction.atomic
def enter_pipeline(job: Job, status: str = Application.Status.APPLIED) -> Application:
    """Put a job in the funnel.

    Raises:
        ApplicationExistsError: when the job already has an application.
    """
    if Application.objects.filter(job=job).exists():
        raise ApplicationExistsError(f"Job {job.pk} already has an application")
    now = timezone.now()
    application = Application.objects.create(
        job=job,
        status=status,
        applied_on=local_today() if status == Application.Status.APPLIED else None,
        created_at=now,
        updated_at=now,
    )
    Interaction.objects.create(
        application=application, title=ENTERED_TITLE, created_at=now, updated_at=now
    )
    if job.arrived_new:
        Job.objects.filter(pk=job.pk).update(arrived_new=False)
    return application


@transaction.atomic
def update_application(application: Application, values: dict[str, Any]) -> Application:
    """Apply validated field changes and the side effects of a status change.

    Stamps ``applied_on`` the first time the application reaches "applied" and
    records the transition in the timeline.
    """
    previous_status = application.status
    for field, value in values.items():
        setattr(application, field, value)
    changed_status = application.status != previous_status
    if application.status == Application.Status.APPLIED and application.applied_on is None:
        application.applied_on = local_today()
    now = timezone.now()
    application.updated_at = now
    application.save()
    if changed_status:
        Interaction.objects.create(
            application=application,
            title=transition_title(previous_status, application.status),
            created_at=now,
            updated_at=now,
        )
    return application


@transaction.atomic
def register_detected_application(job_id: int) -> tuple[Application, bool]:
    """Record an application the desktop app saw being sent (InHire apply form).

    No application yet: enter the funnel as applied. Still "interest": move to
    applied. Any later status stays untouched, the funnel already knows more.

    Returns:
        ``(application, changed)``.

    Raises:
        Job.DoesNotExist: when the job id is unknown.
    """
    job = Job.objects.select_for_update().get(pk=job_id)
    application = Application.objects.filter(job=job).first()
    if application is None:
        application = enter_pipeline(job, Application.Status.APPLIED)
    elif application.status == Application.Status.INTEREST:
        application = update_application(application, {"status": Application.Status.APPLIED})
    else:
        return application, False
    now = timezone.now()
    Interaction.objects.create(
        application=application, title=DETECTED_TITLE, created_at=now, updated_at=now
    )
    return application, True


def _local_date(moment: datetime, timezone_name: str) -> date:
    return moment.astimezone(ZoneInfo(timezone_name)).date()


def convert_applied_archives(
    job_model: Any = Job,
    application_model: Any = Application,
    interaction_model: Any = Interaction,
    timezone_name: str | None = None,
) -> int:
    """Turn v1 manual "applied" archives into applications (idempotent).

    In v1 the "Applied" button archived the job. v2 moved applying into the
    funnel but left those rows archived, so they were missing from it. Each one
    becomes an ``applied`` application dated by the archive, and the job goes
    back to active. Takes the model classes so the data migration can pass its
    historical models.

    Returns:
        How many jobs were converted.
    """
    zone = timezone_name or settings.JOB_WATCHER_TIMEZONE
    converted = 0
    candidates = job_model.objects.filter(
        archive_source="manual",
        archive_reason=LEGACY_APPLIED_REASON,
        application__isnull=True,
    ).order_by("id")
    with transaction.atomic():
        for job in candidates:
            moment = job.archived_at or timezone.now()
            application = application_model.objects.create(
                job_id=job.pk,
                status="applied",
                applied_on=_local_date(moment, zone),
                created_at=moment,
                updated_at=moment,
            )
            interaction_model.objects.create(
                application_id=application.pk,
                date=_local_date(moment, zone),
                title=ENTERED_TITLE,
                created_at=moment,
                updated_at=moment,
            )
            job_model.objects.filter(pk=job.pk).update(
                status="active",
                archive_source=None,
                archive_reason=None,
                archive_note=None,
                archived_at=None,
                arrived_new=False,
            )
            converted += 1
    return converted


# English system titles written before v3.1, frozen here so the rewrite never
# depends on the current labels.
_LEGACY_ENTERED_TITLE = "Entered the funnel"
_LEGACY_DETECTED_TITLE = "Application sent through Job Watcher"
_LEGACY_STATUS_LABELS: dict[str, str] = {
    "interest": "Interested",
    "applied": "Applied",
    "screening": "Screening",
    "challenge": "Challenge",
    "interview": "Interview",
    "offer": "Offer",
    "rejected": "Rejected",
    "withdrawn": "Withdrawn",
}
_PORTUGUESE_STATUS_LABELS: dict[str, str] = {
    "interest": "Tenho interesse",
    "applied": "Aplicada",
    "screening": "Em triagem",
    "challenge": "Teste ou desafio",
    "interview": "Entrevista",
    "offer": "Proposta",
    "rejected": "Rejeitada",
    "withdrawn": "Desisti",
}


def legacy_title_translations() -> dict[str, str]:
    """Exact English system titles mapped to their Portuguese versions."""
    translations = {
        _LEGACY_ENTERED_TITLE: "Entrou no funil",
        _LEGACY_DETECTED_TITLE: "Candidatura enviada pelo Job Watcher",
    }
    for before, old_from in _LEGACY_STATUS_LABELS.items():
        for after, old_to in _LEGACY_STATUS_LABELS.items():
            if before == after:
                continue
            new_title = f"{_PORTUGUESE_STATUS_LABELS[before]} -> {_PORTUGUESE_STATUS_LABELS[after]}"
            translations[f"{old_from} -> {old_to}"] = new_title
    return translations


def translate_legacy_titles(interaction_model: Any = Interaction) -> int:
    """Rewrite English system titles to Portuguese; user written titles stay.

    Only exact matches change, so a title someone typed is never touched.

    Returns:
        How many interactions were rewritten.
    """
    changed = 0
    for old_title, new_title in legacy_title_translations().items():
        changed += interaction_model.objects.filter(title=old_title).update(title=new_title)
    return changed
