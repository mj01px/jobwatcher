"""What the desktop app notifies about: fresh highlights and overdue follow ups."""

from __future__ import annotations

from django.db.models import F
from django.db.models.functions import Coalesce

from pipeline.dates import local_today
from pipeline.models import ACTIVE_STATUSES, Application
from watcher.models import CheckRun, Job


def new_highlights_for_run(run_id: int) -> list[Job]:
    """Highlighted jobs that arrived (or reopened) during a run, best score first.

    Only active jobs outside the funnel count. Unknown or never started runs
    return an empty list.
    """
    run = CheckRun.objects.filter(pk=run_id).only("started_at").first()
    if run is None or run.started_at is None:
        return []
    return list(
        Job.objects.select_related("source")
        .annotate(arrived_at=Coalesce(F("reopened_at"), F("first_seen_at")))
        .filter(
            status=Job.Status.ACTIVE,
            is_highlighted=True,
            arrived_new=True,
            application__isnull=True,
            arrived_at__gte=run.started_at,
        )
        .order_by("-score", "-arrived_at", "id")
    )


def overdue_applications() -> list[Application]:
    """Active applications whose next step date is before today (monitor timezone)."""
    return list(
        Application.objects.select_related("job__source")
        .filter(status__in=ACTIVE_STATUSES, next_step_on__lt=local_today())
        .order_by("next_step_on", "priority", "id")
    )
