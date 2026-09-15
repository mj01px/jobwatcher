"""Apply a scoring profile to a job: score, tags, seniority and work mode.

Pure functions: no models, no database, testable without Django.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from watcher.scoring.profile import (
    PROFILE,
    SENIORITY_TERMS,
    WORK_MODE_TERMS,
    YEARS_PENALTIES,
    YEARS_RE,
    ScoringProfile,
)
from watcher.scoring.text import contains, normalize


@dataclass(frozen=True)
class Classification:
    score: int = 0
    tags: list[str] = field(default_factory=list)
    # Keys of the positive groups that matched, in profile order.
    groups: list[str] = field(default_factory=list)
    seniority: str = "unknown"
    work_mode: str = "unknown"


def score_groups(
    title: str, body: str, profile: ScoringProfile | None = None
) -> tuple[int, list[str], list[str]]:
    """``(score, tags, groups)`` of an already normalized title and body.

    The title weighs double. Tags and groups only collect positive groups, so a
    penalty can never make a job look like it matches the stack.
    """
    score = 0
    tags: list[str] = []
    groups: list[str] = []

    for key, group in (profile or PROFILE).items():
        weight = int(group["weight"])
        for term in group["terms"]:
            term_normalized = normalize(term)
            if not term_normalized:
                continue
            in_title = contains(title, term_normalized)
            if not (in_title or contains(body, term_normalized)):
                continue
            score += weight * 2 if in_title else weight
            if weight > 0:
                if term_normalized not in tags:
                    tags.append(term_normalized)
                groups.append(key)
            # One hit per group is enough: repetition must not inflate the score.
            break

    return score, tags, groups


def score_text(
    title: str, body: str, profile: ScoringProfile | None = None
) -> tuple[int, list[str]]:
    """``(score, tags)`` of an already normalized title and body."""
    score, tags, _groups = score_groups(title, body, profile)
    return score, tags


def years_penalty(text: str) -> int:
    """Penalty for the required years of experience, 0 when none is asked.

    Normalizes first: otherwise "vivencia" never matches "vivência", which is
    how the word shows up in jobs written in Portuguese.
    """
    match = YEARS_RE.search(normalize(text))
    if not match:
        return 0
    years = int(match.group(1))
    for threshold, penalty in YEARS_PENALTIES:
        if years >= threshold:
            return penalty
    return 0


def detect_seniority(text: str) -> str:
    for level, terms in SENIORITY_TERMS:
        if any(contains(text, term) for term in terms):
            return level
    return "unknown"


def detect_work_mode(text: str) -> str:
    for mode, terms in WORK_MODE_TERMS:
        if any(contains(text, term) for term in terms):
            return mode
    return "unknown"


def classify(
    title: str,
    description: str = "",
    company: str = "",
    location: str = "",
    profile: ScoringProfile | None = None,
) -> Classification:
    title_normalized = normalize(title)
    body_normalized = normalize(f"{description} {company} {location}")

    score, tags, groups = score_groups(title_normalized, body_normalized, profile)
    score += years_penalty(f"{title} {description}")

    full = f"{title_normalized} {normalize(description)}"
    return Classification(
        score=score,
        tags=tags,
        groups=groups,
        seniority=detect_seniority(full),
        work_mode=detect_work_mode(f"{full} {normalize(location)}"),
    )
