"""InHire public job pages: descriptions for jobs the lean listing only titles."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from io import StringIO
from typing import Any

import httpx
import pytest
from django.core.management import call_command
from django.utils import timezone

from tests.conftest import MakeJob
from watcher.management.commands import fetch_inhire_details as backfill_command
from watcher.models import CheckRun, Job, Source
from watcher.services import inhire, monitor
from watcher.services.collection import CollectedJob
from watcher.services.inhire import (
    JobDetail,
    ScrapedJob,
    apply_detail,
    detail_fields,
    fetch_job_details,
    parse_job_detail,
)
from watcher.services.monitor import (
    execute_run,
    inhire_keys_needing_details,
    process_source_snapshot,
    with_inhire_details,
)

PYTHON_TITLE = "Pessoa Desenvolvedora Python"
JUNIOR_DJANGO = "<p>Vaga <strong>j&uacute;nior</strong> para trabalhar com Django e SQL.</p>"


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inhire, "RETRY_BACKOFF_SECONDS", 0.0)


@pytest.fixture
def quiet_logs() -> Iterator[None]:
    names = ("watcher.services.inhire", "watcher.services.monitor")
    loggers = [logging.getLogger(name) for name in names]
    previous = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.CRITICAL)
    yield
    for logger, level in zip(loggers, previous, strict=True):
        logger.setLevel(level)


def _page(job_id: str, **fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "jobId": job_id,
        "displayName": "Role",
        "description": JUNIOR_DJANGO,
        "location": "São Paulo, SP, BR",
        "workplaceType": "Hybrid",
        "publishedAt": "2026-09-10T16:48:09.321Z",
        "lastPublishedAt": "2026-09-11T10:00:00.000Z",
        "status": "published",
    }
    payload.update(fields)
    return payload


def _pages_transport(pages: dict[str, Any], calls: list[str] | None = None) -> httpx.MockTransport:
    """200 with the page for known ids, the given status code for ints, 404 otherwise."""

    def handler(request: httpx.Request) -> httpx.Response:
        job_id = request.url.path.rsplit("/", 1)[-1]
        if calls is not None:
            calls.append(job_id)
        assert request.headers["X-Tenant"]
        page = pages.get(job_id)
        if isinstance(page, int):
            return httpx.Response(page)
        if page is None:
            return httpx.Response(404)
        return httpx.Response(200, json=page)

    return httpx.MockTransport(handler)


class TestParseJobDetail:
    def test_description_html_is_cleaned(self) -> None:
        detail = parse_job_detail(_page("a"))
        assert detail.description == "Vaga júnior para trabalhar com Django e SQL."
        assert detail.location == "São Paulo, SP, BR"
        assert detail.published_at == datetime(2026, 9, 10, 16, 48, 9, 321000, tzinfo=UTC)
        assert detail.workplace == "Híbrido"

    def test_last_published_at_is_the_fallback(self) -> None:
        detail = parse_job_detail(_page("a", publishedAt=None))
        assert detail.published_at == datetime(2026, 9, 11, 10, 0, tzinfo=UTC)

    def test_location_object_and_unknown_values(self) -> None:
        detail = parse_job_detail(
            _page(
                "a", location={"city": "Recife", "state": "PE", "country": "BR"}, workplaceType="X"
            )
        )
        assert detail.location == "Recife, PE, BR"
        assert detail.workplace == ""
        assert parse_job_detail(_page("a", location=None, description=None)).description == ""

    @pytest.mark.parametrize(
        ("raw", "label"), [("Remote", "Remoto"), ("On-site", "Presencial"), ("hybrid", "Híbrido")]
    )
    def test_workplace_labels(self, raw: str, label: str) -> None:
        assert parse_job_detail(_page("a", workplaceType=raw)).workplace == label


class TestDetailFields:
    def test_workplace_goes_to_location_when_text_is_silent(self) -> None:
        detail = JobDetail("Trabalho com Django.", "Recife, PE, BR", None, "Remoto")
        assert detail_fields("Dev Python", detail)["location"] == "Recife, PE, BR · Remoto"

    def test_text_that_states_the_work_mode_wins(self) -> None:
        detail = JobDetail("Modelo presencial em Recife.", "Recife, PE, BR", None, "Remoto")
        assert detail_fields("Dev Python", detail)["location"] == "Recife, PE, BR"

    def test_apply_detail_fills_the_collected_job(self) -> None:
        job = CollectedJob(key="inhire:a", external_id="a", title=PYTHON_TITLE, url="u")
        enriched = apply_detail(job, parse_job_detail(_page("a")))
        assert enriched.description.startswith("Vaga júnior")
        assert enriched.published_at is not None
        assert enriched.title == PYTHON_TITLE


@pytest.mark.usefixtures("quiet_logs")
class TestFetchJobDetails:
    def test_failed_pages_are_left_out(self) -> None:
        calls: list[str] = []
        transport = _pages_transport({"ok": _page("ok"), "broken": 503}, calls)
        finished: list[tuple[str, bool]] = []

        async def scenario() -> dict[str, JobDetail]:
            async with httpx.AsyncClient(transport=transport) as client:
                return await fetch_job_details(
                    client,
                    "acme",
                    ["ok", "broken", "missing", "ok"],
                    on_done=lambda job_id, ok: finished.append((job_id, ok)),
                )

        details = asyncio.run(scenario())
        assert set(details) == {"ok"}
        # 503 is retried up to the attempt limit, 404 is not retried, duplicates collapse.
        assert calls.count("broken") == inhire.MAX_ATTEMPTS
        assert calls.count("missing") == 1
        assert calls.count("ok") == 1
        assert sorted(finished) == [("broken", False), ("missing", False), ("ok", True)]


@pytest.mark.django_db
class TestKeysNeedingDetails:
    def test_new_reopened_and_capped_backfill(self, source: Source, make_job: MakeJob) -> None:
        make_job(source, key="inhire:described", description="Tem descrição")
        make_job(
            source,
            key="inhire:gone",
            status=Job.Status.ARCHIVED,
            archive_source=Job.ArchiveSource.SOURCE,
            archive_reason="source_removed",
            description="Antiga",
        )
        make_job(
            source,
            key="inhire:mine",
            status=Job.Status.ARCHIVED,
            archive_source=Job.ArchiveSource.MANUAL,
            archive_reason="not_interested",
            description="Antiga",
        )
        for index in range(3):
            make_job(source, key=f"inhire:empty-{index}")

        keys = [
            "inhire:new",
            "inhire:described",
            "inhire:gone",
            "inhire:mine",
            "inhire:empty-0",
            "inhire:empty-1",
            "inhire:empty-2",
        ]
        wanted = inhire_keys_needing_details(keys, backfill_limit=2)
        assert wanted == {"inhire:new", "inhire:gone", "inhire:empty-0", "inhire:empty-1"}


@pytest.mark.usefixtures("quiet_logs")
class TestWithInhireDetails:
    SOURCE = {"id": 1, "name": "Acme", "kind": "inhire", "target": "https://acme.inhire.app/vagas"}

    def _jobs(self) -> list[CollectedJob]:
        return [
            CollectedJob(key=f"inhire:{job_id}", external_id=job_id, title=PYTHON_TITLE, url="u")
            for job_id in ("a", "b")
        ]

    def test_only_wanted_jobs_are_fetched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        requested: list[str] = []

        async def wanted(_keys: list[str]) -> set[str]:
            return {"inhire:a"}

        async def fake_details(
            _client: Any, tenant: str, ids: list[str], **_: Any
        ) -> dict[str, Any]:
            assert tenant == "acme"
            requested.extend(ids)
            return {job_id: parse_job_detail(_page(job_id)) for job_id in ids}

        monkeypatch.setattr(monitor, "_inhire_keys_needing_details_async", wanted)
        monkeypatch.setattr(monitor, "fetch_job_details", fake_details)
        jobs = asyncio.run(with_inhire_details(httpx.AsyncClient(), self.SOURCE, self._jobs()))
        assert requested == ["a"]
        assert jobs[0].description.startswith("Vaga júnior")
        assert jobs[1].description == ""

    def test_any_failure_keeps_the_listing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def wanted(_keys: list[str]) -> set[str]:
            return {"inhire:a", "inhire:b"}

        async def exploding(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("network down")

        monkeypatch.setattr(monitor, "_inhire_keys_needing_details_async", wanted)
        monkeypatch.setattr(monitor, "fetch_job_details", exploding)
        jobs = asyncio.run(with_inhire_details(httpx.AsyncClient(), self.SOURCE, self._jobs()))
        assert jobs == self._jobs()


@pytest.mark.django_db
class TestDescriptionChangesTheHighlight:
    def test_title_only_python_job_crosses_the_minimum_with_a_description(
        self, source: Source
    ) -> None:
        Source.objects.filter(pk=source.pk).update(last_checked_at=timezone.now())
        title_only = CollectedJob(key="inhire:py", external_id="py", title=PYTHON_TITLE, url="u")
        process_source_snapshot(source.pk, [title_only], True)
        job = Job.objects.get(key="inhire:py")
        assert job.score == 24
        assert job.is_highlighted is False

        enriched = apply_detail(title_only, parse_job_detail(_page("py")))
        process_source_snapshot(source.pk, [enriched], True)
        job.refresh_from_db()
        assert job.score >= 25
        assert job.is_highlighted is True
        assert job.location == "São Paulo, SP, BR · Híbrido"
        assert job.work_mode == Job.WorkMode.HYBRID

    def test_a_later_run_without_details_keeps_the_description(self, source: Source) -> None:
        enriched = apply_detail(
            CollectedJob(key="inhire:py", external_id="py", title=PYTHON_TITLE, url="u"),
            parse_job_detail(_page("py")),
        )
        process_source_snapshot(source.pk, [enriched], True)
        title_only = CollectedJob(key="inhire:py", external_id="py", title=PYTHON_TITLE, url="u")
        process_source_snapshot(source.pk, [title_only], True)
        job = Job.objects.get(key="inhire:py")
        assert job.description.startswith("Vaga júnior")
        assert job.is_highlighted is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("quiet_logs")
class TestRunWithJobPages:
    @pytest.fixture(autouse=True)
    def acme(self, clean_sources: None, monkeypatch: pytest.MonkeyPatch) -> Source:
        source = Source.objects.create(name="Acme", target="https://acme.inhire.app/vagas")

        async def listing(_client: Any, url: str) -> list[ScrapedJob]:
            return [ScrapedJob("new-one", PYTHON_TITLE, f"{url}/new-one")]

        monkeypatch.setattr(monitor, "collect_company", listing)
        return source

    def _run(self) -> CheckRun:
        run = CheckRun.objects.create(
            trigger=CheckRun.Trigger.MANUAL,
            status=CheckRun.Status.RUNNING,
            started_at=timezone.now(),
            heartbeat_at=timezone.now(),
        )
        asyncio.run(execute_run(run.pk))
        run.refresh_from_db()
        return run

    def test_new_job_gets_its_description(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def details(_client: Any, _tenant: str, ids: list[str], **_: Any) -> dict[str, Any]:
            return {job_id: parse_job_detail(_page(job_id)) for job_id in ids}

        monkeypatch.setattr(monitor, "fetch_job_details", details)
        run = self._run()
        assert run.status == CheckRun.Status.SUCCESS
        job = Job.objects.get(key="inhire:new-one")
        assert job.description.startswith("Vaga júnior")
        assert job.is_highlighted is True

    def test_page_failure_keeps_the_job_and_archives_nothing(
        self, acme: Source, make_job: MakeJob, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kept = make_job(acme, key="inhire:new-one", external_id="new-one", title=PYTHON_TITLE)

        async def broken(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise httpx.ConnectError("offline")

        monkeypatch.setattr(monitor, "fetch_job_details", broken)
        run = self._run()
        assert run.status == CheckRun.Status.SUCCESS
        kept.refresh_from_db()
        assert kept.status == Job.Status.ACTIVE
        assert kept.description == ""
        assert Job.objects.filter(status=Job.Status.ARCHIVED).count() == 0


@pytest.mark.django_db
@pytest.mark.usefixtures("quiet_logs")
class TestBackfillCommand:
    def test_fetches_stores_and_rescores(
        self, source: Source, make_job: MakeJob, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        python = make_job(source, external_id="py", key="inhire:py", title=PYTHON_TITLE)
        broken = make_job(source, external_id="broken", key="inhire:broken", title=PYTHON_TITLE)
        described = make_job(
            source, external_id="done", key="inhire:done", title="Analista", description="Pronta"
        )
        archived = make_job(
            source,
            external_id="old",
            key="inhire:old",
            title=PYTHON_TITLE,
            status=Job.Status.ARCHIVED,
            archive_source=Job.ArchiveSource.SOURCE,
            archive_reason="source_removed",
        )
        calls: list[str] = []
        transport = _pages_transport({"py": _page("py"), "broken": 500}, calls)
        original = backfill_command.backfill

        def with_transport(limit: Any = None, concurrency: int = 5, progress: Any = None) -> Any:
            return original(limit, concurrency, progress, transport=transport)

        monkeypatch.setattr(backfill_command, "backfill", with_transport)
        out = StringIO()
        call_command("fetch_inhire_details", stdout=out)

        output = out.getvalue()
        assert "requested: 2" in output
        assert "fetched: 1" in output
        assert "failed: 1" in output
        assert "highlighted after: 1" in output
        assert "done" not in calls and "old" not in calls

        python.refresh_from_db()
        assert python.description.startswith("Vaga júnior")
        assert python.is_highlighted is True
        assert python.published_at is not None
        broken.refresh_from_db()
        assert broken.description == ""
        described.refresh_from_db()
        assert described.description == "Pronta"
        archived.refresh_from_db()
        assert archived.description == ""

    def test_limit_takes_the_most_recent(self, source: Source, make_job: MakeJob) -> None:
        older = make_job(source, external_id="older", key="inhire:older")
        Job.objects.filter(pk=older.pk).update(first_seen_at=timezone.now().replace(year=2025))
        newer = make_job(source, external_id="newer", key="inhire:newer")
        pending = backfill_command.pending_jobs(1)
        assert [job.pk for job in pending] == [newer.pk]
