from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from tests.conftest import MakeJob, data_of, error_of
from watcher.models import Job, Source

JOB_KEYS = {
    "id",
    "sourceId",
    "sourceKind",
    "sourceName",
    "companyName",
    "externalId",
    "title",
    "url",
    "location",
    "workMode",
    "seniority",
    "publishedAt",
    "score",
    "scoreTags",
    "scoreGroups",
    "application",
    "status",
    "archiveSource",
    "archiveReason",
    "archiveNote",
    "isHighlighted",
    "isNew",
    "firstSeenAt",
    "lastSeenAt",
    "archivedAt",
    "reopenedAt",
    "firstVisitedAt",
    "lastVisitedAt",
}


@pytest.fixture
def job(source: Source, make_job: MakeJob) -> Job:
    return make_job(source, external_id="job-1", title="Backend Engineer", arrived_new=True)


def _archive(client: APIClient, job_id: int, **body: object) -> object:
    payload: dict[str, object] = {"reason": "not_interested", "note": ""}
    payload.update(body)
    return client.post(f"/api/v1/jobs/{job_id}/archive", payload, format="json")


@pytest.mark.django_db
class TestArchive:
    def test_archive_with_a_manual_reason(self, api_client: APIClient, job: Job) -> None:
        response = _archive(api_client, job.pk)
        assert response.status_code == 200
        job.refresh_from_db()
        assert job.status == Job.Status.ARCHIVED
        assert job.archive_reason == "not_interested"
        assert job.archive_source == Job.ArchiveSource.MANUAL
        assert job.arrived_new is False
        assert job.archived_at is not None

    def test_archive_returns_the_job_in_the_envelope(self, api_client: APIClient, job: Job) -> None:
        response = _archive(api_client, job.pk)
        body = response.json()
        assert set(body) == {"data", "error", "meta"}
        assert body["error"] is None
        assert body["meta"]["requestId"] == response["X-Request-ID"]
        assert set(body["data"]) == JOB_KEYS
        assert body["data"]["status"] == "archived"
        assert body["data"]["companyName"] == "Acme"
        assert body["data"]["sourceKind"] == "inhire"
        assert body["data"]["application"] is None

    def test_archive_rejects_invalid_reason(self, api_client: APIClient, job: Job) -> None:
        response = _archive(api_client, job.pk, reason="not-a-real-reason")
        assert response.status_code == 422
        assert error_of(response)["code"] == "INVALID_ARCHIVE_REASON"

    def test_archive_rejects_the_legacy_applied_reason(
        self, api_client: APIClient, job: Job
    ) -> None:
        response = _archive(api_client, job.pk, reason="applied")
        assert response.status_code == 422
        assert error_of(response)["code"] == "INVALID_ARCHIVE_REASON"
        job.refresh_from_db()
        assert job.status == Job.Status.ACTIVE

    def test_archive_rejects_system_reason(self, api_client: APIClient, job: Job) -> None:
        response = _archive(api_client, job.pk, reason="source_removed")
        assert response.status_code == 422

    def test_archive_unknown_job_returns_404(self, api_client: APIClient) -> None:
        response = _archive(api_client, 999_999)
        assert response.status_code == 404
        assert error_of(response)["code"] == "NOT_FOUND"

    def test_note_is_trimmed_and_truncated(self, api_client: APIClient, job: Job) -> None:
        data = data_of(_archive(api_client, job.pk, reason="other", note="  " + "x" * 600))
        assert data["archiveNote"] == "x" * 500

    def test_blank_note_is_stored_as_null(self, api_client: APIClient, job: Job) -> None:
        data = data_of(_archive(api_client, job.pk, note="   "))
        assert data["archiveNote"] is None

    def test_non_string_note_is_a_validation_error(self, api_client: APIClient, job: Job) -> None:
        response = _archive(api_client, job.pk, note=42)
        assert response.status_code == 400
        assert error_of(response)["details"] == [
            {"field": "note", "issue": "note must be a string."}
        ]


@pytest.mark.django_db
class TestRestore:
    def test_undo_restore_clears_fields_without_marking_reopened(
        self, api_client: APIClient, job: Job
    ) -> None:
        _archive(api_client, job.pk, note="later")
        response = api_client.post(f"/api/v1/jobs/{job.pk}/restore", format="json")
        assert response.status_code == 200
        job.refresh_from_db()
        assert job.status == Job.Status.ACTIVE
        assert job.archive_reason is None
        assert job.archive_source is None
        assert job.archive_note is None
        assert job.archived_at is None
        assert job.reopened_at is None
        assert data_of(response)["status"] == "active"

    def test_restore_unknown_job_returns_404(self, api_client: APIClient) -> None:
        response = api_client.post("/api/v1/jobs/999999/restore", format="json")
        assert response.status_code == 404


