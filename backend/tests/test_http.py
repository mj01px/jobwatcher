from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from django.test import Client
from rest_framework.test import APIClient

from tests.conftest import MakeJob, data_of, error_of
from watcher.models import Job, Source


def test_healthcheck(client: Client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["time"]


@pytest.mark.django_db
class TestEnvelope:
    def test_request_id_is_generated(self, api_client: APIClient) -> None:
        response = api_client.get("/api/v1/overview")
        assert response["X-Request-ID"]
        assert response.json()["meta"]["requestId"] == response["X-Request-ID"]

    def test_incoming_request_id_is_reused(self, api_client: APIClient) -> None:
        response = api_client.get("/api/v1/overview", HTTP_X_REQUEST_ID="trace-123")
        assert response["X-Request-ID"] == "trace-123"
        assert response.json()["meta"]["requestId"] == "trace-123"

    def test_unsafe_incoming_request_id_is_replaced(self, api_client: APIClient) -> None:
        response = api_client.get("/api/v1/overview", HTTP_X_REQUEST_ID="bad id\nx")
        assert response["X-Request-ID"] != "bad id\nx"

    def test_unknown_api_route_uses_error_envelope(self, api_client: APIClient) -> None:
        response = api_client.get("/api/v1/nothing-here")
        assert response.status_code == 404
        error = error_of(response)
        assert error == {"code": "NOT_FOUND", "message": "Resource not found", "details": []}

    def test_wrong_method(self, api_client: APIClient) -> None:
        response = api_client.delete("/api/v1/overview")
        assert response.status_code == 405
        assert error_of(response)["code"] == "METHOD_NOT_ALLOWED"

    def test_malformed_json(self, api_client: APIClient) -> None:
        response = api_client.put(
            "/api/v1/settings/profile", "{not json", content_type="application/json"
        )
        assert response.status_code == 400
        assert error_of(response)["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
class TestCsrf:
    def test_unsafe_request_without_token_is_rejected(
        self, csrf_client: APIClient, source: Source, make_job: MakeJob
    ) -> None:
        job = make_job(source)
        response = csrf_client.post(f"/api/v1/jobs/{job.pk}/visit", format="json")
        assert response.status_code == 403
        assert error_of(response)["code"] == "CSRF_FAILED"
        job.refresh_from_db()
        assert job.first_visited_at is None

    def test_token_from_status_cookie_is_accepted(
        self, csrf_client: APIClient, source: Source, make_job: MakeJob
    ) -> None:
        job = make_job(source)
        token = csrf_client.get("/api/v1/status").cookies["csrftoken"].value
        response = csrf_client.post(
            f"/api/v1/jobs/{job.pk}/archive",
            {"reason": "not_interested"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        assert response.status_code == 200
        assert data_of(response)["status"] == Job.Status.ARCHIVED

    def test_safe_methods_do_not_need_a_token(self, csrf_client: APIClient) -> None:
        assert csrf_client.get("/api/v1/jobs").status_code == 200


@pytest.mark.django_db
class TestSpa:
    def test_index_is_served_for_client_routes(
        self, client: Client, settings: Any, tmp_path: Path
    ) -> None:
        (tmp_path / "index.html").write_text("<div id=root></div>", encoding="utf-8")
        settings.FRONTEND_DIST = tmp_path
        for route in ("/", "/jobs/highlighted", "/applications", "/activity"):
            response = client.get(route)
            assert response.status_code == 200
            assert b"<div id=root></div>" in b"".join(response.streaming_content)
            assert "csrftoken" in response.cookies

    def test_missing_build_returns_helpful_404(
        self, client: Client, settings: Any, tmp_path: Path
    ) -> None:
        settings.FRONTEND_DIST = tmp_path / "missing"
        response = client.get("/sources")
        assert response.status_code == 404
        assert b"not built" in response.content
