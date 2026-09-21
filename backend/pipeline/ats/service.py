"""Analysis flow: resume text + job -> prompt -> AI JSON -> saved AtsReport."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from pipeline.ai.client import generate_json
from pipeline.ats.prompt import INSTRUCTION, build_input
from pipeline.ats.schema import normalize
from pipeline.models import AtsReport
from watcher.models import Job

RESUME_FILENAME_MAX = 255


def analyze_and_save(job: Job, resume_text: str, resume_filename: str = "") -> AtsReport:
    """Score a resume against a job and replace the job's previous report.

    The resume text is already extracted and validated by the caller. The old
    report is deleted only after the new one exists, so an AI failure never
    leaves the job without the analysis it had before.

    Raises:
        LLMNotConfiguredError: when no AI provider is configured.
        LLMUnavailableError: when every provider failed or returned bad JSON.
    """
    data, completion = generate_json(INSTRUCTION, build_input(job, resume_text))
    result = normalize(data)
    now = timezone.now()
    with transaction.atomic():
        report = AtsReport.objects.create(
            job=job,
            score=result.score,
            verdict=result.verdict,
            summary=result.summary,
            matched_keywords=result.matched_keywords,
            missing_keywords=result.missing_keywords,
            strengths=result.strengths,
            gaps=result.gaps,
            suggestions=result.suggestions,
            resume_filename=resume_filename[:RESUME_FILENAME_MAX],
            model=completion.model,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            created_at=now,
            updated_at=now,
        )
        AtsReport.objects.filter(job=job).exclude(pk=report.pk).delete()
    return report
