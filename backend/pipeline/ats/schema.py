"""The ATS result shape and the normalisation of raw model JSON into it.

Free models are inconsistent: a 0-10 score, a verdict in English, duplicated or
empty list items, a giant paragraph where a phrase was asked. Normalisation is
what makes the feature trustworthy regardless of which model answered, so it
clamps, de-duplicates, trims and, when the model omits the verdict, derives it
from the score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Score bands, also used to fill a missing/invalid verdict from the score.
STRONG_MIN = 70
MODERATE_MIN = 40
VERDICTS = ("forte", "moderado", "fraco")

MAX_SCORE = 100
SUMMARY_MAX = 600
ITEM_MAX = 200
KEYWORD_MAX = 60
# Enough to be useful, capped so a runaway model cannot bloat the row or the UI.
MAX_LIST_ITEMS = 15


@dataclass(frozen=True)
class AtsResult:
    score: int
    verdict: str
    summary: str
    matched_keywords: list[str] = field(default_factory=list)
    missing_keywords: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def _clamp_score(value: Any) -> int:
    try:
        score = round(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, min(MAX_SCORE, score))


def verdict_from_score(score: int) -> str:
    if score >= STRONG_MIN:
        return "forte"
    if score >= MODERATE_MIN:
        return "moderado"
    return "fraco"


def _clean_list(value: Any, *, item_limit: int) -> list[str]:
    """A list of unique, non-empty, trimmed strings, order preserved and capped."""
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            continue
        item = " ".join(raw.split())[:item_limit].strip()
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            result.append(item)
        if len(result) >= MAX_LIST_ITEMS:
            break
    return result


def _text(value: Any, limit: int) -> str:
    return " ".join(value.split())[:limit].strip() if isinstance(value, str) else ""


def normalize(data: dict[str, Any]) -> AtsResult:
    """Turn raw model JSON into a validated ``AtsResult`` (never raises)."""
    score = _clamp_score(data.get("score"))
    verdict = data.get("verdict")
    verdict = verdict.strip().casefold() if isinstance(verdict, str) else ""
    if verdict not in VERDICTS:
        verdict = verdict_from_score(score)
    return AtsResult(
        score=score,
        verdict=verdict,
        summary=_text(data.get("summary"), SUMMARY_MAX),
        matched_keywords=_clean_list(data.get("matched_keywords"), item_limit=KEYWORD_MAX),
        missing_keywords=_clean_list(data.get("missing_keywords"), item_limit=KEYWORD_MAX),
        strengths=_clean_list(data.get("strengths"), item_limit=ITEM_MAX),
        gaps=_clean_list(data.get("gaps"), item_limit=ITEM_MAX),
        suggestions=_clean_list(data.get("suggestions"), item_limit=ITEM_MAX),
    )
