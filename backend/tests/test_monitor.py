from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from pipeline.models import Application
from tests.conftest import MakeJob
from watcher.models import CheckRun, CheckRunSource, Job, Setting, Source
from watcher.services import monitor
from watcher.services.collection import CollectedJob, CollectionError, CollectorResult
from watcher.services.inhire import ScrapedJob
from watcher.services.monitor import (
    execute_run,
    expire_old_jobs,
    process_source_snapshot,
)
from watcher.services.runs import build_progress


def _job(external_id: str, title: str, **fields: Any) -> CollectedJob:
    values: dict[str, Any] = {
        "key": f"inhire:{external_id}",
        "external_id": external_id,
        "title": title,
        "url": f"https://example.test/vagas/{external_id}/job",
    }
    values.update(fields)
    return CollectedJob(**values)


@pytest.mark.django_db
class TestSnapshot:
    def test_first_snapshot_is_baseline_and_later_job_is_new(self, source: Source) -> None:
        first = _job("one", "Backend Developer")
        second = _job("two", "Data Analyst")

        assert process_source_snapshot(source.pk, [first], True) == (0, 0)
        assert process_source_snapshot(source.pk, [first, second], True) == (1, 0)
        assert Job.objects.get(external_id="two").arrived_new is True
        assert Job.objects.get(external_id="one").arrived_new is False

    def test_missing_job_is_archived_and_reappearance_restores_it(self, source: Source) -> None:
        job = _job("one", "Mobile Developer")
        process_source_snapshot(source.pk, [job], True)
        _, archived_count = process_source_snapshot(source.pk, [], True)
        assert archived_count == 1
        archived = Job.objects.get(external_id="one")
        assert archived.status == Job.Status.ARCHIVED
        assert archived.archive_source == Job.ArchiveSource.SOURCE
        assert archived.archive_reason == "source_removed"

        new_count, _ = process_source_snapshot(source.pk, [job], True)
        assert new_count == 1
        restored = Job.objects.get(external_id="one")
        assert restored.status == Job.Status.ACTIVE
        assert restored.reopened_at is not None
        assert restored.archive_source is None
        assert restored.arrived_new is True

    def test_non_authoritative_snapshot_never_archives(self, source: Source) -> None:
        process_source_snapshot(source.pk, [_job("one", "Role")], True)
        assert process_source_snapshot(source.pk, [], False) == (0, 0)
        assert Job.objects.get(external_id="one").status == Job.Status.ACTIVE

    def test_manually_archived_job_stays_archived(self, source: Source) -> None:
        process_source_snapshot(source.pk, [_job("one", "Role")], True)
        Job.objects.filter(external_id="one").update(
            status=Job.Status.ARCHIVED,
            archive_source=Job.ArchiveSource.MANUAL,
            archive_reason="not_interested",
        )
        new_count, archived_count = process_source_snapshot(
            source.pk, [_job("one", "Role renamed")], True
        )
        job = Job.objects.get(external_id="one")
        assert (new_count, archived_count) == (0, 0)
        assert job.status == Job.Status.ARCHIVED
        assert job.archive_reason == "not_interested"
        assert job.title == "Role renamed"

    def test_existing_job_is_updated_and_rescored(self, source: Source) -> None:
        process_source_snapshot(source.pk, [_job("one", "Analyst")], True)
        job = Job.objects.get(external_id="one")
        assert (job.score, job.is_highlighted) == (0, False)

        process_source_snapshot(
            source.pk, [_job("one", "Desenvolvedor Python Junior", company_name="Acme")], True
        )
        job.refresh_from_db()
        assert job.title == "Desenvolvedor Python Junior"
        assert job.score == 44
        assert job.score_tags == ["python", "junior"]
        assert job.seniority == "junior"
        assert job.is_highlighted is True

    def test_highlight_follows_the_saved_min_score(self, source: Source) -> None:
        Setting.objects.update_or_create(key="highlight_min_score", defaults={"value": 50})
        process_source_snapshot(source.pk, [_job("one", "Desenvolvedor Python Junior")], True)
        assert Job.objects.get(external_id="one").is_highlighted is False

    def test_snapshot_marks_source_checked_and_clears_error(self, source: Source) -> None:
        Source.objects.filter(pk=source.pk).update(last_error="boom")
        process_source_snapshot(source.pk, [], True)
        source.refresh_from_db()
        assert source.last_checked_at is not None
        assert source.last_error is None

    def test_other_sources_are_untouched(self, source: Source, make_job: MakeJob) -> None:
        other = Source.objects.create(name="Other", target="https://other.inhire.app/vagas")
        foreign = make_job(other)
        process_source_snapshot(source.pk, [], True)
        foreign.refresh_from_db()
        assert foreign.status == Job.Status.ACTIVE

    def test_same_key_from_another_source_is_deduplicated(self, source: Source) -> None:
        term_a = Source.objects.create(kind="gupy", name="python", target="python-a")
        term_b = Source.objects.create(kind="gupy", name="django", target="django-b")
        item = _job("77", "Dev Python", key="gupy:77", company_name="Acme")
        process_source_snapshot(term_a.pk, [item], False)
        process_source_snapshot(term_b.pk, [item], False)
        job = Job.objects.get(key="gupy:77")
        assert Job.objects.filter(key="gupy:77").count() == 1
        assert job.source_id == term_a.pk

    def test_old_gupy_job_is_not_inserted(self) -> None:
        term = Source.objects.create(kind="gupy", name="python", target="python-old")
        old = _job("1", "Old Role", key="gupy:1", published_at=timezone.now() - timedelta(days=120))
        fresh = _job(
            "2", "Fresh Role", key="gupy:2", published_at=timezone.now() - timedelta(days=2)
        )
        undated = _job("3", "Undated Role", key="gupy:3")
        process_source_snapshot(term.pk, [old, fresh, undated], False)
        assert set(Job.objects.filter(source=term).values_list("key", flat=True)) == {
            "gupy:2",
            "gupy:3",
        }

    def test_old_github_issue_counts_as_seen_for_authority(self) -> None:
        repo = Source.objects.create(kind="github", name="repo", target="owner/old")
        item = _job("1", "Role", key="github:https://gh/1", published_at=timezone.now())
        process_source_snapshot(repo.pk, [item], True)
        stale = _job(
            "1", "Role", key="github:https://gh/1", published_at=timezone.now() - timedelta(days=90)
        )
        _, archived = process_source_snapshot(repo.pk, [stale], True)
        assert archived == 0
        assert Job.objects.get(key="github:https://gh/1").status == Job.Status.ACTIVE

    def test_unknown_source_raises(self) -> None:
        with pytest.raises(Source.DoesNotExist):
            process_source_snapshot(999_999, [], True)


