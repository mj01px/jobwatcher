from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from rest_framework.test import APIClient

from pipeline.models import Application
from tests.conftest import data_of, error_of
from watcher.constants import PAGE_SIZE
from watcher.models import Job, Source


@pytest.fixture
def seed_jobs(source: Source) -> Any:
    def factory(count: int, *, status: str = "active", highlighted: bool = False) -> None:
        base = datetime(2026, 1, 1, tzinfo=UTC)
        Job.objects.bulk_create(
            Job(
                source=source,
                external_id=f"job-{status}-{highlighted}-{index}",
                key=f"inhire:job-{status}-{highlighted}-{index}",
                title=f"Role {index:04d}",
                url=f"https://example.test/vagas/{status}-{index}",
                is_highlighted=highlighted,
                status=status,
                first_seen_at=base + timedelta(minutes=index),
                last_seen_at=base + timedelta(minutes=index),
                archived_at=base if status == "archived" else None,
            )
            for index in range(count)
        )

    return factory


def _page(client: APIClient, query: str = "") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    response = client.get(f"/api/v1/jobs{query}")
    assert response.status_code == 200
    return data_of(response), response.json()["meta"]


@pytest.mark.django_db
class TestJobsPagination:
    def test_zero_results_have_no_pages(self, api_client: APIClient) -> None:
        jobs, meta = _page(api_client)
        assert jobs == []
        assert meta["page"] == 1
        assert meta["perPage"] == PAGE_SIZE
        assert meta["total"] == 0
        assert meta["totalPages"] == 0

    def test_exactly_page_size_results_fit_on_one_page(
        self, api_client: APIClient, seed_jobs: Any
    ) -> None:
        seed_jobs(PAGE_SIZE)
        jobs, meta = _page(api_client)
        assert len(jobs) == PAGE_SIZE
        assert meta["totalPages"] == 1

    def test_one_more_than_page_size_creates_a_second_page(
        self, api_client: APIClient, seed_jobs: Any
    ) -> None:
        seed_jobs(PAGE_SIZE + 1)
        first, meta = _page(api_client)
        assert len(first) == PAGE_SIZE
        assert meta["totalPages"] == 2
        second, _ = _page(api_client, "?page=2")
        assert len(second) == 1

    def test_limit_offset_matches_requested_page(
        self, api_client: APIClient, seed_jobs: Any
    ) -> None:
        seed_jobs(45)
        page_two, _ = _page(api_client, "?page=2")
        page_three, _ = _page(api_client, "?page=3")
        assert len(page_two) == PAGE_SIZE
        assert len(page_three) == 5
        # Newest first: page 1 = 44..25, page 2 = 24..5, page 3 = 4..0.
        titles = [job["title"] for job in page_two]
        assert titles[0] == "Role 0024"
        assert titles[-1] == "Role 0005"

    def test_invalid_page_param_normalizes_to_first_page(
        self, api_client: APIClient, seed_jobs: Any
    ) -> None:
        seed_jobs(25)
        first, _ = _page(api_client)
        for value in ("abc", "0", "-5", ""):
            jobs, meta = _page(api_client, f"?page={value}")
            assert meta["page"] == 1
            assert jobs == first

    def test_page_beyond_total_normalizes_to_last_page(
        self, api_client: APIClient, seed_jobs: Any
    ) -> None:
        seed_jobs(25)
        jobs, meta = _page(api_client, "?page=999")
        assert len(jobs) == 5
        assert meta["page"] == 2

    def test_total_count_is_preserved_across_pages(
        self, api_client: APIClient, seed_jobs: Any
    ) -> None:
        seed_jobs(25)
        assert _page(api_client)[1]["total"] == 25
        assert _page(api_client, "?page=2")[1]["total"] == 25

    def test_single_page_listing(self, api_client: APIClient, seed_jobs: Any) -> None:
        seed_jobs(5)
        assert _page(api_client)[1]["totalPages"] == 1

    def test_seven_pages(self, api_client: APIClient, seed_jobs: Any) -> None:
        seed_jobs(PAGE_SIZE * 7)
        assert _page(api_client)[1]["totalPages"] == 7

    def test_twenty_pages(self, api_client: APIClient, seed_jobs: Any) -> None:
        seed_jobs(PAGE_SIZE * 20)
        _, meta = _page(api_client, "?page=10")
        assert meta["totalPages"] == 20
        assert meta["page"] == 10

    def test_highlighted_listing_is_paginated(self, api_client: APIClient, seed_jobs: Any) -> None:
        seed_jobs(PAGE_SIZE + 3, highlighted=True)
        seed_jobs(4)
        first, meta = _page(api_client, "?view=highlighted")
        assert len(first) == PAGE_SIZE
        assert meta["total"] == PAGE_SIZE + 3
        second, _ = _page(api_client, "?view=highlighted&page=2")
        assert len(second) == 3

    def test_archived_listing_is_paginated(self, api_client: APIClient, seed_jobs: Any) -> None:
        seed_jobs(PAGE_SIZE + 3, status="archived")
        seed_jobs(2)
        first, meta = _page(api_client, "?view=archived")
        assert len(first) == PAGE_SIZE
        assert all(job["status"] == "archived" for job in first)
        second, _ = _page(api_client, "?view=archived&page=2")
        assert len(second) == 3
        assert meta["total"] == PAGE_SIZE + 3

    def test_all_view_excludes_archived(self, api_client: APIClient, seed_jobs: Any) -> None:
        seed_jobs(3, status="archived")
        seed_jobs(2)
        assert _page(api_client, "?view=all")[1]["total"] == 2

    def test_unknown_view_is_a_validation_error(self, api_client: APIClient) -> None:
        response = api_client.get("/api/v1/jobs?view=everything")
        assert response.status_code == 400
        error = error_of(response)
        assert error["code"] == "VALIDATION_ERROR"
        assert error["details"][0]["field"] == "view"

    def test_new_jobs_come_first(self, api_client: APIClient, seed_jobs: Any) -> None:
        seed_jobs(3)
        Job.objects.filter(title="Role 0000").update(arrived_new=True)
        jobs, _ = _page(api_client)
        assert jobs[0]["title"] == "Role 0000"
        assert jobs[0]["isNew"] is True

    def test_title_breaks_ties_case_insensitively(
        self, api_client: APIClient, source: Source
    ) -> None:
        seen = datetime(2026, 1, 1, tzinfo=UTC)
        for title in ("beta", "Alpha", "Gamma"):
            Job.objects.create(
                source=source,
                external_id=title,
                key=f"inhire:{title}",
                title=title,
                url="https://example.test",
                first_seen_at=seen,
                last_seen_at=seen,
            )
        jobs, _ = _page(api_client)
        assert [job["title"] for job in jobs] == ["Alpha", "beta", "Gamma"]


