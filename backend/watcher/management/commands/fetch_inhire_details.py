"""Backfill descriptions of active InHire jobs from their public job pages.

    python manage.py fetch_inhire_details
    python manage.py fetch_inhire_details --limit 100

The lean listing used by every check has titles only. Check runs backfill a few
jobs per source; this command does all of them at once and rescores them.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import httpx
from django.core.management.base import BaseCommand, CommandParser

from watcher.models import Job, Source
from watcher.services.collection import CollectionError
from watcher.services.inhire import (
    MAX_CONCURRENCY,
    REQUEST_TIMEOUT,
    JobDetail,
    detail_fields,
    extract_tenant,
    fetch_job_details,
)
from watcher.services.scoring import apply_classification, load_scoring

UPDATE_BATCH_SIZE = 200
PROGRESS_EVERY = 50
UPDATED_FIELDS = [
    "description",
    "location",
    "published_at",
    "score",
    "score_tags",
    "score_groups",
    "seniority",
    "work_mode",
    "is_highlighted",
]


@dataclass
class BackfillResult:
    requested: int = 0
    fetched: int = 0
    failed: int = 0
    skipped: int = 0
    highlighted_before: int = 0
    highlighted_after: int = 0
    newly_highlighted: list[str] = field(default_factory=list)


def pending_jobs(limit: int | None) -> list[Job]:
    queryset = (
        Job.objects.filter(
            source__kind=Source.Kind.INHIRE, status=Job.Status.ACTIVE, description=""
        )
        .select_related("source")
        .order_by("-first_seen_at", "id")
    )
    return list(queryset[:limit] if limit else queryset)


async def _fetch_all(
    by_tenant: dict[str, list[str]],
    concurrency: int,
    on_done: Any,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[tuple[str, str], JobDetail]:
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    semaphore = asyncio.Semaphore(concurrency)
    results: dict[tuple[str, str], JobDetail] = {}
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT, limits=limits, follow_redirects=True, transport=transport
    ) as client:

        async def tenant_pages(tenant: str, ids: list[str]) -> None:
            details = await fetch_job_details(
                client, tenant, ids, semaphore=semaphore, on_done=on_done
            )
            for job_id, detail in details.items():
                results[(tenant, job_id)] = detail

        await asyncio.gather(*(tenant_pages(tenant, ids) for tenant, ids in by_tenant.items()))
    return results


def backfill(
    limit: int | None = None,
    concurrency: int = MAX_CONCURRENCY,
    progress: Any = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BackfillResult:
    """Fetch, store and rescore descriptions for active InHire jobs without one."""
    result = BackfillResult()
    jobs = pending_jobs(limit)
    by_tenant: dict[str, list[str]] = defaultdict(list)
    tenant_of: dict[int, str] = {}
    for job in jobs:
        try:
            tenant = extract_tenant(job.source.target)
        except CollectionError:
            result.skipped += 1
            continue
        tenant_of[job.pk] = tenant
        by_tenant[tenant].append(job.external_id)
    result.requested = sum(len(ids) for ids in by_tenant.values())

    done = {"count": 0}

    def on_done(_job_id: str, succeeded: bool) -> None:
        done["count"] += 1
        if not succeeded:
            result.failed += 1
        if progress is not None and done["count"] % PROGRESS_EVERY == 0:
            progress(done["count"], result.requested, result.failed)

    details = (
        asyncio.run(_fetch_all(by_tenant, concurrency, on_done, transport)) if by_tenant else {}
    )

    context = load_scoring()
    batch: list[Job] = []
    for job in jobs:
        tenant = tenant_of.get(job.pk)
        detail = details.get((tenant, job.external_id)) if tenant else None
        if detail is None:
            continue
        result.fetched += 1
        was_highlighted = job.is_highlighted
        result.highlighted_before += int(was_highlighted)
        fields = detail_fields(job.title, detail)
        job.description = fields["description"]
        job.location = fields["location"] or job.location
        job.published_at = fields["published_at"] or job.published_at
        apply_classification(job, context)
        result.highlighted_after += int(job.is_highlighted)
        if job.is_highlighted and not was_highlighted:
            result.newly_highlighted.append(f"{job.score} {job.title} ({job.company_name})")
        batch.append(job)
        if len(batch) >= UPDATE_BATCH_SIZE:
            Job.objects.bulk_update(batch, UPDATED_FIELDS)
            batch = []
    if batch:
        Job.objects.bulk_update(batch, UPDATED_FIELDS)
    return result


class Command(BaseCommand):
    help = "Fetch descriptions for active InHire jobs that have none, then rescore them."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=None, help="Only the N most recent jobs.")
        parser.add_argument(
            "--concurrency",
            type=int,
            default=MAX_CONCURRENCY,
            help=f"Parallel job page requests (default {MAX_CONCURRENCY}).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        started = time.monotonic()
        concurrency = max(1, min(int(options["concurrency"]), 10))

        def progress(done: int, total: int, failed: int) -> None:
            self.stdout.write(f"  {done}/{total} job pages ({failed} failed)")

        result = backfill(options["limit"], concurrency, progress)
        elapsed = time.monotonic() - started
        self.stdout.write(
            f"requested: {result.requested}\n"
            f"fetched: {result.fetched}\n"
            f"failed: {result.failed}\n"
            f"skipped (no tenant): {result.skipped}\n"
            f"highlighted before: {result.highlighted_before}\n"
            f"highlighted after: {result.highlighted_after}\n"
            f"seconds: {elapsed:.1f}"
        )
        for line in result.newly_highlighted[:10]:
            self.stdout.write(f"  + {line}")
