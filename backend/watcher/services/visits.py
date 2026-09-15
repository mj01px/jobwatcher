"""Visits to the dashboard, which decide whether a job is still new.

A job is new when it arrived as new after the previous visit ended. The
frontend pings while the dashboard is visible; a gap longer than
``VISIT_GAP_MINUTES`` starts a new visit and closes the previous one at its
last ping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.db import transaction
from django.db.models import BooleanField, Case, Q, QuerySet, Value, When
from django.utils import timezone

from watcher.constants import (
    VISIT_GAP_MINUTES,
    VISIT_LAST_PING_KEY,
    VISIT_PREVIOUS_END_KEY,
    VISIT_STARTED_KEY,
)
from watcher.models import Job, Setting
from watcher.services.preferences import get_setting, set_setting

IS_NEW_ANNOTATION = "is_new_now"


def _read_datetime(key: str) -> datetime | None:
    value = get_setting(key)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if timezone.is_aware(parsed) else parsed.replace(tzinfo=UTC)


def _write_datetime(key: str, value: datetime | None) -> None:
    if value is None:
        # The settings value column is not nullable: absent means "never".
        Setting.objects.filter(key=key).delete()
        return
    set_setting(key, value.isoformat())


def previous_visit_end() -> datetime | None:
    return _read_datetime(VISIT_PREVIOUS_END_KEY)


def register_visit(now: datetime | None = None) -> dict[str, datetime | None]:
    """Record a ping from a visible dashboard.

    Returns:
        ``{"visit_started_at", "previous_visit_ended_at"}`` after the ping.
    """
    current = now or timezone.now()
    with transaction.atomic():
        # Serialize concurrent pings (two windows) on the settings rows.
        list(
            Setting.objects.select_for_update().filter(
                key__in=[VISIT_LAST_PING_KEY, VISIT_STARTED_KEY, VISIT_PREVIOUS_END_KEY]
            )
        )
        started = _read_datetime(VISIT_STARTED_KEY)
        last_ping = _read_datetime(VISIT_LAST_PING_KEY)
        gap = timedelta(minutes=VISIT_GAP_MINUTES)
        if started is None or last_ping is None or current - last_ping > gap:
            _write_datetime(VISIT_PREVIOUS_END_KEY, last_ping)
            _write_datetime(VISIT_STARTED_KEY, current)
            started = current
        _write_datetime(VISIT_LAST_PING_KEY, current)
    return {"visit_started_at": started, "previous_visit_ended_at": previous_visit_end()}


def new_job_q(previous_end: datetime | None) -> Q:
    """Jobs that arrived as new after the previous visit ended."""
    arrived = Q(arrived_new=True)
    if previous_end is None:
        return arrived
    return arrived & (
        Q(reopened_at__gt=previous_end)
        | Q(reopened_at__isnull=True, first_seen_at__gt=previous_end)
    )


def annotate_is_new(queryset: QuerySet[Job], previous_end: datetime | None) -> QuerySet[Job]:
    """Add the computed ``is_new_now`` boolean used for ordering and serialization."""
    return queryset.annotate(
        **{
            IS_NEW_ANNOTATION: Case(
                When(new_job_q(previous_end), then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            )
        }
    )


def job_is_new(job: Job, previous_end: datetime | None) -> bool:
    """In memory version of ``new_job_q`` for a single loaded job."""
    if not job.arrived_new:
        return False
    if previous_end is None:
        return True
    arrived_at = job.reopened_at or job.first_seen_at
    return arrived_at > previous_end
