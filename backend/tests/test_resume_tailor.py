"""Tailored-resume generator: schema, render, service and endpoint.

The AI is always mocked; the renderer is real, so these also prove the PDF comes
out valid and the candidate's text survives into it.
"""

from __future__ import annotations

import io
import time
from typing import Any

import pytest
from pypdf import PdfReader
from rest_framework.test import APIClient

from pipeline.ai.providers.base import Completion, LLMUnavailableError
from pipeline.resume_tailor import jobs, prompt, schema, service
from pipeline.resume_tailor.render import render_pdf
from pipeline.resume_tailor.schema import Entry, TailoredResume, normalize
from tests.conftest import MakeJob
from watcher.models import Job, Source

RAW = {
    "name": "Mauro Junior",
    "headline": "Back-end Python e SQL",
    "contact_lines": ["Sao Paulo, SP - email@example.com"],
    "summary": "Desenvolvedor back-end com Python, Django e PostgreSQL.",
    "skills": [{"label": "Proficient", "items": ["Python", "Django", "PostgreSQL"]}],
    "experience": [
        {
            "title": "Desenvolvedor Full Stack",
            "meta": "2024 - atual",
            "subtitle": "Freelance",
            "bullets": ["Construi APIs em Django/DRF sobre PostgreSQL."],
        }
    ],
    "projects": [{"title": "Ludex", "meta": "2025", "subtitle": "Java", "bullets": ["App web."]}],
    "education": [{"title": "Eng. de Software", "meta": "2026", "subtitle": "UMC", "bullets": []}],
    "languages": "Portugues - nativo",
}


