"""Gupy and GitHub collectors (ported from Vaggio), without network."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from watcher.services import github, gupy
from watcher.services.collection import CollectionError, github_key, gupy_key, manual_key


def no_sleep(_seconds: float) -> None:
    return None


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(str(self.status_code))

    def json(self) -> Any:
        return self._payload


class FakeClient:
    """Returns pages in order and records the params of every call."""

    def __init__(self, pages: list[Any]) -> None:
        self.pages = list(pages)
        self.calls: list[dict[str, Any]] = []

    def get(
        self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> FakeResponse:
        self.calls.append({"url": url, "headers": headers or {}, **(params or {})})
        if not self.pages:
            raise AssertionError("page requested past the end: the collector did not stop")
        page = self.pages.pop(0)
        return page if isinstance(page, FakeResponse) else FakeResponse(page)


def gupy_page(count: int, first_id: int = 0) -> dict[str, Any]:
    return {
        "pagination": {"total": 100, "limit": 100, "offset": 0},
        "data": [
            {
                "id": first_id + index,
                "name": f"Desenvolvedor {first_id + index}",
                "jobUrl": f"https://acme.gupy.io/job/{first_id + index}",
            }
            for index in range(count)
        ],
    }


def issues(count: int, first: int = 0) -> list[dict[str, Any]]:
    return [
        {
            "title": f"Vaga {number}",
            "body": "",
            "html_url": f"https://github.com/o/r/issues/{number}",
            "number": number,
            "created_at": "2026-09-01T10:00:00Z",
        }
        for number in range(first, first + count)
    ]


class TestKeys:
    def test_key_shapes(self) -> None:
        assert gupy_key("42", "https://x") == "gupy:42"
        assert gupy_key("", " https://x/1 ") == "gupy:https://x/1"
        assert (
            github_key("https://github.com/o/r/issues/1")
            == "github:https://github.com/o/r/issues/1"
        )
        assert manual_key(" HTTPS://X.test/1 ") == manual_key("https://x.test/1")
        assert manual_key("https://x.test/1").startswith("manual:")


class TestGupyPagination:
    def test_sweeps_the_whole_term(self) -> None:
        client = FakeClient([gupy_page(100, 0), gupy_page(100, 100), gupy_page(50, 200)])
        result = gupy.collect_term(client, "desenvolvedor", api="https://gupy.test", sleep=no_sleep)
        assert len(result.jobs) == 250
        assert [call["offset"] for call in client.calls] == [0, 100, 200]
        assert {call["limit"] for call in client.calls} == {100}
        assert {call["jobName"] for call in client.calls} == {"desenvolvedor"}
        assert result.authoritative is False
        assert result.warning is None

    def test_does_not_trust_the_envelope_total(self) -> None:
        # Gupy pins total=100 with a high limit even when 650 exist.
        client = FakeClient([gupy_page(100, 0), gupy_page(30, 100)])
        result = gupy.collect_term(client, "desenvolvedor", api="https://gupy.test", sleep=no_sleep)
        assert len(result.jobs) == 130
        assert len(client.calls) == 2

    def test_stops_on_short_page(self) -> None:
        client = FakeClient([gupy_page(40)])
        assert len(gupy.collect_term(client, "python", api="x", sleep=no_sleep).jobs) == 40
        assert len(client.calls) == 1

    def test_stops_on_empty_page(self) -> None:
        client = FakeClient([gupy_page(100), gupy_page(0)])
        assert len(gupy.collect_term(client, "python", api="x", sleep=no_sleep).jobs) == 100
        assert len(client.calls) == 2

    def test_respects_the_page_lock(self) -> None:
        client = FakeClient([gupy_page(100, index * 100) for index in range(10)])
        result = gupy.collect_term(client, "python", api="x", max_pages=3, sleep=no_sleep)
        assert len(result.jobs) == 300
        assert len(client.calls) == 3

    def test_limit_is_capped_at_the_api_ceiling(self) -> None:
        client = FakeClient([gupy_page(10)])
        gupy.collect_term(client, "python", api="x", per_page=500, sleep=no_sleep)
        assert client.calls[0]["limit"] == 100

    def test_first_page_failure_raises(self) -> None:
        class BrokenClient:
            def get(self, *args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("503")

        with pytest.raises(CollectionError, match="503"):
            gupy.collect_term(BrokenClient(), "python", api="x", sleep=no_sleep)

    def test_retries_a_page_before_giving_up(self) -> None:
        """A page that chokes once must not take the rest of the term."""

        class UnstableClient:
            def __init__(self) -> None:
                self.offsets: list[int] = []
                self.failed = False

            def get(self, url: str, params: dict[str, Any] | None = None) -> FakeResponse:
                assert params is not None
                self.offsets.append(params["offset"])
                if params["offset"] == 100 and not self.failed:
                    self.failed = True
                    raise RuntimeError("timeout")
                count = 30 if params["offset"] >= 200 else 100
                return FakeResponse(gupy_page(count, params["offset"]))

        client = UnstableClient()
        waits: list[float] = []
        result = gupy.collect_term(client, "desenvolvedor", api="x", sleep=waits.append)
        assert len(result.jobs) == 230
        assert client.offsets == [0, 100, 100, 200]
        assert waits == [1.0]
        assert result.warning is None

    def test_later_page_failure_keeps_jobs_with_a_warning(self) -> None:
        class FailsSecondPage:
            def get(self, url: str, params: dict[str, Any] | None = None) -> FakeResponse:
                assert params is not None
                if params["offset"] == 100:
                    raise RuntimeError("503")
                return FakeResponse(gupy_page(100))

        result = gupy.collect_term(FailsSecondPage(), "python", api="x", sleep=no_sleep)
        assert len(result.jobs) == 100
        assert result.warning is not None
        assert "offset 100" in result.warning

    def test_duplicate_ids_are_collapsed(self) -> None:
        client = FakeClient([{"data": gupy_page(5)["data"] + gupy_page(5)["data"]}])
        assert len(gupy.collect_term(client, "python", api="x", sleep=no_sleep).jobs) == 5


class TestGupyParsing:
    def test_item_becomes_job(self) -> None:
        item = {
            "id": 42,
            "name": "Desenvolvedor Back-end Junior",
            "jobUrl": "https://acme.gupy.io/job/42",
            "careerPageName": "Acme",
            "city": "Sao Paulo",
            "state": "SP",
            "isRemoteWork": True,
            "publishedDate": "2026-08-29T10:00:00Z",
            "description": "<p>Python &amp; Django</p>",
            "skills": [{"name": "python"}, {"name": "sql"}],
        }
        job = gupy.parse_item(item)
        assert job is not None
        assert job.title == "Desenvolvedor Back-end Junior"
        assert job.company_name == "Acme"
        assert job.location == "Remoto, Sao Paulo, SP"
        assert "Python & Django" in job.description
        assert job.key == "gupy:42"
        assert job.external_id == "42"
        assert job.published_at is not None and job.published_at.year == 2026

    def test_item_without_url_is_ignored(self) -> None:
        assert gupy.parse_item({"name": "Dev"}) is None

    def test_envelope_variants(self) -> None:
        assert gupy.extract_list({"data": [1, 2]}) == [1, 2]
        assert gupy.extract_list({"results": [3]}) == [3]
        assert gupy.extract_list([4]) == [4]
        assert gupy.extract_list({"other": "thing"}) == []

    def test_strip_html(self) -> None:
        assert gupy.strip_html("<p>Ola &amp;   mundo</p>") == "Ola & mundo"


class TestGithubParsing:
    def test_issue_becomes_job(self) -> None:
        issue = {
            "title": "[CLT] Pessoa Desenvolvedora Python Junior",
            "body": "Empresa: Acme\n\nVaga remota.",
            "html_url": "https://github.com/backend-br/vagas/issues/1",
            "number": 1,
            "labels": [{"name": "CLT"}, {"name": "Remoto"}],
            "created_at": "2026-08-30T12:00:00Z",
        }
        job = github.parse_issue(issue, "backend-br/vagas")
        assert job is not None
        assert job.title == "[CLT] Pessoa Desenvolvedora Python Junior"
        assert job.company_name == "Acme"
        assert job.external_id == "backend-br/vagas#1"
        assert job.key == "github:https://github.com/backend-br/vagas/issues/1"
        assert "CLT, Remoto" in job.description
        assert job.published_at is not None and job.published_at.year == 2026

    def test_rules_issue_and_pull_requests_are_ignored(self) -> None:
        assert (
            github.parse_issue({"title": "Regras para publicar vagas", "html_url": "x"}, "r")
            is None
        )
        assert (
            github.parse_issue({"title": "Vaga", "html_url": "x", "pull_request": {}}, "r") is None
        )

    def test_company_is_blank_without_template(self) -> None:
        assert github.company_from_body("Vaga bacana, sem template") == ""

    def test_company_with_markdown(self) -> None:
        assert github.company_from_body("**Empresa**: *Acme*") == "Acme"
        assert github.company_from_body("**Empresa:** Acme") == "Acme"

    def test_too_long_company_is_dropped(self) -> None:
        assert github.company_from_body(f"Empresa: {'x' * 200}") == ""


class TestGithubPaginationAndAuthority:
    def test_short_page_is_authoritative(self) -> None:
        client = FakeClient([issues(30)])
        result = github.collect_repo(client, "o/r", sleep=no_sleep)
        assert len(result.jobs) == 30
        assert len(client.calls) == 1
        assert result.authoritative is True
        assert client.calls[0]["state"] == "open"
        assert client.calls[0]["per_page"] == 100

    def test_reads_until_the_short_page(self) -> None:
        client = FakeClient([issues(100, 0), issues(100, 100), issues(5, 200)])
        result = github.collect_repo(client, "o/r", sleep=no_sleep)
        assert len(result.jobs) == 205
        assert [call["page"] for call in client.calls] == [1, 2, 3]
        assert result.authoritative is True

    def test_empty_first_page_is_an_authoritative_empty_listing(self) -> None:
        result = github.collect_repo(FakeClient([[]]), "o/r", sleep=no_sleep)
        assert (result.jobs, result.authoritative) == ([], True)

    def test_hitting_the_page_limit_is_not_authoritative(self) -> None:
        client = FakeClient([issues(100, 0), issues(100, 100), issues(100, 200)])
        result = github.collect_repo(client, "o/r", sleep=no_sleep)
        assert len(result.jobs) == 300
        assert result.authoritative is False

    def test_later_page_failure_is_partial_and_not_authoritative(self) -> None:
        client = FakeClient([issues(100, 0), FakeResponse({"message": "nope"}, status_code=403)])
        result = github.collect_repo(client, "o/r", sleep=no_sleep)
        assert len(result.jobs) == 100
        assert result.authoritative is False
        assert result.warning is not None and "403" in result.warning

    def test_first_page_failure_raises(self) -> None:
        client = FakeClient([FakeResponse({"message": "rate limited"}, status_code=403)])
        with pytest.raises(CollectionError, match="403"):
            github.collect_repo(client, "o/r", sleep=no_sleep)

    def test_transient_errors_are_retried(self) -> None:
        class Flaky:
            def __init__(self) -> None:
                self.calls = 0

            def get(self, *args: Any, **kwargs: Any) -> FakeResponse:
                self.calls += 1
                if self.calls == 1:
                    raise httpx.ConnectError("boom")
                if self.calls == 2:
                    return FakeResponse([], status_code=502)
                return FakeResponse(issues(2))

        client = Flaky()
        waits: list[float] = []
        result = github.collect_repo(client, "o/r", sleep=waits.append)
        assert len(result.jobs) == 2
        assert waits == [1.0, 2.0]

    def test_bad_payload_raises(self) -> None:
        with pytest.raises(CollectionError, match="unexpected payload"):
            github.collect_repo(FakeClient([{"message": "x"}]), "o/r", sleep=no_sleep)

    def test_token_goes_in_the_authorization_header(self) -> None:
        client = FakeClient([issues(1)])
        github.collect_repo(client, "o/r", token=" ghp_x ", sleep=no_sleep)
        assert client.calls[0]["headers"]["Authorization"] == "Bearer ghp_x"
        assert "Authorization" not in github.request_headers("")
