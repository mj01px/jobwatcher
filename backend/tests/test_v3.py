"""v3: stack gated highlights, visits, source yield, legacy conversion and desktop services."""

from __future__ import annotations

import importlib
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from pipeline.models import Application, Interaction
from pipeline.services import (
    DETECTED_TITLE,
    ENTERED_TITLE,
    convert_applied_archives,
    register_detected_application,
)
from tests.conftest import MakeJob, data_of, error_of
from watcher.constants import IMPORTED_SOURCE_TARGET, MANUAL_SOURCE_TARGET
from watcher.models import CheckRun, CheckRunSource, Job, Setting, Source
from watcher.scoring import PROFILE
from watcher.scoring.engine import score_groups
from watcher.services.collection import CollectedJob
from watcher.services.monitor import process_source_snapshot
from watcher.services.notifications import new_highlights_for_run, overdue_applications
from watcher.services.preferences import (
    notifications_enabled,
    overdue_notice_last_on,
    set_notifications_enabled,
    set_overdue_notice_last_on,
)
from watcher.services.scoring import ScoringContext, apply_classification, load_scoring
from watcher.services.visits import previous_visit_end, register_visit

gate_migration = importlib.import_module("watcher.migrations.0007_v3_highlight_gate")


def _collected(external_id: str, title: str, kind: str = "gupy") -> CollectedJob:
    return CollectedJob(
        key=f"{kind}:{external_id}",
        external_id=external_id,
        title=title,
        url=f"https://example.test/{external_id}",
    )


# 1. v1 "applied" archives become applications


@pytest.mark.django_db
class TestConvertAppliedArchives:
    def test_converts_restores_and_dates_by_the_archive(
        self, source: Source, make_job: MakeJob
    ) -> None:
        # 01:30 UTC on the 15th is still the 14th in Sao Paulo.
        archived_at = datetime(2026, 9, 15, 1, 30, tzinfo=UTC)
        job = make_job(
            source,
            status=Job.Status.ARCHIVED,
            archive_source=Job.ArchiveSource.MANUAL,
            archive_reason="applied",
            archive_note="sent cv",
            archived_at=archived_at,
            arrived_new=True,
        )

        assert convert_applied_archives() == 1

        job.refresh_from_db()
        assert job.status == Job.Status.ACTIVE
        assert (job.archive_source, job.archive_reason, job.archive_note, job.archived_at) == (
            None,
            None,
            None,
            None,
        )
        assert job.arrived_new is False
        application = Application.objects.get(job=job)
        assert application.status == Application.Status.APPLIED
        assert application.applied_on == date(2026, 9, 14)
        assert application.created_at == archived_at
        assert list(application.interactions.values_list("title", flat=True)) == [ENTERED_TITLE]

    def test_is_idempotent_and_ignores_other_rows(self, source: Source, make_job: MakeJob) -> None:
        now = timezone.now()
        applied = make_job(
            source,
            status=Job.Status.ARCHIVED,
            archive_source=Job.ArchiveSource.MANUAL,
            archive_reason="applied",
            archived_at=now,
        )
        other_reason = make_job(
            source,
            status=Job.Status.ARCHIVED,
            archive_source=Job.ArchiveSource.MANUAL,
            archive_reason="not_interested",
            archived_at=now,
        )
        already_in_funnel = make_job(
            source,
            status=Job.Status.ARCHIVED,
            archive_source=Job.ArchiveSource.MANUAL,
            archive_reason="applied",
            archived_at=now,
        )
        Application.objects.create(job=already_in_funnel, status="interview")

        assert convert_applied_archives() == 1
        assert convert_applied_archives() == 0
        assert Application.objects.filter(job=applied).exists()
        assert not Application.objects.filter(job=other_reason).exists()
        already_in_funnel.refresh_from_db()
        assert already_in_funnel.status == Job.Status.ARCHIVED
        assert Application.objects.get(job=already_in_funnel).status == "interview"

    def test_migration_uses_the_same_rule_with_historical_models(
        self, source: Source, make_job: MakeJob
    ) -> None:
        from django.apps import apps

        conversion = importlib.import_module("pipeline.migrations.0002_convert_applied_archives")
        job = make_job(
            source,
            status=Job.Status.ARCHIVED,
            archive_source=Job.ArchiveSource.MANUAL,
            archive_reason="applied",
            archived_at=timezone.now(),
        )
        conversion.forwards(apps, None)
        assert Application.objects.filter(job=job, status="applied").exists()


# 2. Highlight needs a stack hit