def pdf_text(data: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


@pytest.fixture
def job(source: Source, make_job: MakeJob) -> Job:
    return make_job(
        source,
        title="Desenvolvedor Python Pleno",
        description="Buscamos Python, Django e PostgreSQL.",
    )


class TestSchema:
    def test_full_payload_is_kept(self) -> None:
        r = normalize(RAW)
        assert r.name == "Mauro Junior"
        assert r.skills[0].items == ["Python", "Django", "PostgreSQL"]
        assert r.experience[0].bullets == ["Construi APIs em Django/DRF sobre PostgreSQL."]
        assert not r.is_empty()

    def test_missing_and_malformed_fields_become_empty(self) -> None:
        r = normalize({"name": "X", "skills": "nope", "experience": [1, 2], "summary": 5})
        assert (r.name, r.summary, r.skills, r.experience) == ("X", "", [], [])

    def test_empty_payload_is_empty(self) -> None:
        assert normalize({}).is_empty()
        assert normalize("not a dict").is_empty()  # type: ignore[arg-type]

    def test_entries_without_a_title_are_dropped(self) -> None:
        r = normalize({"experience": [{"bullets": ["x"]}, {"title": "Dev", "bullets": ["y"]}]})
        assert [e.title for e in r.experience] == ["Dev"]

    def test_lists_are_capped(self) -> None:
        r = normalize({"skills": [{"label": "L", "items": [f"s{i}" for i in range(60)]}]})
        assert len(r.skills[0].items) == schema.MAX_SKILL_ITEMS

    def test_duplicate_items_are_deduped(self) -> None:
        r = normalize({"experience": [{"title": "T", "bullets": ["same"] * 20}]})
        assert r.experience[0].bullets == ["same"]


class TestRender:
    def test_produces_a_valid_pdf_with_the_text(self) -> None:
        data = render_pdf(normalize(RAW))
        assert data.startswith(b"%PDF")
        text = pdf_text(data)
        assert "Mauro Junior" in text
        assert "Python" in text and "Django" in text

    def test_long_resume_flows_to_a_second_page(self) -> None:
        big = TailoredResume(
            name="Mauro Junior",
            summary="Resumo. " * 60,
            experience=[
                Entry(f"Cargo {i}", "2024", "Empresa", ["Fiz muita coisa relevante aqui. " * 4])
                for i in range(12)
            ],
        )
        assert len(PdfReader(io.BytesIO(render_pdf(big))).pages) >= 2

    def test_accented_text_survives(self) -> None:
        resume = TailoredResume(name="Mauro", summary="Automacao e prevencao a fraude: cao")
        assert "fraude" in pdf_text(render_pdf(resume))


class TestService:
    def test_build_filename_is_slugged(self, job: Job) -> None:
        name = service.build_filename(TailoredResume(name="Mauro Júnior"), job)
        assert name.endswith(".pdf")
        assert " " not in name and name == name.lower()

    def test_generate_returns_pdf_and_resume(
        self, job: Job, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            service, "generate_json", lambda s, u: (RAW, Completion("{}", "m", 1, 2))
        )
        pdf, tailored = service.generate_tailored_pdf(job, "resume text")
        assert pdf.startswith(b"%PDF")
        assert tailored.name == "Mauro Junior"

    def test_empty_model_output_raises(self, job: Job, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            service, "generate_json", lambda s, u: ({}, Completion("{}", "m", 1, 2))
        )
        with pytest.raises(LLMUnavailableError):
            service.generate_tailored_pdf(job, "resume text")


class TestPrompt:
    def test_build_input_carries_resume_and_job(self, job: Job) -> None:
        text = prompt.build_input(job, "CURRICULO AQUI com Python")
        assert "CURRICULO AQUI com Python" in text
        assert "Desenvolvedor Python Pleno" in text  # the job title, via describe_job


def _upload(text: str = "Desenvolvedor back-end Python Django PostgreSQL. " * 6) -> Any:
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile("cv.txt", text.encode(), content_type="text/plain")


@pytest.fixture
def clean_store() -> Any:
    jobs._jobs.clear()
    jobs._running = False
    yield
    jobs._jobs.clear()
    jobs._running = False


class TestResumeJobs:
    """The background runner, with the generation itself mocked."""

    def test_start_runs_and_finishes(
        self, job: Job, clean_store: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            jobs, "generate_tailored_pdf", lambda j, t: (b"%PDF-1.4 x", TailoredResume(name="X"))
        )
        monkeypatch.setattr(jobs, "build_filename", lambda r, j: "x.pdf")
        token = jobs.start(job, "resume text")
        result = _await_terminal(token)
        assert (result.status, result.filename) == ("done", "x.pdf")
        assert result.pdf == b"%PDF-1.4 x"

    def test_failure_becomes_an_error_job(
        self, job: Job, clean_store: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(j: Job, t: str) -> Any:
            raise LLMUnavailableError("down")

        monkeypatch.setattr(jobs, "generate_tailored_pdf", boom)
        result = _await_terminal(jobs.start(job, "resume text"))
        assert (result.status, result.error_code) == ("error", "AI_UNAVAILABLE")

    def test_only_one_runs_at_a_time(self, job: Job, clean_store: Any) -> None:
        jobs._running = True  # pretend a generation is in flight
        with pytest.raises(jobs.ResumeBusyError):
            jobs.start(job, "resume text")


def _await_terminal(token: str, tries: int = 100) -> Any:
    for _ in range(tries):
        result = jobs._jobs.get(token)
        if result is not None and result.status != "pending":
            return result
        time.sleep(0.02)
    raise AssertionError("generation did not finish")


@pytest.mark.django_db
class TestEndpoint:
    def _url(self, job: Job) -> str:
        return f"/api/v1/jobs/{job.id}/resume"

    def test_post_starts_and_returns_a_token(
        self, job: Job, clean_store: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jobs, "start", lambda j, t: "tok123")
        res = APIClient().post(self._url(job), {"resume": _upload()}, format="multipart")
        assert res.status_code == 202
        assert res.json()["data"]["token"] == "tok123"

    def test_missing_file_is_400(self, job: Job) -> None:
        res = APIClient().post(self._url(job), {}, format="multipart")
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "RESUME_REQUIRED"

    def test_unreadable_resume_is_422(self, job: Job) -> None:
        res = APIClient().post(self._url(job), {"resume": _upload("short")}, format="multipart")
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "RESUME_INVALID"

    def test_busy_is_409(self, job: Job, monkeypatch: pytest.MonkeyPatch) -> None:
        def busy(j: Job, t: str) -> Any:
            raise jobs.ResumeBusyError("already running")

        monkeypatch.setattr(jobs, "start", busy)
        res = APIClient().post(self._url(job), {"resume": _upload()}, format="multipart")
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "RESUME_IN_PROGRESS"


@pytest.mark.django_db
class TestStatusEndpoint:
    def _url(self, job: Job, token: str) -> str:
        return f"/api/v1/jobs/{job.id}/resume/{token}"

    def test_pending_is_202(self, job: Job, clean_store: Any) -> None:
        jobs._jobs["t"] = jobs.ResumeJob(status="pending")
        res = APIClient().get(self._url(job, "t"))
        assert res.status_code == 202
        assert res.json()["data"]["status"] == "pending"

    def test_done_returns_the_pdf_once(self, job: Job, clean_store: Any) -> None:
        jobs._jobs["t"] = jobs.ResumeJob(status="done", pdf=b"%PDF-1.4 x", filename="cv.pdf")
        res = APIClient().get(self._url(job, "t"))
        assert res.status_code == 200
        assert res["Content-Type"] == "application/pdf"
        assert "cv.pdf" in res["Content-Disposition"]
        assert res.content == b"%PDF-1.4 x"
        # one-shot: the token is gone afterwards.
        assert APIClient().get(self._url(job, "t")).status_code == 404

    def test_unknown_token_is_404(self, job: Job, clean_store: Any) -> None:
        res = APIClient().get(self._url(job, "nope"))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "RESUME_NOT_FOUND"

    @pytest.mark.parametrize(
        ("code", "expected"),
        [("AI_UNAVAILABLE", 502), ("AI_NOT_CONFIGURED", 503), ("INTERNAL_ERROR", 500)],
    )
    def test_error_maps_to_status(
        self, job: Job, clean_store: Any, code: str, expected: int
    ) -> None:
        jobs._jobs["t"] = jobs.ResumeJob(status="error", error_code=code, error_message="x")
        res = APIClient().get(self._url(job, "t"))
        assert res.status_code == expected
        assert res.json()["error"]["code"] == code
