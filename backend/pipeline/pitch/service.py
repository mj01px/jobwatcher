"""Generation flow: dossier + job -> prompt -> Gemini -> saved pitch."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from pipeline.models import Pitch
from pipeline.pitch.dossier import clean_dossier
from pipeline.pitch.gemini import generate_text
from pipeline.pitch.prompt import INSTRUCTION, build_input
from watcher.models import Job
from watcher.services.preferences import get_dossier, get_gemini_model, get_pitch_max_chars

INSTRUCTION_MAX_LENGTH = 300


def generate_and_save(job: Job, extra_instruction: str = "") -> Pitch:
    """Generate a cover letter and replace the previous one of the job.

    The previous pitch is deleted only after the new text exists, so a Gemini
    failure never takes away the letter already on screen.

    Raises:
        DossierEmptyError: when the dossier is too short.
        GeminiNotConfiguredError: when no API key is configured.
        GeminiUnavailableError: when the API fails.
    """
    dossier = clean_dossier(get_dossier())
    max_chars = get_pitch_max_chars()
    model = get_gemini_model()
    generated = generate_text(
        INSTRUCTION, build_input(job, dossier, max_chars, extra_instruction), model
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