class TestScoreGroups:
    def test_returns_positive_groups_only(self) -> None:
        score, tags, groups = score_groups("desenvolvedor python junior php", "")
        assert "core" in groups
        assert "level_match" in groups
        assert "stack_mismatch" not in groups
        assert "php" not in tags
        assert score == 2 * (12 + 10 - 20)


@pytest.mark.django_db
class TestStackGate:
    def _job(self, title: str) -> Job:
        return Job(title=title, description="", company_name="", location="")

    def test_finance_junior_without_stack_is_not_highlighted(self) -> None:
        job = self._job("Analista Financeiro Junior")
        apply_classification(job, ScoringContext(profile=PROFILE, min_score=25))
        assert job.score >= 25
        assert job.score_groups == ["domain", "level_match"]
        assert job.is_highlighted is False

    def test_stack_hit_is_highlighted(self) -> None:
        job = self._job("Desenvolvedor Python Junior")
        apply_classification(job, ScoringContext(profile=PROFILE, min_score=25))
        assert "core" in job.score_groups
        assert job.is_highlighted is True

    def test_empty_stack_groups_disable_the_gate(self) -> None:
        job = self._job("Analista Financeiro Junior")
        apply_classification(job, ScoringContext(profile=PROFILE, min_score=25, stack_groups=()))
        assert job.is_highlighted is True

    def test_below_min_score_is_never_highlighted(self) -> None:
        job = self._job("Desenvolvedor Python Junior")
        apply_classification(job, ScoringContext(profile=PROFILE, min_score=1000))
        assert job.is_highlighted is False

    def test_defaults_come_from_settings(self) -> None:
        context = load_scoring()
        assert context.min_score == 25
        assert context.stack_groups == ("core", "adjacent")

    def test_job_json_exposes_score_groups(
        self, api_client: APIClient, source: Source, make_job: MakeJob
    ) -> None:
        job = make_job(source, score_groups=["core"])
        assert data_of(api_client.get(f"/api/v1/jobs/{job.pk}"))["scoreGroups"] == ["core"]


@pytest.mark.django_db
class TestGateMigration:
    def test_raises_the_old_default_and_rescores(self, source: Source, make_job: MakeJob) -> None:
        from django.apps import apps

        Setting.objects.update_or_create(key="highlight_min_score", defaults={"value": 20})
        finance = make_job(source, title="Analista Financeiro Junior", is_highlighted=True)
        python = make_job(source, title="Desenvolvedor Python Junior", is_highlighted=False)

        gate_migration.forwards(apps, None)

        assert Setting.objects.get(key="highlight_min_score").value == 25
        finance.refresh_from_db()
        python.refresh_from_db()
        assert finance.is_highlighted is False
        assert python.is_highlighted is True
        assert "core" in python.score_groups

    def test_keeps_a_min_score_the_user_picked(self) -> None:
        from django.apps import apps

        Setting.objects.update_or_create(key="highlight_min_score", defaults={"value": 40})
        gate_migration.forwards(apps, None)
        assert Setting.objects.get(key="highlight_min_score").value == 40


@pytest.mark.django_db
class TestStackGroupsSettings:
    def test_put_saves_stack_groups_and_rescores(
        self, api_client: APIClient, source: Source, make_job: MakeJob
    ) -> None:
        job = make_job(source, title="Analista Financeiro Junior")
        data = data_of(
            api_client.put(
                "/api/v1/settings/scoring",
                {"stackGroups": ["domain", "domain"], "minScore": 25},
                format="json",
            )
        )
        assert data["stackGroups"] == ["domain"]
        job.refresh_from_db()
        assert job.is_highlighted is True

    def test_empty_list_disables_the_gate(self, api_client: APIClient) -> None:
        data = data_of(
            api_client.put("/api/v1/settings/scoring", {"stackGroups": []}, format="json")
        )
        assert data["stackGroups"] == []

    @pytest.mark.parametrize(
        ("body", "issue"),
        [
            ({"stackGroups": ["nope"]}, "Unknown scoring group(s): nope."),
            ({"stackGroups": "core"}, "stackGroups must be a list of strings."),
            (
                {"groups": {"stack": {"weight": 5, "terms": ["go"]}}, "stackGroups": ["core"]},
                "Unknown scoring group(s): core.",
            ),
        ],
    )
    def test_invalid_stack_groups_are_rejected(
        self, api_client: APIClient, body: dict[str, Any], issue: str
    ) -> None:
        response = api_client.put("/api/v1/settings/scoring", body, format="json")
        assert response.status_code == 400
        assert error_of(response)["details"] == [{"field": "stackGroups", "issue": issue}]

    def test_omitted_stack_groups_keep_the_saved_list(self, api_client: APIClient) -> None:
        Setting.objects.update_or_create(key="highlight_stack_groups", defaults={"value": ["core"]})
        data = data_of(api_client.put("/api/v1/settings/scoring", {"minScore": 30}, format="json"))
        assert data["stackGroups"] == ["core"]


