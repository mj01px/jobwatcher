from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from pipeline.dates import local_today
from pipeline.models import Application, Interaction
from tests.conftest import MakeJob, data_of, error_of
from watcher.models import Job, Source

APPLICATION_KEYS = {
    "id",
    "job",
    "status",
    "priority",
    "appliedOn",
    "nextStep",
    "nextStepOn",
    "contact",
    "hasReferral",
    "notes",
    "isOverdue",
    "daysIdle",
    "interactionsCount",
    "createdAt",
    "updatedAt",
}


@pytest.fixture
def job(source: Source, make_job: MakeJob) -> Job:
    return make_job(source, title="Backend Engineer", arrived_new=True)


def _create(client: APIClient, job_id: int, **body: Any) -> Any:
    return client.post(f"/api/v1/jobs/{job_id}/application", body, format="json")


@pytest.mark.django_db
class TestEnterFunnel:
    def test_applied_by_default(self, api_client: APIClient, job: Job) -> None:
        response = _create(api_client, job.pk)
        assert response.status_code == 201
        data = data_of(response)
        assert set(data) == APPLICATION_KEYS
        assert data["status"] == "applied"
        assert data["appliedOn"] == local_today().isoformat()
        assert data["priority"] == 3
        assert data["interactionsCount"] == 1
        assert data["job"]["application"] == {"id": data["id"], "status": "applied"}
        job.refresh_from_db()
        assert job.arrived_new is False

    def test_interest_has_no_applied_date(self, api_client: APIClient, job: Job) -> None:
        data = data_of(_create(api_client, job.pk, status="interest"))
        assert (data["status"], data["appliedOn"]) == ("interest", None)

    def test_second_application_conflicts(self, api_client: APIClient, job: Job) -> None:
        _create(api_client, job.pk)
        response = _create(api_client, job.pk)
        assert response.status_code == 409
        assert error_of(response)["code"] == "CONFLICT"

    def test_invalid_status_and_unknown_job(self, api_client: APIClient, job: Job) -> None:
        assert _create(api_client, job.pk, status="offer").status_code == 400
        assert _create(api_client, 999_999).status_code == 404

    def test_job_leaves_the_lists_and_comes_back_on_delete(
        self, api_client: APIClient, job: Job
    ) -> None:
        application_id = data_of(_create(api_client, job.pk))["id"]
        listed = [item["id"] for item in data_of(api_client.get("/api/v1/jobs"))]
        assert job.pk not in listed

        response = api_client.delete(f"/api/v1/applications/{application_id}")
        assert response.status_code == 204
        listed = [item["id"] for item in data_of(api_client.get("/api/v1/jobs"))]
        assert job.pk in listed
        assert not Interaction.objects.exists()


@pytest.mark.django_db
class TestBoard:
    def test_columns_order_overdue_and_counts(
        self, api_client: APIClient, source: Source, make_job: MakeJob
    ) -> None:
        now = timezone.now()
        low = Application.objects.create(job=make_job(source), status="applied", priority=4)
        high = Application.objects.create(job=make_job(source), status="applied", priority=1)
        same_prio_recent = Application.objects.create(
            job=make_job(source), status="applied", priority=4, updated_at=now + timedelta(hours=1)
        )
        late = Application.objects.create(
            job=make_job(source),
            status="interview",
            next_step_on=local_today() - timedelta(days=2),
        )
        Application.objects.create(
            job=make_job(source), status="rejected", next_step_on=date(2020, 1, 1)
        )
        Application.objects.create(job=make_job(source), status="withdrawn")

        data = data_of(api_client.get("/api/v1/applications/board"))
        assert [column["status"] for column in data["columns"]] == [
            "interest",
            "applied",
            "screening",
            "challenge",
            "interview",
            "offer",
        ]
        applied = next(column for column in data["columns"] if column["status"] == "applied")
        assert [app["id"] for app in applied["applications"]] == [
            high.pk,
            same_prio_recent.pk,
            low.pk,
        ]
        assert [app["id"] for app in data["overdue"]] == [late.pk]
        assert data["overdue"][0]["isOverdue"] is True
        assert data["counts"] == {
            "interest": 0,
            "applied": 3,
            "screening": 0,
            "challenge": 0,
            "interview": 1,
            "offer": 0,
            "rejected": 1,
            "withdrawn": 1,
        }

    def test_closed_lists_rejected_and_withdrawn_newest_first(
        self, api_client: APIClient, source: Source, make_job: MakeJob
    ) -> None:
        old = Application.objects.create(
            job=make_job(source), status="rejected", updated_at=timezone.now() - timedelta(days=3)
        )
        recent = Application.objects.create(job=make_job(source), status="withdrawn")
        Application.objects.create(job=make_job(source), status="offer")
        data = data_of(api_client.get("/api/v1/applications/closed"))
        assert [app["id"] for app in data] == [recent.pk, old.pk]
        assert data[0]["isOverdue"] is False