@pytest.mark.django_db
class TestOverview:
    def test_recent_jobs_are_capped_and_not_paginated(
        self, api_client: APIClient, seed_jobs: Any
    ) -> None:
        seed_jobs(PAGE_SIZE * 3, highlighted=True)
        response = api_client.get("/api/v1/overview")
        body = response.json()
        assert response.status_code == 200
        assert len(body["data"]["recentJobs"]) == 8
        assert "totalPages" not in body["meta"]

    def test_stats(
        self, api_client: APIClient, clean_sources: None, seed_jobs: Any, source: Source
    ) -> None:
        seed_jobs(3)
        seed_jobs(2, highlighted=True)
        seed_jobs(4, status="archived")
        Job.objects.filter(status="active", title="Role 0000").update(arrived_new=True)
        Source.objects.create(name="Paused", target="https://paused.inhire.app", is_active=False)
        Source.objects.create(name="Broken", target="https://broken.inhire.app", last_error="boom")
        Source.objects.create(
            name="Gone", target="https://gone.inhire.app", is_removed=True, last_error="old"
        )
        Source.objects.create(
            kind="manual", name="Manual", target="manual", is_hidden=True, last_error="x"
        )

        data = data_of(api_client.get("/api/v1/overview"))
        assert data["jobStats"] == {"active": 5, "new": 2, "highlighted": 2, "archived": 4}
        assert data["sourceStats"] == {"active": 2, "errors": 1}
        assert data["pipelineStats"] == {"active": 0, "overdue": 0, "interviews": 0}
        assert data["overdueApplications"] == []

    def test_jobs_in_the_funnel_leave_stats_and_recent_jobs(
        self, api_client: APIClient, clean_sources: None, seed_jobs: Any
    ) -> None:
        seed_jobs(2, highlighted=True)
        funnel_job = Job.objects.order_by("id").first()
        assert funnel_job is not None
        Application.objects.create(
            job=funnel_job, status="interview", next_step_on=date(2020, 1, 1)
        )
        data = data_of(api_client.get("/api/v1/overview"))
        assert data["jobStats"]["active"] == 1
        assert data["jobStats"]["highlighted"] == 1
        assert funnel_job.pk not in [job["id"] for job in data["recentJobs"]]
        assert data["pipelineStats"] == {"active": 1, "overdue": 1, "interviews": 1}
        assert [app["id"] for app in data["overdueApplications"]] == [funnel_job.application.pk]


@pytest.mark.django_db
class TestV2Listing:
    def test_all_and_highlighted_exclude_jobs_with_an_application(
        self, api_client: APIClient, seed_jobs: Any
    ) -> None:
        seed_jobs(3, highlighted=True)
        job = Job.objects.order_by("id").first()
        assert job is not None
        Application.objects.create(job=job, status="applied")
        assert _page(api_client, "?view=all")[1]["total"] == 2
        assert _page(api_client, "?view=highlighted")[1]["total"] == 2

    def test_highlighted_is_ordered_by_score(self, api_client: APIClient, seed_jobs: Any) -> None:
        seed_jobs(3, highlighted=True)
        for score, title in ((10, "Role 0000"), (90, "Role 0001"), (50, "Role 0002")):
            Job.objects.filter(title=title).update(score=score)
        jobs, _ = _page(api_client, "?view=highlighted")
        assert [job["score"] for job in jobs] == [90, 50, 10]