# 3. Overview recent jobs follow the highlights


@pytest.mark.django_db
def test_overview_recent_jobs_are_highlighted_only(
    api_client: APIClient, clean_sources: None, source: Source, make_job: MakeJob
) -> None:
    make_job(source, title="Plain")
    make_job(source, title="Starred", is_highlighted=True)
    recent = data_of(api_client.get("/api/v1/overview"))["recentJobs"]
    assert [job["title"] for job in recent] == ["Starred"]


# 4. Sources: ownership transfer and yield


@pytest.mark.django_db
class TestOwnershipTransfer:
    def _placeholder(self) -> Source:
        source, _ = Source.objects.get_or_create(
            kind="gupy",
            target=IMPORTED_SOURCE_TARGET,
            defaults={"name": "Gupy (imported from Vaggio)", "is_active": False, "is_hidden": True},
        )
        return source

    def test_placeholder_job_moves_to_the_source_that_returned_it(self, make_job: MakeJob) -> None:
        placeholder = self._placeholder()
        term = Source.objects.create(kind="gupy", name="v3 term", target="v3 term")
        job = make_job(placeholder, key="gupy:77", external_id="77")

        process_source_snapshot(term.pk, [_collected("77", "Dev Python")], False)

        job.refresh_from_db()
        assert job.source_id == term.pk

    def test_job_of_a_real_source_keeps_its_owner(self, make_job: MakeJob) -> None:
        first = Source.objects.create(kind="gupy", name="v3 first", target="v3 first")
        second = Source.objects.create(kind="gupy", name="v3 second", target="v3 second")
        job = make_job(first, key="gupy:88", external_id="88")

        process_source_snapshot(second.pk, [_collected("88", "Dev Django")], False)

        job.refresh_from_db()
        assert job.source_id == first.pk

    def test_manual_jobs_are_never_moved(self, make_job: MakeJob) -> None:
        manual, _ = Source.objects.get_or_create(
            kind="manual",
            target=MANUAL_SOURCE_TARGET,
            defaults={"name": "Manual", "is_hidden": True, "is_active": False},
        )
        term = Source.objects.create(kind="gupy", name="v3 term", target="v3 term")
        job = make_job(manual, key="gupy:99", external_id="99")

        process_source_snapshot(term.pk, [_collected("99", "Dev")], False)

        job.refresh_from_db()
        assert job.source_id == manual.pk


@pytest.mark.django_db
class TestSourceYield:
    def test_counts_and_last_run_jobs(
        self, api_client: APIClient, clean_sources: None, make_job: MakeJob
    ) -> None:
        source = Source.objects.create(name="Acme", target="https://acme.inhire.app/vagas")
        make_job(source, is_highlighted=True)
        make_job(source, is_highlighted=True, status=Job.Status.ARCHIVED)
        in_funnel = make_job(source, is_highlighted=True)
        Application.objects.create(job=in_funnel, status="applied")
        make_job(source)

        [item] = data_of(api_client.get("/api/v1/sources"))
        assert item["activeJobs"] == 3
        assert item["highlightedJobs"] == 1
        assert item["applications"] == 1
        assert item["lastRunJobs"] is None

        now = timezone.now()
        older = CheckRun.objects.create(
            trigger="manual", status="success", started_at=now, finished_at=now
        )
        newer = CheckRun.objects.create(
            trigger="manual",
            status="partial",
            started_at=now,
            finished_at=now + timedelta(hours=1),
        )
        running = CheckRun.objects.create(trigger="manual", status="running", started_at=now)
        errored = CheckRun.objects.create(
            trigger="manual", status="partial", started_at=now, finished_at=now + timedelta(hours=2)
        )
        for run, jobs in ((older, 5), (newer, 7), (running, 9), (errored, None)):
            CheckRunSource.objects.create(
                run=run, source=source, kind="inhire", name="Acme", state="done", jobs=jobs
            )

        [item] = data_of(api_client.get("/api/v1/sources"))
        assert item["lastRunJobs"] == 7

    def test_patch_response_includes_yield_fields(
        self, api_client: APIClient, clean_sources: None
    ) -> None:
        source = Source.objects.create(name="Acme", target="https://acme.inhire.app/vagas")
        data = data_of(
            api_client.patch(f"/api/v1/sources/{source.pk}", {"isActive": False}, format="json")
        )
        assert (data["highlightedJobs"], data["applications"], data["lastRunJobs"]) == (0, 0, None)


