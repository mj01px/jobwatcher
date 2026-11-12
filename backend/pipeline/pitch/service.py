"""Generation flow: dossier + job -> prompt -> AI provider -> saved pitch."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from pipeline.ai.client import generate_text
from pipeline.models import Pitch
from pipeline.pitch.dossier import clean_dossier
from pipeline.pitch.prompt import INSTRUCTION, build_input
from watcher.models import Job
from watcher.services.preferences import get_dossier, get_pitch_max_chars

INSTRUCTION_MAX_LENGTH = 300
# The POST is synchronous and the desktop webview aborts a request after ~60s,
# showing a generic error even when the server is about to answer. The whole
# fallback chain has to finish inside that.
BUDGET_SECONDS = 50.0
# A healthy Gemini writes the letter in 3 to 15s; past this it is busy, and the
# rest of the budget (35s) goes to OpenRouter.
GEMINI_SHARE_SECONDS = 15.0


def generate_and_save(job: Job, extra_instruction: str = "") -> Pitch:
    """Generate a cover letter and replace the previous one of the job.

    The previous pitch is deleted only after the new text exists, so a provider
    failure never takes away the letter already on screen.

    Raises:
        DossierEmptyError: when the dossier is too short.
        LLMNotConfiguredError: when no AI provider has an API key.
        LLMUnavailableError: when every provider failed or ran out of time.
    """
    dossier = clean_dossier(get_dossier())
    max_chars = get_pitch_max_chars()
    generated = generate_text(
        INSTRUCTION,
        build_input(job, dossier, max_chars, extra_instruction),
        budget_seconds=BUDGET_SECONDS,
        gemini_share_seconds=GEMINI_SHARE_SECONDS,
    )
    now = timezone.now()
    with transaction.atomic():
        pitch = Pitch.objects.create(
            job=job,
            text=generated.text,
            model=generated.model,
            instruction=extra_instruction.strip()[:INSTRUCTION_MAX_LENGTH],
            max_chars=max_chars,
            input_tokens=generated.input_tokens,
            output_tokens=generated.output_tokens,
            thinking_tokens=generated.thinking_tokens,
            created_at=now,
            updated_at=now,
        )
        Pitch.objects.filter(job=job).exclude(pk=pitch.pk).delete()
    return pitch
