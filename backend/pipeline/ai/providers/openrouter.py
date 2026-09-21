"""OpenRouter client: one key, many models, OpenAI-compatible endpoint.

We send the whole ``models`` list in one request: OpenRouter tries them in order
and falls back on its side when a model is rate limited or down, and the response
reports which model actually answered. Transient HTTP failures (429, 5xx, network)
are retried here with exponential backoff, honouring ``Retry-After``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx
from django.conf import settings

from pipeline.ai.providers.base import (
    Completion,
    LLMNotConfiguredError,
    LLMUnavailableError,
)
from watcher.services.secrets import OPENROUTER_API_KEY, get_secret

logger = logging.getLogger(__name__)

# A normal generation is a few seconds; the ceiling stops a hung request from
# blocking the request thread forever.
TIMEOUT_SECONDS = 90.0
# The ATS answer is a small JSON object, but it now carries a short reasoning
# field. A generous ceiling avoids cutting the JSON off mid-object.
MAX_OUTPUT_TOKENS = 2000
# Low temperature: the ATS should be repeatable, not creative.
DEFAULT_TEMPERATURE = 0.2
MAX_ATTEMPTS = 3
# OpenRouter rejects a request whose ``models`` array has more than this many
# entries. We keep the primary plus the first fallbacks and drop the rest.
MAX_MODELS = 3
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# Cap the backoff so a long Retry-After never parks the thread past the timeout.
MAX_BACKOFF_SECONDS = 20.0
# Attribution headers OpenRouter uses for its rankings (optional, harmless).
_REFERER = "https://github.com/mj01px/jobwatcher"
_TITLE = "Job Watcher"


def api_key() -> str:
    key = get_secret(OPENROUTER_API_KEY)
    if not key:
        raise LLMNotConfiguredError(
            "No OpenRouter API key configured. Create one at openrouter.ai/keys "
            "and save it in Settings."
        )
    return key


def build_client() -> httpx.Client:
    return httpx.Client(
        base_url=settings.OPENROUTER_BASE_URL,
        timeout=httpx.Timeout(TIMEOUT_SECONDS, connect=10.0),
        headers={
            "Authorization": f"Bearer {api_key()}",
            "HTTP-Referer": _REFERER,
            "X-Title": _TITLE,
            "Content-Type": "application/json",
        },
    )


def _message_text(message: dict[str, Any]) -> str:
    """The assistant text, whether ``content`` is a string or a list of parts."""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in {"text", None}
        ]
        return "".join(parts).strip()
    return ""


def _parse(payload: Any, requested: Sequence[str]) -> Completion:
    if not isinstance(payload, dict):
        raise LLMUnavailableError("OpenRouter returned an unexpected body.")
    # OpenRouter surfaces upstream provider errors inside a 200 body too.
    error = payload.get("error")
    if error:
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise LLMUnavailableError(f"OpenRouter error: {message}")
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        raise LLMUnavailableError("OpenRouter answered without any choice.")
    text = _message_text(choices[0].get("message") or {})
    if not text:
        finish = choices[0].get("finish_reason", "unknown")
        raise LLMUnavailableError(f"OpenRouter answered without text (finish_reason: {finish}).")
    usage = payload.get("usage") or {}
    return Completion(
        text=text,
        model=str(payload.get("model") or (requested[0] if requested else "openrouter")),
        input_tokens=int(usage.get("prompt_tokens", 0) or 0),
        output_tokens=int(usage.get("completion_tokens", 0) or 0),
    )


def _retry_delay(attempt: int, response: httpx.Response | None) -> float:
    if response is not None:
        header = response.headers.get("Retry-After", "").strip()
        if header.isdigit():
            return min(float(header), MAX_BACKOFF_SECONDS)
    return min(2.0**attempt, MAX_BACKOFF_SECONDS)


def complete(
    system: str,
    user: str,
    *,
    models: Sequence[str],
    response_format: dict[str, Any] | None = None,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Completion:
    """Send one chat completion and return the text, retrying transient failures.

    Raises:
        LLMNotConfiguredError: when no API key is configured (via ``build_client``).
        LLMUnavailableError: on non-transient HTTP errors, empty output or after
            exhausting retries.
    """
    if not models:
        raise LLMUnavailableError("No OpenRouter model configured.")
    payload: dict[str, Any] = {
        "models": list(models)[:MAX_MODELS],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_output_tokens,
        "temperature": temperature,
    }
    if response_format is not None:
        payload["response_format"] = response_format

    own_client = client is None
    http = client or build_client()
    last_error = "unknown error"
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            response: httpx.Response | None = None
            try:
                response = http.post("/chat/completions", json=payload)
            except (httpx.TimeoutException, httpx.TransportError) as error:
                last_error = str(error) or type(error).__name__
                logger.warning("OpenRouter transport error (attempt %d): %s", attempt, last_error)
            else:
                if response.status_code < 400:
                    return _parse(response.json(), payload["models"])
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    detail = response.text[:200]
                    raise LLMUnavailableError(
                        f"OpenRouter returned HTTP {response.status_code}: {detail}"
                    )
                last_error = f"HTTP {response.status_code}"
                logger.warning("OpenRouter %s (attempt %d)", last_error, attempt)
            if attempt < MAX_ATTEMPTS:
                sleep(_retry_delay(attempt, response))
        raise LLMUnavailableError(
            f"OpenRouter did not answer after {MAX_ATTEMPTS} attempts ({last_error}). "
            "It may be the free-tier daily limit: wait and try again."
        )
    finally:
        if own_client:
            http.close()
