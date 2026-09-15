from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from tests.conftest import MakeJob, data_of, error_of
from watcher.models import Job, Source

SOURCE_KEYS = {
    "id",
    "kind",
    "name",
    "target",
    "isActive",
    "lastCheckedAt",
    "lastError",
    "activeJobs",
    "highlightedJobs",
    "applications",
    "lastRunJobs",
    "createdAt",
    "updatedAt",
}


@pytest.mark.django_db
class TestSourceList:
    def test_lists_visible_sources_by_kind_then_name_with_active_jobs(
        self, api_client: APIClient, clean_sources: None, make_job: MakeJob
    ) -> None:
        beta = Source.objects.create(name="beta", target="https://beta.inhire.app/vagas")
        Source.objects.create(name="Alpha", target="https://alpha.inhire.app/vagas")
        Source.objects.create(kind="github", name="backend-br/vagas", target="backend-br/vagas")
        Source.objects.create(kind="gupy", name="python", target="python")
        Source.objects.create(name="Gone", target="https://gone.inhire.app/vagas", is_removed=True)
        Source.objects.create(kind="manual", name="Manual", target="manual", is_hidden=True)
        make_job(beta)
        make_job(beta)
        make_job(beta, status=Job.Status.ARCHIVED)

        sources = data_of(api_client.get("/api/v1/sources"))
        assert [(item["kind"], item["name"]) for item in sources] == [
            ("inhire", "Alpha"),
            ("inhire", "beta"),
            ("gupy", "python"),
            ("github", "backend-br/vagas"),
        ]
        assert set(sources[0]) == SOURCE_KEYS
        assert sources[1]["activeJobs"] == 2
        assert sources[0]["activeJobs"] == 0

    def test_seeded_sources_are_listed(self, api_client: APIClient) -> None:
        sources = data_of(api_client.get("/api/v1/sources"))
        kinds = [item["kind"] for item in sources]
        assert kinds.count("inhire") == 74
        assert kinds.count("gupy") == 38
        assert kinds.count("github") == 4
        assert "manual" not in kinds

    def test_companies_route_is_gone(self, api_client: APIClient) -> None:
        assert api_client.get("/api/v1/companies").status_code == 404


@pytest.mark.django_db
class TestSourceCreate:
    def test_creates_inhire_source_trimming_input(self, api_client: APIClient) -> None:
        response = api_client.post(
            "/api/v1/sources",
            {"kind": "inhire", "name": "  New Co ", "target": " https://newco.inhire.app/vagas/ "},
            format="json",
        )
        assert response.status_code == 201
        data = data_of(response)
        assert data["name"] == "New Co"
        assert data["target"] == "https://newco.inhire.app/vagas"
        assert data["isActive"] is True
        assert data["activeJobs"] == 0

    def test_creates_gupy_and_github_sources(self, api_client: APIClient) -> None:
        gupy = data_of(
            api_client.post(
                "/api/v1/sources",
                {"kind": "gupy", "name": "Django", "target": "  django  "},
                format="json",
            )
        )
        assert (gupy["kind"], gupy["target"]) == ("gupy", "django")
        github = data_of(
            api_client.post(
                "/api/v1/sources",
                {"kind": "github", "name": "Python BR", "target": "pythonbrasil/vagas"},
                format="json",
            )
        )
        assert (github["kind"], github["target"]) == ("github", "pythonbrasil/vagas")

    @pytest.mark.parametrize(
        ("body", "field"),
        [
            ({"kind": "inhire", "name": "", "target": "https://x.inhire.app/vagas"}, "name"),
            ({"kind": "inhire", "name": "   ", "target": "https://x.inhire.app/vagas"}, "name"),
            ({"kind": "inhire", "name": "X", "target": "https://example.com/vagas"}, "target"),
            ({"kind": "inhire", "name": "X", "target": "ftp://x.inhire.app/vagas"}, "target"),
            ({"kind": "inhire", "name": "X", "target": "https://inhire.app.evil.com"}, "target"),
            ({"kind": "inhire", "name": "X"}, "target"),
            ({"kind": "gupy", "name": "X", "target": "a"}, "target"),
            ({"kind": "gupy", "name": "X", "target": "x" * 101}, "target"),
            ({"kind": "github", "name": "X", "target": "not a repo"}, "target"),
            ({"kind": "github", "name": "X", "target": "owner/repo/extra"}, "target"),
            ({"kind": "manual", "name": "X", "target": "manual"}, "kind"),
            ({"name": "X", "target": "python"}, "kind"),
        ],
    )
    def test_invalid_input(self, api_client: APIClient, body: dict[str, str], field: str) -> None:
        response = api_client.post("/api/v1/sources", body, format="json")
        assert response.status_code == 400
        error = error_of(response)
        assert error["code"] == "VALIDATION_ERROR"
        assert field in {detail["field"] for detail in error["details"]}

    def test_existing_target_is_reactivated_and_renamed(self, api_client: APIClient) -> None:
        removed = Source.objects.create(
            name="Old",
            target="https://again.inhire.app/vagas",
            is_active=False,
            is_removed=True,
        )
        response = api_client.post(
            "/api/v1/sources",
            {"kind": "inhire", "name": "Again", "target": "https://again.inhire.app/vagas"},
            format="json",
        )
        assert response.status_code == 201
        removed.refresh_from_db()
        assert (removed.name, removed.is_active, removed.is_removed) == ("Again", True, False)
        assert data_of(response)["id"] == removed.pk

    def test_existing_gupy_term_is_upserted(self, api_client: APIClient) -> None:
        response = api_client.post(
            "/api/v1/sources", {"kind": "gupy", "name": "Python", "target": "python"}, format="json"
        )
        assert response.status_code == 201
        assert Source.objects.filter(kind="gupy", target="python").count() == 1
        assert data_of(response)["name"] == "Python"


