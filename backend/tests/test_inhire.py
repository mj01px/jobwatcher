from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import pytest

from watcher.services import inhire
from watcher.services.inhire import (
    CollectionError,
    ScrapedJob,
    collect_company,
    extract_career_page,
    extract_external_id,
    extract_tenant,
    records_to_jobs,
)


def _record(
    job_id: str, name: str, career_page: str, career_page_id: str | None = None
) -> dict[str, Any]:
    return {
        "careerPageId": career_page_id or career_page,
        "displayName": name,
        "jobId": job_id,
        "careerPage": {
            "id": career_page_id or career_page,
            "name": name,
            "careerPage": career_page,
        },
        "link": f"https://tenant.inhire.com.br/vagas/{job_id}",
    }


Handler = Callable[[httpx.Request], httpx.Response]


def _collect(handler: Handler, url: str) -> list[ScrapedJob]:
    async def scenario() -> list[ScrapedJob]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collect_company(client, url)

    return _run(scenario())


def _run(coroutine: Coroutine[Any, Any, list[ScrapedJob]]) -> list[ScrapedJob]:
    return asyncio.run(coroutine)


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inhire, "RETRY_BACKOFF_SECONDS", 0.0)


class TestTenantExtraction:
    def test_plain_tenant_from_host(self) -> None:
        assert extract_tenant("https://lyncas.inhire.app/vagas") == "lyncas"

    def test_tenant_from_nested_career_page_url(self) -> None:
        assert extract_tenant("https://lwsa.inhire.app/octadesk/vagas") == "lwsa"

    def test_tenant_lowercased(self) -> None:
        url = "https://Kooperecooperativa.inhire.app/supero/vagas"
        assert extract_tenant(url) == "kooperecooperativa"

    def test_url_without_host_is_rejected(self) -> None:
        with pytest.raises(CollectionError):
            extract_tenant("not-a-url")


class TestCareerPageIdentification:
    def test_bare_vagas_path_is_the_default_career_page(self) -> None:
        assert extract_career_page("https://lyncas.inhire.app/vagas") == "default"

    def test_trailing_slash_is_still_default(self) -> None:
        assert extract_career_page("https://lyncas.inhire.app/vagas/") == "default"

    def test_octadesk_segment_is_identified(self) -> None:
        assert extract_career_page("https://lwsa.inhire.app/octadesk/vagas") == "octadesk"

    def test_supero_segment_is_identified(self) -> None:
        url = "https://kooperecooperativa.inhire.app/supero/vagas"
        assert extract_career_page(url) == "supero"


class TestExternalId:
    def test_extracts_job_identifier_from_nested_inhire_url(self) -> None:
        url = "https://lwsa.inhire.app/octadesk/vagas/abc-123/python-developer"
        assert extract_external_id(url) == "abc-123"

    def test_rejects_company_listing_url(self) -> None:
        assert extract_external_id("https://example.inhire.app/vagas") is None


class TestRecordConversion:
    def test_records_become_internal_jobs(self) -> None:
        records = [_record("id-1", "Desenvolvedor Python", "default")]
        jobs = records_to_jobs(records, "https://lyncas.inhire.app/vagas", "default")
        assert jobs == [
            ScrapedJob(
                "id-1",
                "Desenvolvedor Python",
                "https://lyncas.inhire.app/vagas/id-1/desenvolvedor-python",
            )
        ]

    def test_link_keeps_the_registered_career_page_segment(self) -> None:
        records = [_record("id-9", "Analista", "octadesk")]
        jobs = records_to_jobs(records, "https://lwsa.inhire.app/octadesk/vagas", "octadesk")
        assert jobs[0].url == "https://lwsa.inhire.app/octadesk/vagas/id-9/analista"

    def test_link_slug_matches_inhire_title_format(self) -> None:
        records = [
            _record(
                "d05c8dc3-5bed-4b88-8e15-c847d3225697",
                "Desenvolvedor(a) Python SR \u2014 Automacao e Integracoes",
                "default",
            )
        ]
        jobs = records_to_jobs(records, "https://zallpy.inhire.app/vagas", "default")
        assert jobs[0].url == (
            "https://zallpy.inhire.app/vagas/"
            "d05c8dc3-5bed-4b88-8e15-c847d3225697/"
            "desenvolvedora-python-sr-automacao-e-integracoes"
        )

    def test_entries_without_id_or_title_are_skipped(self) -> None:
        records = [
            {"jobId": "", "displayName": "No Id", "careerPageId": "default"},
            {"jobId": "id-2", "displayName": "  ", "careerPageId": "default"},
            _record("id-3", "Valid", "default"),
        ]
        jobs = records_to_jobs(records, "https://lyncas.inhire.app/vagas", "default")
        assert [job.external_id for job in jobs] == ["id-3"]

    def test_duplicate_ids_are_collapsed(self) -> None:
        records = [_record("id-1", "First", "default"), _record("id-1", "Second", "default")]
        jobs = records_to_jobs(records, "https://lyncas.inhire.app/vagas", "default")
        assert len(jobs) == 1


