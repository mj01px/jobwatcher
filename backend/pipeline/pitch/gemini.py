"""Gemini client (Google AI Studio), ported from Vaggio.

Call shape confirmed against the API on 2026-09-02: ``client.interactions.create``
with ``model``, ``system_instruction``, ``input`` and ``generation_config`` as
keyword arguments, and the response carrying ``output_text`` and ``usage``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from watcher.services.secrets import GEMINI_API_KEY, get_secret

logger = logging.getLogger(__name__)

# Writing a cover letter is not a deep reasoning problem, and the low level
# already spends about 200 thinking tokens. Going higher burns free tier quota
# without better text.
THINKING_LEVEL = "low"
# Generous ceiling: ``max_output_tokens`` also counts thinking tokens, and hitting
# the limit cuts the text mid sentence.
MAX_OUTPUT_TOKENS = 4000
# Without an explicit ceiling the call hangs forever when the API chokes or
# rate limits. A normal generation takes 3 to 15 seconds.
TIMEOUT_SECONDS = 90.0


class GeminiNotConfiguredError(RuntimeError):
    """No API key configured."""


class GeminiUnavailableError(RuntimeError):
    """The API could not be reached, timed out or did not return usable text."""


@dataclass(frozen=True)
class GeneratedText:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int


def _client() -> Any:
    api_key = get_secret(GEMINI_API_KEY)
    if not api_key:
        raise GeminiNotConfiguredError(
            "No Gemini API key configured. Create one at aistudio.google.com "
            "and save it in Settings."
        )
    try:
        from google import genai
    except ImportError as error:  # pragma: no cover - declared dependency
        raise GeminiUnavailableError("The google-genai package is not installed.") from error
    return genai.Client(api_key=api_key)


def generate_text(instruction: str, prompt_input: str, model: str) -> GeneratedText:
    """Send the instruction and input, return the text and its token cost.

    Raises:
        GeminiNotConfiguredError: when no API key is configured.
        GeminiUnavailableError: on API failure, timeout or empty output.
    """
    client = _client()
    try:
        response = client.interactions.create(
            model=model,
            system_instruction=instruction,
            input=prompt_input,
            generation_config={
                "thinking_level": THINKING_LEVEL,
                "max_output_tokens": MAX_OUTPUT_TOKENS,
            },
            timeout=TIMEOUT_SECONDS,
        )
    except Exception as error:
        logger.warning("Gemini call failed (model %s): %s", model, type(error).__name__)
        if "timeout" in type(error).__name__.lower() or isinstance(error, TimeoutError):
            raise GeminiUnavailableError(
                f"Gemini did not answer within {TIMEOUT_SECONDS:.0f}s. It may be the free "
                "tier limit: wait a minute and try again."
            ) from error
        raise GeminiUnavailableError(f"Gemini did not answer: {error}") from error

    text = (getattr(response, "output_text", "") or "").strip()
    if not text:
        # Happens when a safety filter blocks the model or the token ceiling eats
        # the output.
        raise GeminiUnavailableError(
            f"Gemini answered without text (status: {getattr(response, 'status', 'unknown')})."
        )
    usage = getattr(response, "usage", None)
    return GeneratedText(
        text=text,
        model=model,
        input_tokens=getattr(usage, "total_input_tokens", 0) or 0,
        output_tokens=getattr(usage, "total_output_tokens", 0) or 0,
        thinking_tokens=getattr(usage, "total_thought_tokens", 0) or 0,
    )