@pytest.mark.django_db
class TestVisit:
    def test_visit_marks_job_as_visited(self, api_client: APIClient, job: Job) -> None:
        response = api_client.post(f"/api/v1/jobs/{job.pk}/visit", format="json")
        assert response.status_code == 200
        job.refresh_from_db()
        assert job.first_visited_at is not None
        assert job.last_visited_at is not None
        assert data_of(response)["firstVisitedAt"] is not None

    def test_revisiting_job_preserves_first_visit_timestamp(
        self, api_client: APIClient, job: Job
    ) -> None:
        api_client.post(f"/api/v1/jobs/{job.pk}/visit", format="json")
        job.refresh_from_db()
        first_visited = job.first_visited_at
        last_visited = job.last_visited_at

        api_client.post(f"/api/v1/jobs/{job.pk}/visit", format="json")
        job.refresh_from_db()
        assert job.first_visited_at == first_visited
        assert job.last_visited_at is not None
        assert last_visited is not None
        assert job.last_visited_at >= last_visited

    def test_visit_unknown_job_returns_404(self, api_client: APIClient) -> None:
        response = api_client.post("/api/v1/jobs/999999/visit", format="json")
        assert response.status_code == 404

    def test_visited_timestamps_show_up_in_the_listing(
        self, api_client: APIClient, job: Job
    ) -> None:
        before = data_of(api_client.get("/api/v1/jobs"))
        entry = next(item for item in before if item["id"] == job.pk)
        assert entry["firstVisitedAt"] is None

        api_client.post(f"/api/v1/jobs/{job.pk}/visit", format="json")

        after = data_of(api_client.get("/api/v1/jobs"))
        entry = next(item for item in after if item["id"] == job.pk)
        assert entry["firstVisitedAt"] is not None
        assert entry["lastVisitedAt"] is not None


@pytest.mark.django_db
class TestJobDetail:
    def test_detail_includes_description_and_pitch(self, api_client: APIClient, job: Job) -> None:
        from pipeline.models import Pitch

        Job.objects.filter(pk=job.pk).update(description="Full description")
        data = data_of(api_client.get(f"/api/v1/jobs/{job.pk}"))
        assert set(data) == JOB_KEYS | {"description", "pitch"}
        assert data["description"] == "Full description"
        assert data["pitch"] is None

        Pitch.objects.create(job=job, text="Hello", model="m", max_chars=1200)
        pitch = data_of(api_client.get(f"/api/v1/jobs/{job.pk}"))["pitch"]
        assert pitch["text"] == "Hello"
        assert pitch["chars"] == 5

    def test_unknown_job(self, api_client: APIClient) -> None:
        assert api_client.get("/api/v1/jobs/999999").status_code == 404


@pytest.mark.django_db
class TestManualJob:
    def test_creates_scored_manual_job(self, api_client: APIClient) -> None:
        response = api_client.post(
            "/api/v1/jobs",
            {
                "title": " Desenvolvedor Python Junior ",
                "url": "https://careers.example.com/jobs/1",
                "companyName": "Example",
                "location": "Recife",
                "workMode": "hybrid",
                "description": "Django e PostgreSQL",
            },
            format="json",
        )
        assert response.status_code == 201
        data = data_of(response)
        assert data["title"] == "Desenvolvedor Python Junior"
        assert data["sourceKind"] == "manual"
        assert data["companyName"] == "Example"
        assert data["workMode"] == "hybrid"
        assert data["seniority"] == "junior"
        assert data["score"] == 44
        assert data["isNew"] is False
        assert data["isHighlighted"] is True
        job = Job.objects.get(pk=data["id"])
        assert job.key.startswith("manual:")
        assert job.source.is_hidden is True

    def test_same_url_conflicts(self, api_client: APIClient) -> None:
        body = {"title": "Role", "url": "https://careers.example.com/jobs/2"}
        assert api_client.post("/api/v1/jobs", body, format="json").status_code == 201
        body["url"] = " HTTPS://careers.example.com/jobs/2 "
        response = api_client.post("/api/v1/jobs", body, format="json")
        assert response.status_code == 409
        assert error_of(response)["code"] == "CONFLICT"

    @pytest.mark.parametrize(
        ("body", "field"),
        [
            ({"url": "https://x.test/1"}, "title"),
            ({"title": "Role", "url": "not a url"}, "url"),
            ({"title": "Role", "url": "https://x.test/1", "workMode": "moon"}, "workMode"),
            ({"title": "Role", "url": "https://x.test/1", "seniority": "god"}, "seniority"),
            ({"title": "Role", "url": "https://x.test/1", "companyName": 5}, "companyName"),
        ],
    )
    def test_invalid_manual_job(
        self, api_client: APIClient, body: dict[str, object], field: str
    ) -> None:
        response = api_client.post("/api/v1/jobs", body, format="json")
        assert response.status_code == 400
        assert field in {detail["field"] for detail in error_of(response)["details"]}
