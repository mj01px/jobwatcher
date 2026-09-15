"""The dossier: what the person writes about themselves in Settings.

It is the only source of truth about the candidate in generated text.
"""

from __future__ import annotations

import re

# HTML comments in the dossier are reminders to the person ("TODO: check this
# split"), not information about them. They go away before becoming a prompt:
# sending a task reminder to the model only confuses it.
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

MIN_USEFUL_CHARS = 400


class DossierEmptyError(ValueError):
    """The dossier does not have enough content to write anything specific."""


def clean_dossier(text: str) -> str:
    """Return the dossier ready for the prompt.

    Raises:
        DossierEmptyError: when fewer than ``MIN_USEFUL_CHARS`` useful characters remain.
    """
    cleaned = COMMENT_RE.sub("", text or "").strip()
    if len(cleaned) < MIN_USEFUL_CHARS:
        raise DossierEmptyError(
            f"The dossier has fewer than {MIN_USEFUL_CHARS} useful characters. Without "
            "experience and projects written there, the generated text can only be generic."
        )
    return cleaned
