"""The one entry point features call: JSON generation with provider fallback.

Order: OpenRouter first (one key, many free models, tried as a list), then Gemini.
Each provider's text is parsed defensively into JSON, so a free model that ignores
``response_format`` still works as long as it returns the object we asked for.
A provider that is unconfigured is skipped; one that fails or returns unparseable
text moves us to the next. Only when all fail do we raise.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pipeline.ai.providers import openrouter
from pipeline.ai.providers.base import (
    Completion,
    LLMNotConfiguredError,
    LLMUnavailableError,
)
from watcher.services.preferences import get_gemini_model, get_openrouter_models
from watcher.services.secrets import GEMINI_API_KEY, OPENROUTER_API_KEY, is_configured

logger = logging.getLogger(__name__)

# Broadly supported "JSON mode". Full json_schema strict mode is honoured by few
# free models; json_object plus defensive parsing works across many more.
_JSON_RESPONSE_FORMAT = {"type": "json_object"}
# Appended to the Gemini fallback input: it has no JSON mode in our port, so we
# ask for the object explicitly and rely on the same defensive parser.
_GEMINI_JSON_REMINDER = "\n\nResponda APENAS com o objeto JSON pedido, sem texto em volta."
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
# Free models often emit a trailing comma before a closing } or ], which is valid
# JS but not JSON. Dropping it lets us keep the OpenRouter answer instead of
# falling through to the next provider.
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _loads(candidate: str) -> Any:
    try:
        return json.loads(candidate)
    except ValueError:
        return json.loads(_TRAILING_COMMA_RE.sub(r"\1", candidate))


def _extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object out of a model answer, tolerating fences, prose and trailing commas."""
    candidate = text.strip()
    fenced = _FENCE_RE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        parsed = _loads(candidate)
    except ValueError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise
        parsed = _loads(candidate[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Model returned JSON that is not an object.")
    return parsed


def _openrouter_json(system: str, user: str) -> Completion:
    """Try the configured models in fixed order, one request each, and return the
    first whose text parses as a JSON object.

    One request per model in a fixed order, rather than handing OpenRouter the
    whole list and letting its router pick, is what keeps a score reproducible:
    the same model answers whenever it is up, instead of whichever the router
    happened to route to that minute. Measured, model choice was the whole source
    of the ATS variance (a model that scored ~15-20 points apart from the next).
    A model that is unavailable or returns unparseable JSON hands off to the next
    in line; only when none answer does OpenRouter fail and Gemini take over.
    """
    models = get_openrouter_models()[: openrouter.MAX_MODELS]
    if not models:
        raise LLMUnavailableError("No OpenRouter model configured.")
    last_error: Exception = LLMUnavailableError("No OpenRouter model answered.")
    for model in models:
        try:
            completion = openrouter.complete(
                system, user, models=[model], response_format=_JSON_RESPONSE_FORMAT
            )
            _extract_json(completion.text)  # accept this model only if its JSON parses
            return completion
        except (LLMUnavailableError, ValueError) as error:
            logger.warning("OpenRouter model %s unusable: %s", model, error)
            last_error = error
    raise LLMUnavailableError(str(last_error))


def _gemini_json(system: str, user: str) -> Completion:
    # Imported lazily: keeps google-genai optional and avoids an import cycle.
    from pipeline.pitch.gemini import (
        GeminiNotConfiguredError,
        GeminiUnavailableError,
        generate_text,
    )

    try:
        generated = generate_text(system, user + _GEMINI_JSON_REMINDER, get_gemini_model())
    except GeminiNotConfiguredError as error:
        raise LLMNotConfiguredError(str(error)) from error
    except GeminiUnavailableError as error:
        raise LLMUnavailableError(str(error)) from error
    return Completion(
        text=generated.text,
        model=generated.model,
        input_tokens=generated.input_tokens,
        output_tokens=generated.output_tokens,
    )


def generate_json(system: str, user: str) -> tuple[dict[str, Any], Completion]:
    """Return the parsed JSON object and the completion that produced it.

    Raises:
        LLMNotConfiguredError: when no provider has an API key.
        LLMUnavailableError: when every configured provider failed or returned
            text we could not parse as a JSON object.
    """
    providers = []
    if is_configured(OPENROUTER_API_KEY):
        providers.append(("OpenRouter", _openrouter_json))
    if is_configured(GEMINI_API_KEY):
        providers.append(("Gemini", _gemini_json))
    if not providers:
        raise LLMNotConfiguredError(
            "No AI provider configured. Add an OpenRouter key (recommended) or a "
            "Gemini key in Settings."
        )

    last_error: Exception | None = None
    for name, call in providers:
        try:
            completion = call(system, user)
            return _extract_json(completion.text), completion
        except LLMNotConfiguredError as error:  # pragma: no cover - guarded above
            last_error = error
        except (LLMUnavailableError, ValueError) as error:
            logger.warning("%s failed to produce JSON: %s", name, error)
            last_error = error
    raise LLMUnavailableError(
        f"No AI provider could produce a valid answer ({last_error})."
    ) from last_error