@pytest.mark.django_db
class TestApplicationDetailAndPatch:
    def test_detail_includes_interactions_newest_first(
        self, api_client: APIClient, job: Job
    ) -> None:
        application = Application.objects.create(job=job, status="applied")
        Interaction.objects.create(application=application, date=date(2026, 9, 1), title="Sent CV")
        Interaction.objects.create(application=application, date=date(2026, 9, 5), title="Call")
        data = data_of(api_client.get(f"/api/v1/applications/{application.pk}"))
        assert [item["title"] for item in data["interactions"]] == ["Call", "Sent CV"]
        assert set(data["interactions"][0]) == {
            "id",
            "applicationId",
            "date",
            "title",
            "detail",
            "createdAt",
        }
        assert data["interactionsCount"] == 2

    def test_patch_fields_and_status_side_effects(self, api_client: APIClient, job: Job) -> None:
        application = Application.objects.create(job=job, status="interest")
        response = api_client.patch(
            f"/api/v1/applications/{application.pk}",
            {
                "status": "applied",
                "priority": 1,
                "nextStep": " Follow up ",
                "nextStepOn": "2026-10-01",
                "contact": "Ana",
                "hasReferral": True,
                "notes": "Talked on LinkedIn",
            },
            format="json",
        )
        assert response.status_code == 200
        data = data_of(response)
        assert data["status"] == "applied"
        assert data["appliedOn"] == local_today().isoformat()
        assert (data["priority"], data["nextStep"], data["nextStepOn"]) == (
            1,
            "Follow up",
            "2026-10-01",
        )
        assert (data["contact"], data["hasReferral"], data["notes"]) == (
            "Ana",
            True,
            "Talked on LinkedIn",
        )
        assert Interaction.objects.filter(title="Tenho interesse -> Aplicada").exists()

    def test_existing_applied_on_is_kept_and_same_status_adds_no_interaction(
        self, api_client: APIClient, job: Job
    ) -> None:
        application = Application.objects.create(
            job=job, status="screening", applied_on=date(2026, 8, 1)
        )
        api_client.patch(
            f"/api/v1/applications/{application.pk}", {"status": "applied"}, format="json"
        )
        api_client.patch(
            f"/api/v1/applications/{application.pk}", {"status": "applied"}, format="json"
        )
        application.refresh_from_db()
        assert application.applied_on == date(2026, 8, 1)
        assert Interaction.objects.filter(application=application).count() == 1

    def test_clearing_dates(self, api_client: APIClient, job: Job) -> None:
        application = Application.objects.create(
            job=job, status="applied", next_step_on=date(2026, 1, 1)
        )
        data = data_of(
            api_client.patch(
                f"/api/v1/applications/{application.pk}", {"nextStepOn": None}, format="json"
            )
        )
        assert data["nextStepOn"] is None

    @pytest.mark.parametrize(
        ("body", "field"),
        [
            ({"status": "hired"}, "status"),
            ({"priority": 0}, "priority"),
            ({"priority": 6}, "priority"),
            ({"nextStepOn": "01/10/2026"}, "nextStepOn"),
            ({"hasReferral": "yes"}, "hasReferral"),
            ({"nextStep": "x" * 301}, "nextStep"),
        ],
    )
    def test_invalid_patch(
        self, api_client: APIClient, job: Job, body: dict[str, Any], field: str
    ) -> None:
        application = Application.objects.create(job=job)
        response = api_client.patch(f"/api/v1/applications/{application.pk}", body, format="json")
        assert response.status_code == 400
        assert field in {detail["field"] for detail in error_of(response)["details"]}

    def test_unknown_application(self, api_client: APIClient) -> None:
        assert api_client.get("/api/v1/applications/999999").status_code == 404
        assert api_client.delete("/api/v1/applications/999999").status_code == 404


