"""Text normalization and term matching. Pure functions, no Django."""

from __future__ import annotations

import re
import unicodedata

_SPACES_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, strip accents and collapse whitespace, so comparisons are predictable."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return _SPACES_RE.sub(" ", stripped.lower())


def contains(text: str, term: str) -> bool:
    """Match ``term`` on word boundaries.

    This is what allows short terms such as "jr" and "sr" in the profile
    without matching inside "jrxyz" or "srv". Both sides must be normalized.
    """
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
