"""ATS analysis with every AI provider mocked: never calls a real API."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from pipeline.ai import client as ai_client
from pipeline.ai.providers import openrouter
from pipeline.ai.providers.base import (
    Completion,
    LLMNotConfiguredError,
    LLMUnavailableError,
)
from pipeline.ats import resume, schema, service
from pipeline.ats.resume import ResumeError, extract_resume_text
from pipeline.ats.schema import normalize
from pipeline.models import AtsReport
from tests.conftest import MakeJob, data_of, error_of
from watcher.models import Job, Source
from watcher.services.secrets import set_secrets

# A resume long enough to pass the minimum-length check.
RESUME_TEXT = "Desenvolvedor backend, 3 anos com Python, Django, DRF, PostgreSQL e Docker. " * 6


def resume_upload(text: str = RESUME_TEXT, name: str = "cv.txt") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/plain")

RAW_RESULT = {
    "score": 82,
    "verdict": "forte",
    "summary": "Perfil forte para a vaga.",
    "matched_keywords": ["Python", "Django"],
    "missing_keywords": ["Kubernetes"],
    "strengths": ["Entregou um ERP em producao com Django"],
    "gaps": ["Sem experiencia com Kubernetes"],
    "suggestions": ["Destacar o ERP no topo do curriculo"],
}


@pytest.fixture
def job(source: Source, make_job: MakeJob) -> Job:
    return make_job(
        source,
        title="Desenvolvedor Python Pleno",
        description="Buscamos pessoa com Python, Django e Kubernetes.",
        score_tags=["python", "django"],
        seniority="mid",
        work_mode="remote",
    )


# --- HTTP doubles for the OpenRouter client -------------------------------


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200, headers: dict | None = None) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = json.dumps(payload) if isinstance(payload, dict) else str(payload)

    def json(self) -> Any:
        return self._payload


class FakeHttp:
    """Returns queued responses in order and records the posted bodies."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, json: Any = None) -> FakeResponse:
        self.calls.append({"url": url, "json": json})
        page = self.responses.pop(0)
        return page if isinstance(page, FakeResponse) else FakeResponse(page)


def completion_body(content: str, model: str = "vendor/model:free") -> dict[str, Any]:
    return {
        "model": model,
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 40},
    }


class TestNormalize:
    def test_full_result_is_kept(self) -> None:
        result = normalize(RAW_RESULT)
        assert (result.score, result.verdict) == (82, "forte")
        assert result.missing_keywords == ["Kubernetes"]

    def test_score_is_clamped_and_verdict_derived(self) -> None:
        result = normalize({"score": 250})
        assert result.score == 100
        assert result.verdict == "forte"
        low = normalize({"score": "12"})
        assert (low.score, low.verdict) == (12, "fraco")

    def test_invalid_verdict_falls_back_to_score_band(self) -> None:
        assert normalize({"score": 55, "verdict": "amazing"}).verdict == "moderado"

    def test_lists_are_trimmed_deduped_and_capped(self) -> None:
        result = normalize(
            {
                "score": 50,
                "matched_keywords": ["Python", "python", " Django ", 42, ""],
                "suggestions": [f"item {i}" for i in range(30)],
            }
        )
        assert result.matched_keywords == ["Python", "Django"]
        assert len(result.suggestions) == schema.MAX_LIST_ITEMS

    def test_garbage_is_safe(self) -> None:
        result = normalize({})
        assert (result.score, result.verdict, result.matched_keywords) == (0, "fraco", [])


class TestExtractJson:
    def test_plain_object(self) -> None:
        assert ai_client._extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_object(self) -> None:
        assert ai_client._extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_object_within_prose(self) -> None:
        assert ai_client._extract_json('Segue: {"a": 1}. Pronto.') == {"a": 1}

    def test_trailing_commas_are_tolerated(self) -> None:
        assert ai_client._extract_json('{"a": [1, 2,], "b": 3,}') == {"a": [1, 2], "b": 3}

    def test_non_object_raises(self) -> None:
        with pytest.raises(ValueError):
            ai_client._extract_json("[1, 2, 3]")
        with pytest.raises(ValueError):
            ai_client._extract_json("desculpe, sem json")


