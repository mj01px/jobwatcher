"""Check run execution: collect every active source and fold the snapshots in."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from asgiref.sync import sync_to_async
from django.db import close_old_connections, transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone

from watcher.constants import (
    COLLECTED_SOURCE_KINDS,
    EXPIRED_REASON,
    EXPIRING_SOURCE_KINDS,
    IMPORTED_SOURCE_TARGET,
    MAX_JOB_AGE_DAYS,
    RUN_ERROR_MAX_LENGTH,
    SOURCE_ERROR_MAX_LENGTH,
    SOURCE_REMOVED_REASON,
)
from watcher.models import CheckRun, CheckRunSource, Job, Source
from watcher.services.collection import (
    CollectedJob,
    CollectionError,
    CollectorResult,
    inhire_key,
)
from watcher.services.github import collect_github_repo
from watcher.services.gupy import collect_gupy_term
from watcher.services.inhire import (
    MAX_CONCURRENCY,
    REQUEST_TIMEOUT,
    apply_detail,
    collect_company,
    extract_tenant,
    fetch_job_details,
)
from watcher.services.runs import record_run_progress
from watcher.services.scoring import ScoringContext, apply_classification, load_scoring

logger = logging.getLogger(__name__)

# Concurrent collections per source kind. InHire answers fast; Gupy and GitHub
# are rate limited portals, so they go gently.
KIND_CONCURRENCY: dict[str, int] = {
    Source.Kind.INHIRE: MAX_CONCURRENCY,
    Source.Kind.GUPY: 2,
    Source.Kind.GITHUB: 1,
}
UPDATE_BATCH_SIZE = 500
# Existing InHire jobs still without a description are backfilled a few per
# source per run, so a first run after an upgrade does not take minutes.
# New and reopened jobs are always fetched. `manage.py fetch_inhire_details`
# backfills everything at once.
INHIRE_DETAIL_BACKFILL_PER_SOURCE = 20
SNAPSHOT_FIELDS = [
    "title",
    "url",
    "company_name",
    "location",
    "description",
    "published_at",
    "score",
    "score_tags",
    "score_groups",
    "seniority",
    "work_mode",
    "is_highlighted",
    "last_seen_at",
    "status",
    "archive_source",
    "archive_reason",
    "archive_note",
    "archived_at",
    "reopened_at",
    "arrived_new",
    "source",
]


def _max_age_cutoff(now: datetime) -> datetime:
    return now - timedelta(days=MAX_JOB_AGE_DAYS)


def _is_too_old(item: CollectedJob, cutoff: datetime) -> bool:
    # Without a date there is no way to tell, and dropping what is unknown is
    # worse than letting it in.
    published = item.published_at
    if published is None:
        return False
    if timezone.is_naive(published):
        published = published.replace(tzinfo=UTC)
    return published < cutoff


def _refresh_fields(job: Job, item: CollectedJob, now: datetime) -> None:
    job.title = item.title
    job.url = item.url
    if item.company_name:
        job.company_name = item.company_name
    if item.location:
        job.location = item.location
    if item.description:
        job.description = item.description
    if item.published_at is not None:
        job.published_at = item.published_at
    job.last_seen_at = now


def process_source_snapshot(
    source_id: int,
    jobs: list[CollectedJob],
    authoritative: bool,
    *,
    scoring: ScoringContext | None = None,
) -> tuple[int, int]:
    """Apply one source listing.

    Jobs are upserted by their global key, so a job found by two sources keeps
    the first one, except jobs still owned by a hidden Vaggio import placeholder:
    those move to the real source that returned them. Missing jobs are archived
    only for authoritative snapshots.

    Returns:
        ``(new_count, archived_count)`` for the source.

    Raises:
        Source.DoesNotExist: when the source id is unknown.
    """
    now = timezone.now()
    context = scoring or load_scoring()
    new_count = 0
    archived_count = 0

    with transaction.atomic():
        source = Source.objects.select_for_update().get(pk=source_id)
        is_baseline = source.last_checked_at is None
        expires = source.kind in EXPIRING_SOURCE_KINDS
        cutoff = _max_age_cutoff(now)
        unique_items = {item.key: item for item in jobs}
        existing_by_key = {job.key: job for job in Job.objects.filter(key__in=list(unique_items))}
        placeholder_ids = set(
            Source.objects.filter(is_hidden=True, target=IMPORTED_SOURCE_TARGET).values_list(
                "pk", flat=True
            )
        )
        to_update: list[Job] = []

        for key, item in unique_items.items():
            existing = existing_by_key.get(key)
            if existing is None:
                if expires and _is_too_old(item, cutoff):
                    continue
                arrived_new = not is_baseline
                new_count += int(arrived_new)
                job = Job(
                    source_id=source_id,
                    key=key,
                    external_id=item.external_id,
                    title=item.title,
                    url=item.url,
                    company_name=item.company_name,
                    location=item.location,
                    description=item.description,
                    published_at=item.published_at,
                    arrived_new=arrived_new,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                apply_classification(job, context)
                job.save()
                existing_by_key[key] = job
                continue

            _refresh_fields(existing, item, now)
            if existing.source_id in placeholder_ids:
                existing.source_id = source_id
            reopen = (
                existing.status == Job.Status.ARCHIVED
                and existing.archive_source == Job.ArchiveSource.SOURCE
                and not (expires and _is_too_old(item, cutoff))
            )
            if reopen:
                new_count += 1
                existing.status = Job.Status.ACTIVE
                existing.archive_source = None
                existing.archive_reason = None
                existing.archive_note = None
                existing.archived_at = None
                existing.reopened_at = now
                existing.arrived_new = True
            apply_classification(existing, context)
            to_update.append(existing)

        if to_update:
            Job.objects.bulk_update(to_update, SNAPSHOT_FIELDS, batch_size=UPDATE_BATCH_SIZE)

        if authoritative:
            missing = Job.objects.filter(source_id=source_id, status=Job.Status.ACTIVE).exclude(
                key__in=list(unique_items)
            )
            archived_count = missing.update(
                status=Job.Status.ARCHIVED,
                archive_source=Job.ArchiveSource.SOURCE,
                archive_reason=SOURCE_REMOVED_REASON,
                archive_note=None,
                archived_at=now,
                arrived_new=False,
            )

        Source.objects.filter(pk=source_id).update(
            last_checked_at=now, last_error=None, updated_at=now
        )

    return new_count, archived_count


def expire_old_jobs(now: datetime | None = None) -> int:
    """Archive Gupy and GitHub jobs older than the max age, except jobs in the funnel."""
    current = now or timezone.now()
    cutoff = _max_age_cutoff(current)
    stale = Job.objects.filter(
        status=Job.Status.ACTIVE,
        source__kind__in=EXPIRING_SOURCE_KINDS,
        application__isnull=True,
    ).filter(Q(published_at__lt=cutoff) | Q(published_at__isnull=True, first_seen_at__lt=cutoff))
    return Job.objects.filter(pk__in=list(stale.values_list("pk", flat=True))).update(
        status=Job.Status.ARCHIVED,
        archive_source=Job.ArchiveSource.SOURCE,
        archive_reason=EXPIRED_REASON,
        archive_note=None,
        archived_at=current,
        arrived_new=False,
    )


def ordered_collected_sources() -> list[dict[str, Any]]:
    kind_order = Case(
        *[When(kind=kind, then=Value(index)) for index, kind in enumerate(COLLECTED_SOURCE_KINDS)],
        default=Value(len(COLLECTED_SOURCE_KINDS)),
        output_field=IntegerField(),
    )
    rows = list(
        Source.objects.filter(
            is_active=True, is_removed=False, is_hidden=False, kind__in=COLLECTED_SOURCE_KINDS
        )
        .annotate(kind_order=kind_order)
        .values("id", "name", "kind", "target", "kind_order")
    )
    rows.sort(key=lambda row: (row["kind_order"], row["name"].casefold(), row["id"]))
    return rows


def _start_run(run_id: int) -> list[dict[str, Any]]:
    """Snapshot the source list and create progress rows.

    New flags are no longer reset here: whether a job is still new depends on
    the user's last visit (see services.visits).
    """
    close_old_connections()
    now = timezone.now()
    with transaction.atomic():
        sources = ordered_collected_sources()
        run = CheckRun.objects.select_for_update().get(pk=run_id)
        run.status = CheckRun.Status.RUNNING
        run.started_at = run.started_at or now
        run.heartbeat_at = now
        run.sources_total = len(sources)
        run.save(update_fields=["status", "started_at", "heartbeat_at", "sources_total"])
        CheckRunSource.objects.bulk_create(
            CheckRunSource(
                run_id=run_id,
                source_id=source["id"],
                kind=source["kind"],
                name=source["name"],
                position=index,
                updated_at=now,
            )
            for index, source in enumerate(sources)
        )
    return sources


def _mark_source(
    run_id: int,
    source_id: int,
    state: str,
    *,
    jobs: int | None = None,
    error: str | None = None,
) -> None:
    values: dict[str, Any] = {"state": state, "updated_at": timezone.now()}
    if jobs is not None:
        values["jobs"] = jobs
    if error is not None:
        values["error"] = error
    CheckRunSource.objects.filter(run_id=run_id, source_id=source_id).update(**values)


def _record_source_error(run_id: int, source_id: int, message: str) -> None:
    now = timezone.now()
    trimmed = message[:SOURCE_ERROR_MAX_LENGTH]
    Source.objects.filter(pk=source_id).update(last_error=trimmed, updated_at=now)
    _mark_source(run_id, source_id, CheckRunSource.State.ERROR, error=trimmed)
    record_run_progress(run_id)


def _record_source_success(
    run_id: int, source_id: int, found: int, new_count: int, archived_count: int
) -> None:
    _mark_source(run_id, source_id, CheckRunSource.State.DONE, jobs=found)
    record_run_progress(run_id, checked=1, found=found, new=new_count, archived=archived_count)


def _record_source_partial(
    run_id: int, source_id: int, found: int, new_count: int, archived_count: int, warning: str
) -> None:
    """The snapshot was applied, but part of the source did not answer."""
    trimmed = warning[:SOURCE_ERROR_MAX_LENGTH]
    Source.objects.filter(pk=source_id).update(last_error=trimmed, updated_at=timezone.now())
    _mark_source(run_id, source_id, CheckRunSource.State.ERROR, jobs=found, error=trimmed)
    record_run_progress(run_id, checked=1, found=found, new=new_count, archived=archived_count)


def _expire_for_run(run_id: int) -> int:
    expired = expire_old_jobs()
    if expired:
        record_run_progress(run_id, archived=expired)
    return expired


def _finish_run(run_id: int, status: str, error: str | None) -> None:
    now = timezone.now()
    CheckRun.objects.filter(pk=run_id).update(
        finished_at=now, heartbeat_at=now, status=status, error=error
    )


def _fail_run(run_id: int, error: str) -> None:
    CheckRun.objects.filter(pk=run_id).update(
        finished_at=timezone.now(),
        status=CheckRun.Status.FAILED,
        error=error[:RUN_ERROR_MAX_LENGTH],
    )


# All ORM work happens on one dedicated thread so SQLite sees a single writer
# from this process and Django never runs queries inside the event loop.
_start_run_async = sync_to_async(_start_run, thread_sensitive=True)
_mark_source_async = sync_to_async(_mark_source, thread_sensitive=True)
_record_source_error_async = sync_to_async(_record_source_error, thread_sensitive=True)
_record_source_success_async = sync_to_async(_record_source_success, thread_sensitive=True)
_record_source_partial_async = sync_to_async(_record_source_partial, thread_sensitive=True)
_process_snapshot_async = sync_to_async(process_source_snapshot, thread_sensitive=True)
_expire_for_run_async = sync_to_async(_expire_for_run, thread_sensitive=True)
_finish_run_async = sync_to_async(_finish_run, thread_sensitive=True)
_fail_run_async = sync_to_async(_fail_run, thread_sensitive=True)
_close_connections_async = sync_to_async(close_old_connections, thread_sensitive=True)


def inhire_keys_needing_details(
    keys: list[str], backfill_limit: int = INHIRE_DETAIL_BACKFILL_PER_SOURCE
) -> set[str]:
    """Keys whose public job page should be fetched: new jobs, source archived
    jobs about to reopen, and up to ``backfill_limit`` jobs without a description."""
    existing = {
        row["key"]: row
        for row in Job.objects.filter(key__in=keys).values(
            "key", "description", "status", "archive_source"
        )
    }
    wanted: set[str] = set()
    backfill: list[str] = []
    for key in keys:
        row = existing.get(key)
        reopening = row is not None and (
            row["status"] == Job.Status.ARCHIVED
            and row["archive_source"] == Job.ArchiveSource.SOURCE
        )
        if row is None or reopening:
            wanted.add(key)
        elif not row["description"]:
            backfill.append(key)
    wanted.update(backfill[:backfill_limit])
    return wanted


_inhire_keys_needing_details_async = sync_to_async(
    inhire_keys_needing_details, thread_sensitive=True
)


async def with_inhire_details(
    client: httpx.AsyncClient,
    source: dict[str, Any],
    jobs: list[CollectedJob],
    semaphore: asyncio.Semaphore | None = None,
) -> list[CollectedJob]:
    """Add descriptions from the public job pages. Never raises: a job whose page
    fails keeps its title only, and the listing stays authoritative."""
    if not jobs:
        return jobs
    try:
        wanted = await _inhire_keys_needing_details_async([job.key for job in jobs])
        if not wanted:
            return jobs
        tenant = extract_tenant(source["target"])
        ids = [job.external_id for job in jobs if job.key in wanted]
        details = await fetch_job_details(client, tenant, ids, semaphore=semaphore)
    except Exception as error:  # noqa: BLE001 - details are optional enrichment
        logger.warning("InHire details skipped for %s: %s", source["name"], error)
        return jobs
    return [
        apply_detail(job, details[job.external_id]) if job.external_id in details else job
        for job in jobs
    ]


async def collect_source(
    client: httpx.AsyncClient,
    source: dict[str, Any],
    detail_semaphore: asyncio.Semaphore | None = None,
) -> CollectorResult:
    """Dispatch one source to its collector.

    Raises:
        CollectionError: when the source cannot be collected or trusted.
    """
    kind = source["kind"]
    if kind == Source.Kind.INHIRE:
        scraped = await collect_company(client, source["target"])
        jobs = [
            CollectedJob(
                key=inhire_key(job.external_id),
                external_id=job.external_id,
                title=job.title,
                url=job.url,
                company_name=source["name"],
            )
            for job in scraped
        ]
        jobs = await with_inhire_details(client, source, jobs, detail_semaphore)
        return CollectorResult(jobs=jobs, authoritative=True)
    if kind == Source.Kind.GUPY:
        return await asyncio.to_thread(collect_gupy_term, source["target"])
    if kind == Source.Kind.GITHUB:
        return await asyncio.to_thread(collect_github_repo, source["target"])
    raise CollectionError(f"Unsupported source kind {kind!r}")


async def execute_run(run_id: int) -> None:
    """Execute a claimed check run end to end. Never raises."""
    try:
        sources = await _start_run_async(run_id)
        errors: list[str] = []

        limits = httpx.Limits(
            max_connections=MAX_CONCURRENCY, max_keepalive_connections=MAX_CONCURRENCY
        )
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT, limits=limits, follow_redirects=True
        ) as client:
            semaphores = {
                kind: asyncio.Semaphore(limit) for kind, limit in KIND_CONCURRENCY.items()
            }
            fallback = asyncio.Semaphore(1)
            # One pool of job page requests for every InHire source in the run.
            detail_semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

            async def collect(source: dict[str, Any]) -> None:
                async with semaphores.get(source["kind"], fallback):
                    await _mark_source_async(run_id, source["id"], CheckRunSource.State.COLLECTING)
                    try:
                        result = await collect_source(client, source, detail_semaphore)
                        new_count, archived_count = await _process_snapshot_async(
                            source["id"], result.jobs, result.authoritative
                        )
                    except Exception as error:  # noqa: BLE001 - one source must not stop the run
                        logger.warning("Failed to collect %s: %s", source["name"], error)
                        errors.append(f"{source['name']}: {error}")
                        await _record_source_error_async(run_id, source["id"], str(error))
                        return
                    if result.warning:
                        errors.append(f"{source['name']}: {result.warning}")
                        await _record_source_partial_async(
                            run_id,
                            source["id"],
                            len(result.jobs),
                            new_count,
                            archived_count,
                            result.warning,
                        )
                        return
                    await _record_source_success_async(
                        run_id, source["id"], len(result.jobs), new_count, archived_count
                    )

            await asyncio.gather(*(collect(source) for source in sources))

        await _expire_for_run_async(run_id)
        status = CheckRun.Status.PARTIAL if errors else CheckRun.Status.SUCCESS
        error_text = "\n".join(errors)[:RUN_ERROR_MAX_LENGTH] or None
        await _finish_run_async(run_id, status, error_text)
    except Exception as error:
        logger.exception("Monitoring run %s failed", run_id)
        await _fail_run_async(run_id, str(error))
    finally:
        await _close_connections_async()


def run_check_now(run_id: int) -> None:
    """Synchronous entry point used by the worker loop."""
    asyncio.run(execute_run(run_id))