@pytest.mark.django_db
class TestExpiry:
    def test_old_gupy_and_github_jobs_expire_but_inhire_and_funnel_do_not(
        self, source: Source, make_job: MakeJob
    ) -> None:
        term = Source.objects.create(kind="gupy", name="python", target="python-x")
        repo = Source.objects.create(kind="github", name="repo", target="owner/repo-x")
        old = timezone.now() - timedelta(days=45)
        gupy_old = make_job(term, published_at=old)
        github_undated_old = make_job(repo, published_at=None, first_seen_at=old)
        gupy_recent = make_job(term, published_at=timezone.now() - timedelta(days=3))
        inhire_old = make_job(source, first_seen_at=old)
        in_funnel = make_job(term, published_at=old)
        Application.objects.create(job=in_funnel, status="applied")

        assert expire_old_jobs() == 2
        statuses = {
            job.pk: (job.status, job.archive_reason)
            for job in Job.objects.filter(
                pk__in=[
                    gupy_old.pk,
                    github_undated_old.pk,
                    gupy_recent.pk,
                    inhire_old.pk,
                    in_funnel.pk,
                ]
            )
        }
        assert statuses[gupy_old.pk] == ("archived", "expired")
        assert statuses[github_undated_old.pk] == ("archived", "expired")
        assert statuses[gupy_recent.pk] == ("active", None)
        assert statuses[inhire_old.pk] == ("active", None)
        assert statuses[in_funnel.pk] == ("active", None)


