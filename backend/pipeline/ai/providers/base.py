"""Shared provider types and errors.

The errors are provider-neutral on purpose: a view catches ``LLMNotConfigured``
and ``LLMUnavailable`` without caring which provider failed.
"""

from __future__ import annotations

from dataclasses import dataclass


class LLMNotConfiguredError(RuntimeError):
    """No provider has an API key configured."""


class LLMUnavailableError(RuntimeError):
    """Every configured provider failed, timed out or returned unusable output."""


@dataclass(frozen=True)
class Completion:
    """One model answer plus what it cost, whichever provider produced it."""

    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