@pytest.mark.django_db
class TestOpenRouterClient:
    def test_success_maps_text_and_usage(self) -> None:
        http = FakeHttp([completion_body('{"score": 80}')])
        result = openrouter.complete(
            "sys", "user", models=["a/b:free", "c/d:free"], client=http
        )
        assert result == Completion('{"score": 80}', "vendor/model:free", 100, 40)
        assert http.calls[0]["json"]["models"] == ["a/b:free", "c/d:free"]

    def test_models_array_is_capped(self) -> None:
        http = FakeHttp([completion_body("{}")])
        openrouter.complete(
            "s", "u", models=["a", "b", "c", "d", "e"], client=http, sleep=lambda _: None
        )
        assert http.calls[0]["json"]["models"] == ["a", "b", "c"]

    def test_retries_on_429_then_succeeds(self) -> None:
        http = FakeHttp(
            [FakeResponse({}, 429, {"Retry-After": "0"}), completion_body('{"ok": 1}')]
        )
        result = openrouter.complete("s", "u", models=["a/b"], client=http, sleep=lambda _: None)
        assert result.text == '{"ok": 1}'
        assert len(http.calls) == 2

    def test_non_retryable_status_raises(self) -> None:
        http = FakeHttp([FakeResponse({"error": {"message": "bad key"}}, 401)])
        with pytest.raises(LLMUnavailableError, match="HTTP 401"):
            openrouter.complete("s", "u", models=["a/b"], client=http, sleep=lambda _: None)

    def test_gives_up_after_max_attempts(self) -> None:
        http = FakeHttp([FakeResponse({}, 503) for _ in range(openrouter.MAX_ATTEMPTS)])
        with pytest.raises(LLMUnavailableError, match="did not answer after"):
            openrouter.complete("s", "u", models=["a/b"], client=http, sleep=lambda _: None)

    def test_empty_content_is_unavailable(self) -> None:
        http = FakeHttp([completion_body("")])
        with pytest.raises(LLMUnavailableError, match="without text"):
            openrouter.complete("s", "u", models=["a/b"], client=http, sleep=lambda _: None)


@pytest.mark.django_db
class TestProviderFallback:
    def test_no_provider_configured(self) -> None:
        with pytest.raises(LLMNotConfiguredError):
            ai_client.generate_json("sys", "user")

    def test_openrouter_used_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        set_secrets({"openrouter_api_key": "key", "gemini_api_key": "key"})
        monkeypatch.setattr(
            ai_client, "_openrouter_json", lambda s, u: Completion('{"score": 90}', "or", 1, 2)
        )
        monkeypatch.setattr(
            ai_client, "_gemini_json", lambda s, u: pytest.fail("Gemini should not be reached")
        )
        data, completion = ai_client.generate_json("sys", "user")
        assert (data, completion.model) == ({"score": 90}, "or")

    def test_falls_back_to_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        set_secrets({"openrouter_api_key": "key", "gemini_api_key": "key"})

        def boom(_s: str, _u: str) -> Completion:
            raise LLMUnavailableError("rate limited")

        monkeypatch.setattr(ai_client, "_openrouter_json", boom)
        monkeypatch.setattr(
            ai_client, "_gemini_json", lambda s, u: Completion('{"score": 70}', "gemini", 3, 4)
        )
        data, completion = ai_client.generate_json("sys", "user")
        assert (data["score"], completion.model) == (70, "gemini")

    def test_unparseable_answer_is_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        set_secrets({"openrouter_api_key": "key"})
        monkeypatch.setattr(
            ai_client, "_openrouter_json", lambda s, u: Completion("sem json", "or", 1, 2)
        )
        with pytest.raises(LLMUnavailableError):
            ai_client.generate_json("sys", "user")


class TestResumeExtraction:
    def test_plain_text(self) -> None:
        assert "Python" in extract_resume_text("cv.txt", RESUME_TEXT.encode("utf-8"))

    def test_empty_file(self) -> None:
        with pytest.raises(ResumeError, match="empty"):
            extract_resume_text("cv.txt", b"")

    def test_too_short(self) -> None:
        with pytest.raises(ResumeError, match="Almost no text"):
            extract_resume_text("cv.txt", b"too short")

    def test_unsupported_type(self) -> None:
        with pytest.raises(ResumeError, match="Unsupported"):
            extract_resume_text("cv.rtf", RESUME_TEXT.encode("utf-8"))

    def test_too_large(self) -> None:
        with pytest.raises(ResumeError, match="larger than"):
            extract_resume_text("cv.txt", b"x" * (resume.MAX_BYTES + 1))

    def test_pdf_dispatches_to_reader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(resume, "_from_pdf", lambda _content: RESUME_TEXT)
        assert "Python" in extract_resume_text("cv.pdf", b"%PDF-1.4 bytes")