@pytest.mark.django_db
class TestRunProgress:
    def _run_with(self, names: list[str]) -> tuple[CheckRun, list[Source]]:
        run = CheckRun.objects.create(
            trigger=CheckRun.Trigger.MANUAL,
            status=CheckRun.Status.RUNNING,
            started_at=timezone.now(),
        )
        sources = []
        for index, name in enumerate(names):
            source = Source.objects.create(name=name, target=f"https://{name.lower()}.inhire.app")
            CheckRunSource.objects.create(run=run, source=source, name=name, position=index)
            sources.append(source)
        return run, sources

    def test_counts_and_settled_track_source_states(self) -> None:
        run, (alpha, beta, _gamma) = self._run_with(["Alpha", "Beta", "Gamma"])
        snapshot = build_progress(run)
        assert snapshot["total"] == 3
        assert snapshot["settled"] == 0
        assert snapshot["counts"]["pending"] == 3

        CheckRunSource.objects.filter(run=run, source=alpha).update(state="done", jobs=12)
        CheckRunSource.objects.filter(run=run, source=beta).update(state="error")
        snapshot = build_progress(run)
        assert snapshot["settled"] == 2
        assert snapshot["counts"] == {"pending": 1, "collecting": 0, "done": 1, "error": 1}
        entry = next(item for item in snapshot["sources"] if item["name"] == "Alpha")
        assert entry == {
            "sourceId": alpha.pk,
            "kind": "inhire",
            "name": "Alpha",
            "state": "done",
            "jobs": 12,
        }

    def test_sources_keep_their_run_order(self) -> None:
        run, _ = self._run_with(["Zeta", "Alpha"])
        assert [item["name"] for item in build_progress(run)["sources"]] == ["Zeta", "Alpha"]