@pytest.mark.django_db
class TestInteractions:
    def test_create_edit_delete(self, api_client: APIClient, job: Job) -> None:
        application = Application.objects.create(job=job, status="applied")
        response = api_client.post(
            f"/api/v1/applications/{application.pk}/interactions",
            {"title": " Technical test ", "detail": "Take home"},
            format="json",
        )
        assert response.status_code == 201
        created = data_of(response)
        assert created["title"] == "Technical test"
        assert created["date"] == local_today().isoformat()
        assert created["applicationId"] == application.pk

        edited = data_of(
            api_client.patch(
                f"/api/v1/interactions/{created['id']}",
                {"date": "2026-09-10", "detail": "Submitted"},
                format="json",
            )
        )
        assert (edited["date"], edited["detail"], edited["title"]) == (
            "2026-09-10",
            "Submitted",
            "Technical test",
        )
        assert api_client.delete(f"/api/v1/interactions/{created['id']}").status_code == 204
        assert not Interaction.objects.filter(pk=created["id"]).exists()

    def test_invalid_interactions(self, api_client: APIClient, job: Job) -> None:
        application = Application.objects.create(job=job)
        url = f"/api/v1/applications/{application.pk}/interactions"
        assert api_client.post(url, {"title": ""}, format="json").status_code == 400
        assert api_client.post(url, {"title": "x", "date": "bad"}, format="json").status_code == 400
        assert api_client.post(url, {"title": "x" * 201}, format="json").status_code == 400
        assert api_client.patch("/api/v1/interactions/999999", {}, format="json").status_code == 404


@pytest.mark.django_db
class TestPortugueseTimelineTitles:
    def test_system_titles_are_portuguese(self, api_client: APIClient, job: Job) -> None:
        application_id = data_of(_create(api_client, job.pk, status="interest"))["id"]
        api_client.patch(
            f"/api/v1/applications/{application_id}", {"status": "screening"}, format="json"
        )

        titles = set(
            Interaction.objects.filter(application_id=application_id).values_list(
                "title", flat=True
            )
        )

        assert titles == {"Entrou no funil", "Tenho interesse -> Em triagem"}

    def test_legacy_english_titles_are_rewritten_and_user_titles_kept(self, job: Job) -> None:
        from pipeline.services import translate_legacy_titles

        application = Application.objects.create(job=job, status="applied")
        for title in (
            "Entered the funnel",
            "Application sent through Job Watcher",
            "Interested -> Applied",
            "Withdrawn -> Offer",
            "Applied",
            "Entered the funnel today",
            "Quero aplicar -> Aplicada",
        ):
            Interaction.objects.create(application=application, title=title)

        assert translate_legacy_titles() == 4
        assert translate_legacy_titles() == 0

        titles = sorted(application.interactions.values_list("title", flat=True))
        assert titles == sorted(
            [
                "Entrou no funil",
                "Candidatura enviada pelo Job Watcher",
                "Tenho interesse -> Aplicada",
                "Desisti -> Proposta",
                "Applied",
                "Entered the funnel today",
                "Quero aplicar -> Aplicada",
            ]
        )
