from __future__ import annotations

from datetime import datetime

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from tests.conftest import ago, data_of, error_of
from watcher.models import CheckRun, CheckRunSource, Source
from watcher.services.runs import write_worker_heartbeat

RUN_KEYS = {
    "id",
    "trigger",
    "status",
    "requestedAt",
    "startedAt",
    "finishedAt",
    "heartbeatAt",
    "sourcesTotal",
    "sourcesChecked",
    "jobsFound",
    "jobsNew",
    "jobsArchived",
    "error",
    "durationSeconds",
    "isStalled",
}


@pytest.mark.django_db
class TestStatus:
    def test_idle_status(self, api_client: APIClient) -> None:
        data = data_of(api_client.get("/api/v1/status"))
        assert data["lastRun"] is None
        assert data["isRunning"] is False
        assert data["isStalled"] is False
        assert data["progress"] is None
        assert data["workerOnline"] is False
        assert datetime.fromisoformat(data["nextRunAt"]) > timezone.now()

    def test_status_sets_the_csrf_cookie(self, api_client: APIClient) -> None:
        response = api_client.get("/api/v1/status")
        assert "csrftoken" in response.cookies

    def test_worker_online_after_heartbeat(self, api_client: APIClient) -> None:
        write_worker_heartbeat()
        assert data_of(api_client.get("/api/v1/status"))["workerOnline"] is True

    def test_queued_run_is_running_without_progress(self, api_client: APIClient) -> None:
        CheckRun.objects.create(trigger=CheckRun.Trigger.MANUAL)
        data = data_of(api_client.get("/api/v1/status"))
        assert data["isRunning"] is True
        assert data["progress"] is None
        assert data["lastRun"]["status"] == "queued"

    def test_running_check_exposes_live_progress(self, api_client: APIClient) -> None:
        run = CheckRun.objects.create(
            trigger=CheckRun.Trigger.SCHEDULED,
            status=CheckRun.Status.RUNNING,
            started_at=ago(4),
            heartbeat_at=ago(2),
            sources_total=2,
        )
        alpha = Source.objects.create(name="Alpha", target="https://alpha.inhire.app/vagas")
        beta = Source.objects.create(kind="gupy", name="python", target="python-status")
        CheckRunSource.objects.create(
            run=run, source=alpha, name="Alpha", position=0, state="done", jobs=7
        )
        CheckRunSource.objects.create(
            run=run, source=beta, kind="gupy", name="python", position=1, state="collecting"
        )

        data = data_of(api_client.get("/api/v1/status"))
        assert data["isRunning"] is True
        assert data["isStalled"] is False
        progress = data["progress"]
        assert progress["runId"] == run.pk
        assert progress["total"] == 2
        assert progress["settled"] == 1
        assert progress["counts"] == {"pending": 0, "collecting": 1, "done": 1, "error": 0}
        assert progress["sources"] == [
            {"sourceId": alpha.pk, "kind": "inhire", "name": "Alpha", "state": "done", "jobs": 7},
            {
                "sourceId": beta.pk,
                "kind": "gupy",
                "name": "python",
                "state": "collecting",
                "jobs": None,
            },
        ]
        assert progress["startedAt"] is not None
        assert progress["updatedAt"] is not None

    def test_stalled_run_is_flagged(self, api_client: APIClient) -> None:
        CheckRun.objects.create(
            trigger=CheckRun.Trigger.MANUAL,
            status=CheckRun.Status.RUNNING,
            started_at=ago(3600),
            heartbeat_at=ago(3600),
        )
        data = data_of(api_client.get("/api/v1/status"))
        assert data["isStalled"] is True
        assert data["lastRun"]["isStalled"] is True


@pytest.mark.django_db
class TestCheckRuns:
    def test_history_row_is_listed(self, api_client: APIClient) -> None:
        started = ago(120)
        CheckRun.objects.create(
            trigger=CheckRun.Trigger.SCHEDULED,
            status=CheckRun.Status.PARTIAL,
            started_at=started,
            finished_at=started + (ago(110) - ago(120)),
            sources_total=30,
            sources_checked=29,
            jobs_found=812,
            jobs_new=3,
            jobs_archived=1,
        )
        runs = data_of(api_client.get("/api/v1/check-runs"))
        assert len(runs) == 1
        assert set(runs[0]) == RUN_KEYS
        assert runs[0]["status"] == "partial"
        assert runs[0]["jobsFound"] == 812
        assert runs[0]["durationSeconds"] == 10.0
        assert runs[0]["isStalled"] is False

    def test_history_is_newest_first_and_limited(self, api_client: APIClient) -> None:
        for index in range(25):
            CheckRun.objects.create(
                trigger=CheckRun.Trigger.SCHEDULED,
                status=CheckRun.Status.SUCCESS,
                requested_at=ago(1000 - index),
            )
        runs = data_of(api_client.get("/api/v1/check-runs"))
        assert len(runs) == 20
        assert runs[0]["requestedAt"] > runs[-1]["requestedAt"]
        assert len(data_of(api_client.get("/api/v1/check-runs?limit=5"))) == 5
        assert len(data_of(api_client.get("/api/v1/check-runs?limit=500"))) == 25

    @pytest.mark.parametrize("value", ["abc", "0", "-1"])
    def test_invalid_limit(self, api_client: APIClient, value: str) -> None:
        response = api_client.get(f"/api/v1/check-runs?limit={value}")
        assert response.status_code == 400
        assert error_of(response)["details"][0]["field"] == "limit"

    def test_post_enqueues_a_manual_run(self, api_client: APIClient) -> None:
        response = api_client.post("/api/v1/check-runs", format="json")
        assert response.status_code == 202
        run = data_of(response)
        assert run["status"] == "queued"
        assert run["trigger"] == "manual"
        assert run["startedAt"] is None

    def test_post_while_active_returns_the_same_run(self, api_client: APIClient) -> None:
        first = data_of(api_client.post("/api/v1/check-runs", format="json"))
        second_response = api_client.post("/api/v1/check-runs", format="json")
        assert second_response.status_code == 202
        assert data_of(second_response)["id"] == first["id"]
        assert CheckRun.objects.count() == 1
