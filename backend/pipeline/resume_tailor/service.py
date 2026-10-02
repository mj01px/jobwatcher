"""Tailoring flow: resume text + job -> prompt -> AI JSON -> rendered PDF."""

from __future__ import annotations

import re
import unicodedata

from pipeline.ai.client import generate_json
from pipeline.ai.providers.base import LLMUnavailableError
from pipeline.resume_tailor.prompt import INSTRUCTION, build_input
from pipeline.resume_tailor.render import render_pdf
from pipeline.resume_tailor.schema import TailoredResume, normalize
from watcher.models import Job

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = _SLUG_RE.sub("-", normalized.lower()).strip("-")
    return slug or fallback


def build_filename(resume: TailoredResume, job: Job) -> str:
    """A readable download name: candidate + company (or job title)."""
    who = _slug(resume.name, "curriculo")
    where = _slug(job.company_name or job.title, "vaga")
    return f"{who}-{where}.pdf"[:120]


def generate_tailored_pdf(job: Job, resume_text: str) -> tuple[bytes, TailoredResume]:
    """Tailor the resume to the job and render it.

    The resume text is already extracted and validated by the caller.

    Raises:
        LLMNotConfiguredError: when no AI provider is configured.
        LLMUnavailableError: when every provider failed, returned bad JSON, or
            returned nothing usable to render.
    """
    data, _completion = generate_json(INSTRUCTION, build_input(job, resume_text))
    resume = normalize(data)
    if resume.is_empty():
        raise LLMUnavailableError("The AI returned nothing usable to build a resume.")
    return render_pdf(resume), resume