@pytest.mark.django_db
class TestSourcePatch:
    def test_pause_and_resume(self, api_client: APIClient, source: Source) -> None:
        data = data_of(
            api_client.patch(f"/api/v1/sources/{source.pk}", {"isActive": False}, format="json")
        )
        assert data["isActive"] is False
        data = data_of(
            api_client.patch(f"/api/v1/sources/{source.pk}", {"isActive": True}, format="json")
        )
        assert data["isActive"] is True

    def test_edit_name_and_target(self, api_client: APIClient, source: Source) -> None:
        response = api_client.patch(
            f"/api/v1/sources/{source.pk}",
            {"name": " Acme Labs ", "target": "https://acme.inhire.app/labs/vagas/"},
            format="json",
        )
        assert response.status_code == 200
        data = data_of(response)
        assert data["name"] == "Acme Labs"
        assert data["target"] == "https://acme.inhire.app/labs/vagas"

    def test_target_is_validated_with_the_source_kind(self, api_client: APIClient) -> None:
        repo = Source.objects.create(kind="github", name="repo", target="owner/repo")
        response = api_client.patch(
            f"/api/v1/sources/{repo.pk}", {"target": "https://x.inhire.app"}, format="json"
        )
        assert response.status_code == 400

    def test_target_of_another_source_conflicts(
        self, api_client: APIClient, source: Source
    ) -> None:
        Source.objects.create(name="Other", target="https://other.inhire.app/vagas")
        response = api_client.patch(
            f"/api/v1/sources/{source.pk}",
            {"target": "https://other.inhire.app/vagas"},
            format="json",
        )
        assert response.status_code == 409
        assert error_of(response)["code"] == "CONFLICT"

    def test_same_target_is_not_a_conflict(self, api_client: APIClient, source: Source) -> None:
        response = api_client.patch(
            f"/api/v1/sources/{source.pk}", {"target": source.target}, format="json"
        )
        assert response.status_code == 200

    def test_invalid_values(self, api_client: APIClient, source: Source) -> None:
        response = api_client.patch(
            f"/api/v1/sources/{source.pk}",
            {"isActive": "yes", "target": "https://example.com"},
            format="json",
        )
        assert response.status_code == 400
        fields = {detail["field"] for detail in error_of(response)["details"]}
        assert fields == {"isActive", "target"}

    def test_removed_and_hidden_sources_are_not_found(
        self, api_client: APIClient, source: Source
    ) -> None:
        Source.objects.filter(pk=source.pk).update(is_removed=True)
        hidden = Source.objects.get(kind="manual")
        for pk in (source.pk, hidden.pk):
            response = api_client.patch(f"/api/v1/sources/{pk}", {"name": "X"}, format="json")
            assert response.status_code == 404


@pytest.mark.django_db
class TestSourceDelete:
    def test_soft_removes_and_archives_active_jobs(
        self, api_client: APIClient, source: Source, make_job: MakeJob
    ) -> None:
        active = make_job(source, arrived_new=True)
        manual = make_job(
            source,
            status=Job.Status.ARCHIVED,
            archive_source=Job.ArchiveSource.MANUAL,
            archive_reason="not_interested",
        )

        response = api_client.delete(f"/api/v1/sources/{source.pk}")
        assert response.status_code == 204
        assert response.content == b""

        source.refresh_from_db()
        active.refresh_from_db()
        manual.refresh_from_db()
        assert (source.is_active, source.is_removed) == (False, True)
        assert active.status == Job.Status.ARCHIVED
        assert active.archive_source == Job.ArchiveSource.SOURCE
        assert active.archive_reason == "source_removed"
        assert active.arrived_new is False
        assert active.archived_at is not None
        assert manual.archive_reason == "not_interested"
        assert manual.archive_source == Job.ArchiveSource.MANUAL

    def test_delete_unknown_source(self, api_client: APIClient) -> None:
        assert api_client.delete("/api/v1/sources/999999").status_code == 404