@pytest.fixture
def quiet_monitor_logs() -> Iterator[None]:
    logger = logging.getLogger("watcher.services.monitor")
    previous = logger.level
    logger.setLevel(logging.CRITICAL)
    yield
    logger.setLevel(previous)


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("quiet_monitor_logs")
class TestExecuteRun:
    @pytest.fixture(autouse=True)
    def sources(self, clean_sources: None, monkeypatch: pytest.MonkeyPatch) -> list[Source]:
        def no_gupy(_term: str) -> CollectorResult:
            return CollectorResult(authoritative=False)

        def no_github(_repo: str) -> CollectorResult:
            return CollectorResult(authoritative=True)

        monkeypatch.setattr(monitor, "collect_gupy_term", no_gupy)
        monkeypatch.setattr(monitor, "collect_github_repo", no_github)
        return [
            Source.objects.create(name=name, target=f"https://{name.lower()}.inhire.app/vagas")
            for name in ("beta", "Alpha", "gamma")
        ] + [
            Source.objects.create(
                name="Paused", target="https://paused.inhire.app/vagas", is_active=False
            ),
            Source.objects.create(
                kind="manual", name="Manual", target="manual", is_active=True, is_hidden=True
            ),
        ]

    def _claimed_run(self) -> CheckRun:
        return CheckRun.objects.create(
            trigger=CheckRun.Trigger.MANUAL,
            status=CheckRun.Status.RUNNING,
            started_at=timezone.now(),
            heartbeat_at=timezone.now(),
        )

    def _patch_collect(self, monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
        monkeypatch.setattr(monitor, "collect_company", handler)

    def test_successful_run_records_incremental_totals(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def one_job(_client: Any, url: str) -> list[ScrapedJob]:
            return [ScrapedJob(f"{url}-job-1", "Backend Engineer", f"{url}/job-1")]

        self._patch_collect(monkeypatch, one_job)
        run = self._claimed_run()
        asyncio.run(execute_run(run.pk))

        run.refresh_from_db()
        assert run.status == CheckRun.Status.SUCCESS
        assert run.sources_total == 3
        assert run.sources_checked == 3
        assert run.jobs_found == 3
        assert run.jobs_new == 0
        assert run.finished_at is not None
        assert run.error is None
        progress = build_progress(run)
        assert progress["counts"]["done"] == 3
        assert [item["name"] for item in progress["sources"]] == ["Alpha", "beta", "gamma"]
        job = Job.objects.get(source__name="Alpha")
        assert job.company_name == "Alpha"
        assert job.key.startswith("inhire:")

    def test_sources_run_in_kind_order_and_dispatch_by_kind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        Source.objects.create(kind="github", name="owner/repo", target="owner/repo")
        Source.objects.create(kind="gupy", name="python", target="python")
        calls: list[str] = []

        async def nothing(_client: Any, _url: str) -> list[ScrapedJob]:
            return []

        def gupy_term(term: str) -> CollectorResult:
            calls.append(f"gupy:{term}")
            return CollectorResult(
                jobs=[
                    CollectedJob(
                        key="gupy:1",
                        external_id="1",
                        title="Desenvolvedor Python Junior",
                        url="https://acme.gupy.io/job/1",
                        company_name="Acme",
                    )
                ],
                authoritative=False,
            )

        def github_repo(repo: str) -> CollectorResult:
            calls.append(f"github:{repo}")
            return CollectorResult(authoritative=True)

        self._patch_collect(monkeypatch, nothing)
        monkeypatch.setattr(monitor, "collect_gupy_term", gupy_term)
        monkeypatch.setattr(monitor, "collect_github_repo", github_repo)
        run = self._claimed_run()
        asyncio.run(execute_run(run.pk))

        run.refresh_from_db()
        assert run.status == CheckRun.Status.SUCCESS
        assert sorted(calls) == ["github:owner/repo", "gupy:python"]
        kinds = [item["kind"] for item in build_progress(run)["sources"]]
        assert kinds == ["inhire", "inhire", "inhire", "gupy", "github"]
        assert Job.objects.get(key="gupy:1").score == 44

    def test_partial_warning_applies_jobs_and_marks_run_partial(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        term = Source.objects.create(kind="gupy", name="python", target="python")

        async def nothing(_client: Any, _url: str) -> list[ScrapedJob]:
            return []

        def flaky(_term: str) -> CollectorResult:
            return CollectorResult(
                jobs=[CollectedJob(key="gupy:9", external_id="9", title="Dev", url="https://g/9")],
                authoritative=False,
                warning="Gupy search 'python' stopped at offset 100: 503",
            )

        self._patch_collect(monkeypatch, nothing)
        monkeypatch.setattr(monitor, "collect_gupy_term", flaky)
        run = self._claimed_run()
        asyncio.run(execute_run(run.pk))

        run.refresh_from_db()
        term.refresh_from_db()
        assert run.status == CheckRun.Status.PARTIAL
        assert "python: Gupy search 'python' stopped at offset 100" in (run.error or "")
        assert Job.objects.filter(key="gupy:9").exists()
        assert term.last_error is not None
        assert run.sources_checked == 4

    def test_collection_failure_never_archives_and_keeps_run_partial(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def one_job(_client: Any, url: str) -> list[ScrapedJob]:
            return [ScrapedJob(f"{url}-seed", "Seed Role", f"{url}/seed-1")]

        self._patch_collect(monkeypatch, one_job)
        asyncio.run(execute_run(self._claimed_run().pk))

        async def always_fails(_client: Any, _url: str) -> list[ScrapedJob]:
            raise CollectionError("InHire API request failed")

        self._patch_collect(monkeypatch, always_fails)
        run = self._claimed_run()
        asyncio.run(execute_run(run.pk))

        run.refresh_from_db()
        assert run.status == CheckRun.Status.PARTIAL
        assert run.sources_checked == 0
        assert Job.objects.filter(status=Job.Status.ARCHIVED).count() == 0
        assert Job.objects.filter(status=Job.Status.ACTIVE).count() == 3
        assert run.error is not None
        assert "Alpha: InHire API request failed" in run.error
        assert Source.objects.filter(last_error__isnull=False, is_active=True).count() == 3
        assert build_progress(run)["counts"]["error"] == 3

    def test_run_expires_old_jobs_and_counts_them(
        self, monkeypatch: pytest.MonkeyPatch, make_job: MakeJob
    ) -> None:
        term = Source.objects.create(kind="gupy", name="python", target="python", is_active=False)
        make_job(term, published_at=timezone.now() - timedelta(days=60))

        async def nothing(_client: Any, _url: str) -> list[ScrapedJob]:
            return []

        self._patch_collect(monkeypatch, nothing)
        run = self._claimed_run()
        asyncio.run(execute_run(run.pk))
        run.refresh_from_db()
        assert run.jobs_archived == 1
        assert Job.objects.get(source=term).archive_reason == "expired"

    def test_arrived_new_is_not_reset_when_a_run_starts(
        self, monkeypatch: pytest.MonkeyPatch, sources: list[Source], make_job: MakeJob
    ) -> None:
        paused = sources[3]
        fresh = make_job(paused, arrived_new=True)

        async def nothing(_client: Any, _url: str) -> list[ScrapedJob]:
            return []

        self._patch_collect(monkeypatch, nothing)
        asyncio.run(execute_run(self._claimed_run().pk))
        fresh.refresh_from_db()
        # Whether it is still new depends on the last visit, not on runs.
        assert fresh.arrived_new is True

    def test_unexpected_crash_marks_run_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def explode(_run_id: int) -> list[dict[str, Any]]:
            raise RuntimeError("database gone")

        monkeypatch.setattr(monitor, "_start_run_async", explode)
        run = self._claimed_run()
        asyncio.run(execute_run(run.pk))
        run.refresh_from_db()
        assert run.status == CheckRun.Status.FAILED
        assert run.error == "database gone"
        assert run.finished_at is not None