# 5. New since the last visit


@pytest.mark.django_db
class TestVisits:
    def test_first_ping_starts_a_visit_without_previous_end(self) -> None:
        now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
        visit = register_visit(now)
        assert visit == {"visit_started_at": now, "previous_visit_ended_at": None}

    def test_pings_within_the_gap_keep_the_visit(self) -> None:
        start = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
        register_visit(start)
        visit = register_visit(start + timedelta(minutes=19))
        visit = register_visit(start + timedelta(minutes=38))
        assert visit == {"visit_started_at": start, "previous_visit_ended_at": None}

    def test_a_gap_over_twenty_minutes_starts_a_new_visit(self) -> None:
        start = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
        register_visit(start)
        last = start + timedelta(minutes=10)
        register_visit(last)
        later = last + timedelta(minutes=20, seconds=1)
        visit = register_visit(later)
        assert visit == {"visit_started_at": later, "previous_visit_ended_at": last}
        assert previous_visit_end() == last

    def test_exactly_twenty_minutes_is_still_the_same_visit(self) -> None:
        start = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
        register_visit(start)
        visit = register_visit(start + timedelta(minutes=20))
        assert visit["visit_started_at"] == start

    def test_api_returns_iso_timestamps(self, api_client: APIClient) -> None:
        data = data_of(api_client.post("/api/v1/visits"))
        assert set(data) == {"visitStartedAt", "previousVisitEndedAt"}
        assert data["visitStartedAt"].endswith("Z")
        assert data["previousVisitEndedAt"] is None

    def test_api_requires_csrf(self, csrf_client: APIClient) -> None:
        response = csrf_client.post("/api/v1/visits")
        assert response.status_code == 403
        assert error_of(response)["code"] == "CSRF_FAILED"


@pytest.mark.django_db
class TestComputedIsNew:
    @pytest.fixture
    def boundary(self) -> datetime:
        end = timezone.now() - timedelta(hours=1)
        Setting.objects.update_or_create(
            key="visit_previous_end_at", defaults={"value": end.isoformat()}
        )
        return end

    def test_new_means_arrived_after_the_previous_visit(
        self,
        api_client: APIClient,
        clean_sources: None,
        source: Source,
        make_job: MakeJob,
        boundary: datetime,
    ) -> None:
        before = boundary - timedelta(minutes=5)
        after = boundary + timedelta(minutes=5)
        make_job(source, title="Old news", arrived_new=True, first_seen_at=before)
        make_job(source, title="Fresh", arrived_new=True, first_seen_at=after)
        make_job(source, title="Baseline", arrived_new=False, first_seen_at=after)
        make_job(
            source,
            title="Reopened",
            arrived_new=True,
            first_seen_at=before - timedelta(days=3),
            reopened_at=after,
        )

        jobs = data_of(api_client.get("/api/v1/jobs"))
        flags = {job["title"]: job["isNew"] for job in jobs}
        assert flags == {"Old news": False, "Fresh": True, "Baseline": False, "Reopened": True}
        assert {job["title"] for job in jobs[:2]} == {"Fresh", "Reopened"}
        overview = data_of(api_client.get("/api/v1/overview"))
        assert overview["jobStats"]["new"] == 2
        detail = data_of(api_client.get(f"/api/v1/jobs/{Job.objects.get(title='Fresh').pk}"))
        assert detail["isNew"] is True

    def test_without_any_previous_visit_every_arrival_is_new(
        self, api_client: APIClient, clean_sources: None, source: Source, make_job: MakeJob
    ) -> None:
        make_job(source, title="Arrived", arrived_new=True)
        make_job(source, title="Baseline")
        flags = {job["title"]: job["isNew"] for job in data_of(api_client.get("/api/v1/jobs"))}
        assert flags == {"Arrived": True, "Baseline": False}

    def test_nested_job_in_an_application_is_computed_too(
        self, api_client: APIClient, source: Source, make_job: MakeJob, boundary: datetime
    ) -> None:
        job = make_job(source, arrived_new=True, first_seen_at=boundary - timedelta(minutes=1))
        application = Application.objects.create(job=job, status="applied")
        data = data_of(api_client.get(f"/api/v1/applications/{application.pk}"))
        assert data["job"]["isNew"] is False


# 8. Desktop notifications