@pytest.mark.django_db
class TestAtsApi:
    def _stub(
        self, monkeypatch: pytest.MonkeyPatch, raw: dict[str, Any] | None = None
    ) -> list[Any]:
        calls: list[Any] = []

        def fake_generate(system: str, user: str) -> tuple[dict[str, Any], Completion]:
            calls.append((system, user))
            return (raw if raw is not None else RAW_RESULT), Completion("x", "vendor/model", 5, 6)

        monkeypatch.setattr(service, "generate_json", fake_generate)
        return calls

    def _post(self, api_client: APIClient, job: Job, **kwargs: Any) -> Any:
        body = kwargs if kwargs else {"resume": resume_upload()}
        return api_client.post(f"/api/v1/jobs/{job.pk}/ats", body, format="multipart")

    def test_get_without_report(self, api_client: APIClient, job: Job) -> None:
        assert data_of(api_client.get(f"/api/v1/jobs/{job.pk}/ats")) is None

    def test_generate_and_replace(
        self, api_client: APIClient, job: Job, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        AtsReport.objects.create(job=job, score=10, verdict="fraco", model="old")
        calls = self._stub(monkeypatch)

        response = self._post(api_client, job, resume=resume_upload(name="meu-cv.txt"))
        assert response.status_code == 201
        data = data_of(response)
        assert set(data) == {
            "id",
            "jobId",
            "score",
            "verdict",
            "summary",
            "matchedKeywords",
            "missingKeywords",
            "strengths",
            "gaps",
            "suggestions",
            "resumeFilename",
            "model",
            "createdAt",
        }
        assert (data["score"], data["verdict"]) == (82, "forte")
        assert data["missingKeywords"] == ["Kubernetes"]
        assert data["resumeFilename"] == "meu-cv.txt"
        assert data["model"] == "vendor/model"
        assert AtsReport.objects.filter(job=job).count() == 1
        # Both the job description (as data) and the resume reached the prompt.
        assert "Kubernetes" in calls[0][1]
        assert "Django" in calls[0][1]
        assert data_of(api_client.get(f"/api/v1/jobs/{job.pk}/ats"))["id"] == data["id"]

    def test_resume_required(self, api_client: APIClient, job: Job) -> None:
        response = api_client.post(f"/api/v1/jobs/{job.pk}/ats", {}, format="multipart")
        assert response.status_code == 400
        assert error_of(response)["code"] == "RESUME_REQUIRED"

    def test_invalid_resume(self, api_client: APIClient, job: Job) -> None:
        response = self._post(api_client, job, resume=resume_upload(text="curto", name="cv.txt"))
        assert response.status_code == 422
        assert error_of(response)["code"] == "RESUME_INVALID"

    def test_ai_not_configured(self, api_client: APIClient, job: Job) -> None:
        response = self._post(api_client, job)
        assert response.status_code == 503
        assert error_of(response)["code"] == "AI_NOT_CONFIGURED"

    def test_ai_unavailable_keeps_previous_report(
        self, api_client: APIClient, job: Job, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_secrets({"openrouter_api_key": "key"})
        AtsReport.objects.create(job=job, score=44, verdict="moderado", model="old")

        def boom(_s: str, _u: str) -> tuple[dict[str, Any], Completion]:
            raise LLMUnavailableError("all providers down")

        monkeypatch.setattr(service, "generate_json", boom)
        response = self._post(api_client, job)
        assert response.status_code == 502
        assert error_of(response)["code"] == "AI_UNAVAILABLE"
        assert AtsReport.objects.get(job=job).score == 44

    def test_concurrent_analysis_is_refused(self, api_client: APIClient, job: Job) -> None:
        from pipeline import views

        views._ats_lock.acquire()
        try:
            response = self._post(api_client, job)
        finally:
            views._ats_lock.release()
        assert response.status_code == 409
        assert error_of(response)["code"] == "ATS_IN_PROGRESS"

    def test_unknown_job(self, api_client: APIClient) -> None:
        assert api_client.get("/api/v1/jobs/999999/ats").status_code == 404
