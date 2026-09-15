"""Check run queue, progress bookkeeping and worker liveness.

The web process only enqueues runs and reads their state; the worker claims
and executes them. Everything goes through the database so both processes
see the same picture.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from watcher.constants import (
    INTERRUPTED_RUN_ERROR,
    STALE_RUN_SECONDS,
    WORKER_HEARTBEAT_KEY,
    WORKER_ONLINE_SECONDS,
)
from watcher.models import CheckRun, CheckRunSource, Setting

PENDING_STATUSES = (CheckRun.Status.QUEUED, CheckRun.Status.RUNNING)


def enqueue_run(trigger: str) -> tuple[CheckRun, bool]:
    """Queue a check run unless one is already queued or running.

    Returns:
        The queued (or already active) run and whether it was created.
    """
    with transaction.atomic():
        active = (
            CheckRun.objects.filter(status__in=PENDING_STATUSES)
            .order_by("-requested_at", "-id")
            .first()
        )
        if active is not None:
            return active, False
        return CheckRun.objects.create(trigger=trigger, status=CheckRun.Status.QUEUED), True


def claim_next_queued_run() -> CheckRun | None:
    """Atomically move the oldest queued run to running."""
    with transaction.atomic():
        if CheckRun.objects.filter(status=CheckRun.Status.RUNNING).exists():
            return None
        run = (
            CheckRun.objects.filter(status=CheckRun.Status.QUEUED)
            .order_by("requested_at", "id")
            .first()
        )
        if run is None:
            return None
        now = timezone.now()
        run.status = CheckRun.Status.RUNNING
        run.started_at = now
        run.heartbeat_at = now
        run.save(update_fields=["status", "started_at", "heartbeat_at"])
        return run


def mark_interrupted_runs() -> int:
    """Close out any check run still marked running from a previous process.

    A single worker owns execution, so when it starts no check can genuinely
    be in progress. Any leftover running row means the process died mid run;
    mark it failed so the activity page never shows a phantom run.
    """
    now = timezone.now()
    with transaction.atomic():
        running = CheckRun.objects.filter(status=CheckRun.Status.RUNNING)
        running.filter(error__isnull=True).update(error=INTERRUPTED_RUN_ERROR)
        return running.update(status=CheckRun.Status.FAILED, finished_at=now)


def record_run_progress(
    run_id: int,
    *,
    checked: int = 0,
    found: int = 0,
    new: int = 0,
    archived: int = 0,
) -> None:
    """Fold one source result into its check run and refresh the heartbeat."""
    CheckRun.objects.filter(pk=run_id).update(
        heartbeat_at=timezone.now(),
        sources_checked=F("sources_checked") + checked,
        jobs_found=F("jobs_found") + found,
        jobs_new=F("jobs_new") + new,
        jobs_archived=F("jobs_archived") + archived,
    )


def run_looks_stalled(run: CheckRun | None, now: datetime | None = None) -> bool:
    if run is None or run.status != CheckRun.Status.RUNNING:
        return False
    stamp = run.heartbeat_at or run.started_at
    if stamp is None:
        return False
    current = now or timezone.now()
    return (current - stamp).total_seconds() > STALE_RUN_SECONDS


def run_duration_seconds(run: CheckRun) -> float | None:
    if run.finished_at is None or run.started_at is None:
        return None
    return round((run.finished_at - run.started_at).total_seconds(), 1)


def build_progress(run: CheckRun) -> dict[str, Any]:
    """Live progress snapshot of a run, shaped like the API ``RunProgress``."""
    states = list(
        CheckRunSource.objects.filter(run=run)
        .order_by("position", "id")
        .values("source_id", "kind", "name", "state", "jobs", "updated_at")
    )
    counts = {state: 0 for state in CheckRunSource.State.values}
    updated_at = run.heartbeat_at or run.started_at or run.requested_at
    for entry in states:
        counts[entry["state"]] += 1
        if entry["updated_at"] and entry["updated_at"] > updated_at:
            updated_at = entry["updated_at"]
    return {
        "runId": run.pk,
        "startedAt": run.started_at,
        "updatedAt": updated_at,
        "total": len(states),
        "settled": counts[CheckRunSource.State.DONE] + counts[CheckRunSource.State.ERROR],
        "counts": counts,
        "sources": [
            {
                "sourceId": entry["source_id"],
                "kind": entry["kind"],
                "name": entry["name"],
                "state": entry["state"],
                "jobs": entry["jobs"],
            }
            for entry in states
        ],
    }


def write_worker_heartbeat() -> None:
    now = timezone.now()
    Setting.objects.update_or_create(
        key=WORKER_HEARTBEAT_KEY, defaults={"value": now.isoformat(), "updated_at": now}
    )


def worker_is_online(now: datetime | None = None) -> bool:
    row = Setting.objects.filter(key=WORKER_HEARTBEAT_KEY).first()
    if row is None or not isinstance(row.value, str):
        return False
    try:
        beat = datetime.fromisoformat(row.value)
    except ValueError:
        return False
    current = now or timezone.now()
    return current - beat < timedelta(seconds=WORKER_ONLINE_SECONDS)