@pytest.mark.django_db
class TestNotifications:
    def test_new_highlights_for_run(self, source: Source, make_job: MakeJob) -> None:
        started = timezone.now() - timedelta(minutes=10)
        run = CheckRun.objects.create(trigger="scheduled", status="success", started_at=started)
        after = started + timedelta(minutes=1)
        best = make_job(
            source,
            title="Best",
            score=60,
            is_highlighted=True,
            arrived_new=True,
            first_seen_at=after,
        )
        good = make_job(
            source,
            title="Good",
            score=40,
            is_highlighted=True,
            arrived_new=True,
            first_seen_at=after,
        )
        make_job(
            source,
            title="Old",
            score=90,
            is_highlighted=True,
            arrived_new=True,
            first_seen_at=started - timedelta(minutes=1),
        )
        make_job(
            source,
            title="Plain",
            score=10,
            is_highlighted=False,
            arrived_new=True,
            first_seen_at=after,
        )
        make_job(
            source,
            title="Baseline",
            score=50,
            is_highlighted=True,
            arrived_new=False,
            first_seen_at=after,
        )
        make_job(
            source,
            title="Archived",
            score=50,
            is_highlighted=True,
            arrived_new=True,
            first_seen_at=after,
            status=Job.Status.ARCHIVED,
        )
        funnel = make_job(
            source,
            title="Funnel",
            score=70,
            is_highlighted=True,
            arrived_new=True,
            first_seen_at=after,
        )
        Application.objects.create(job=funnel, status="interest")
        reopened = make_job(
            source,
            title="Reopened",
            score=30,
            is_highlighted=True,
            arrived_new=True,
            first_seen_at=started - timedelta(days=5),
            reopened_at=after,
        )

        result = new_highlights_for_run(run.pk)

        assert [job.pk for job in result] == [best.pk, good.pk, reopened.pk]

    def test_unknown_or_unstarted_run_is_empty(self) -> None:
        queued = CheckRun.objects.create(trigger="manual", status="queued")
        assert new_highlights_for_run(queued.pk) == []
        assert new_highlights_for_run(999_999) == []

    @override_settings(JOB_WATCHER_TIMEZONE="America/Sao_Paulo")
    def test_overdue_applications(self, source: Source, make_job: MakeJob) -> None:
        today = timezone.now().astimezone().date()
        overdue = Application.objects.create(
            job=make_job(source), status="applied", next_step_on=date(2020, 1, 1)
        )
        Application.objects.create(
            job=make_job(source), status="applied", next_step_on=today + timedelta(days=3)
        )
        Application.objects.create(
            job=make_job(source), status="rejected", next_step_on=date(2020, 1, 1)
        )
        Application.objects.create(job=make_job(source), status="interview")
        assert [application.pk for application in overdue_applications()] == [overdue.pk]

    def test_preference_helpers(self) -> None:
        assert notifications_enabled() is True
        set_notifications_enabled(False)
        assert notifications_enabled() is False
        assert overdue_notice_last_on() is None
        set_overdue_notice_last_on(date(2026, 9, 15))
        assert overdue_notice_last_on() == date(2026, 9, 15)


# 9. InHire application detection


@pytest.mark.django_db
class TestRegisterDetectedApplication:
    def test_creates_an_applied_application(self, source: Source, make_job: MakeJob) -> None:
        job = make_job(source)
        application, changed = register_detected_application(job.pk)
        assert changed is True
        assert application.status == Application.Status.APPLIED
        assert application.applied_on is not None
        titles = list(
            Interaction.objects.filter(application=application)
            .order_by("id")
            .values_list("title", flat=True)
        )
        assert titles == [ENTERED_TITLE, DETECTED_TITLE]

    def test_moves_interest_to_applied(self, source: Source, make_job: MakeJob) -> None:
        job = make_job(source)
        existing = Application.objects.create(job=job, status="interest")
        application, changed = register_detected_application(job.pk)
        assert changed is True
        assert application.pk == existing.pk
        application.refresh_from_db()
        assert application.status == Application.Status.APPLIED
        assert application.applied_on is not None
        assert Interaction.objects.filter(application=application, title=DETECTED_TITLE).exists()

    def test_later_status_is_left_alone(self, source: Source, make_job: MakeJob) -> None:
        job = make_job(source)
        existing = Application.objects.create(job=job, status="interview")
        application, changed = register_detected_application(job.pk)
        assert changed is False
        application.refresh_from_db()
        assert application.pk == existing.pk
        assert application.status == Application.Status.INTERVIEW
        assert not Interaction.objects.filter(application=application).exists()

    def test_unknown_job_raises(self) -> None:
        with pytest.raises(Job.DoesNotExist):
            register_detected_application(999_999)