class TestCareerPageFilter:
    def test_only_matching_career_page_is_returned(self) -> None:
        records = [
            _record("keep-1", "Octadesk role", "octadesk"),
            _record("drop-1", "Vindi role", "vindi"),
            _record("drop-2", "Default role", "default"),
        ]
        jobs = records_to_jobs(records, "https://lwsa.inhire.app/octadesk/vagas", "octadesk")
        assert [job.external_id for job in jobs] == ["keep-1"]

    def test_default_filter_keeps_only_default_entries(self) -> None:
        records = [
            _record("keep-1", "Default role", "default"),
            _record("drop-1", "Supero role", "supero"),
        ]
        jobs = records_to_jobs(records, "https://kooperecooperativa.inhire.app/vagas", "default")
        assert [job.external_id for job in jobs] == ["keep-1"]


class TestCollectCompany:
    def test_valid_empty_response_yields_no_jobs(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            assert request.headers["X-Tenant"] == "lyncas"
            assert request.headers["Content-Type"] == "application/json"
            assert str(request.url) == inhire.API_URL
            return httpx.Response(200, json=[])

        assert _collect(handler, "https://lyncas.inhire.app/vagas") == []
        assert len(calls) == 1

    def test_http_failure_raises_and_never_returns_empty(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "not found"})

        with pytest.raises(CollectionError):
            _collect(handler, "https://lyncas.inhire.app/vagas")

    def test_transient_errors_are_retried_until_success(self) -> None:
        attempts = {"count": 0}

        def handler(_: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] < 3:
                return httpx.Response(503, text="try later")
            return httpx.Response(200, json=[_record("id-1", "Python Developer", "default")])

        jobs = _collect(handler, "https://lyncas.inhire.app/vagas")
        assert attempts["count"] == 3
        assert [job.external_id for job in jobs] == ["id-1"]

    def test_connection_errors_are_retried(self) -> None:
        attempts = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise httpx.ConnectError("boom", request=request)
            return httpx.Response(200, json=[])

        assert _collect(handler, "https://lyncas.inhire.app/vagas") == []
        assert attempts["count"] == 2

    def test_rate_limit_is_retried(self) -> None:
        attempts = {"count": 0}

        def handler(_: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] == 1:
                return httpx.Response(429, text="slow down")
            return httpx.Response(200, json=[])

        assert _collect(handler, "https://lyncas.inhire.app/vagas") == []
        assert attempts["count"] == 2

    def test_permanent_errors_do_not_retry_forever(self) -> None:
        attempts = {"count": 0}

        def handler(_: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            return httpx.Response(400, text="bad request")

        with pytest.raises(CollectionError):
            _collect(handler, "https://lyncas.inhire.app/vagas")
        assert attempts["count"] == 1

    def test_retry_budget_is_bounded_for_transient_errors(self) -> None:
        attempts = {"count": 0}

        def handler(_: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            return httpx.Response(500, text="server error")

        with pytest.raises(CollectionError):
            _collect(handler, "https://lyncas.inhire.app/vagas")
        assert attempts["count"] == inhire.MAX_ATTEMPTS

    def test_invalid_json_raises(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>not json</html>")

        with pytest.raises(CollectionError):
            _collect(handler, "https://lyncas.inhire.app/vagas")

    def test_non_list_payload_raises(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"jobs": []})

        with pytest.raises(CollectionError):
            _collect(handler, "https://lyncas.inhire.app/vagas")

    def test_unconfirmed_career_page_refuses_to_archive(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[_record("id-1", "Default role", "default")])

        with pytest.raises(CollectionError):
            _collect(handler, "https://lwsa.inhire.app/octadesk/vagas")

    def test_confirmed_career_page_filters_results(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    _record("keep-1", "Octadesk role", "octadesk"),
                    _record("drop-1", "Default role", "default"),
                ],
            )

        jobs = _collect(handler, "https://lwsa.inhire.app/octadesk/vagas")
        assert [job.external_id for job in jobs] == ["keep-1"]
