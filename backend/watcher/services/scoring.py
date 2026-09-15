"""Scoring profile stored in settings, and applying it to jobs."""

from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from watcher.constants import (
    DEFAULT_HIGHLIGHT_MIN_SCORE,
    DEFAULT_HIGHLIGHT_STACK_GROUPS,
    HIGHLIGHT_MIN_SCORE_KEY,
    HIGHLIGHT_STACK_GROUPS_KEY,
    SCORING_PROFILE_KEY,
)
from watcher.models import Job
from watcher.scoring import PROFILE, ScoringProfile, classify
from watcher.services.preferences import get_setting, set_setting

RESCORE_BATCH_SIZE = 500
RESCORED_FIELDS = [
    "score",
    "score_tags",
    "score_groups",
    "seniority",
    "work_mode",
    "is_highlighted",
]


@dataclass(frozen=True)
class ScoringContext:
    profile: ScoringProfile
    min_score: int
    stack_groups: tuple[str, ...] = DEFAULT_HIGHLIGHT_STACK_GROUPS


def saved_profile() -> ScoringProfile | None:
    value = get_setting(SCORING_PROFILE_KEY)
    return value if isinstance(value, dict) and value else None


def get_min_score() -> int:
    value = get_setting(HIGHLIGHT_MIN_SCORE_KEY, DEFAULT_HIGHLIGHT_MIN_SCORE)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return DEFAULT_HIGHLIGHT_MIN_SCORE


def get_stack_groups() -> tuple[str, ...]:
    value = get_setting(HIGHLIGHT_STACK_GROUPS_KEY)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    return DEFAULT_HIGHLIGHT_STACK_GROUPS


def load_scoring() -> ScoringContext:
    return ScoringContext(
        profile=saved_profile() or PROFILE,
        min_score=get_min_score(),
        stack_groups=get_stack_groups(),
    )


def scoring_payload() -> dict[str, Any]:
    profile = saved_profile()
    return {
        "groups": copy.deepcopy(profile or PROFILE),
        "minScore": get_min_score(),
        "stackGroups": list(get_stack_groups()),
        "isDefault": profile is None,
    }


def is_highlight(score: int, groups: Iterable[str], context: ScoringContext) -> bool:
    """Score at or above the minimum and, when a stack is configured, a stack hit."""
    if score < context.min_score:
        return False
    if not context.stack_groups:
        return True
    return not set(context.stack_groups).isdisjoint(groups)


def apply_classification(job: Job, context: ScoringContext) -> None:
    """Score a job in memory from its title, description, company and location."""
    result = classify(job.title, job.description, job.company_name, job.location, context.profile)
    job.score = result.score
    job.score_tags = result.tags
    job.score_groups = result.groups
    job.seniority = result.seniority
    job.work_mode = result.work_mode
    job.is_highlighted = is_highlight(result.score, result.groups, context)


def rescore_all(context: ScoringContext | None = None) -> tuple[int, int]:
    """Rescore every job with the current profile.

    Returns:
        ``(evaluated, changed)``, where changed counts score or highlight changes.
    """
    context = context or load_scoring()
    total = changed = 0
    batch: list[Job] = []
    queryset = Job.objects.only(
        "id",
        "title",
        "description",
        "company_name",
        "location",
        *RESCORED_FIELDS,
    ).order_by("id")
    with transaction.atomic():
        for job in queryset.iterator(chunk_size=RESCORE_BATCH_SIZE):
            before = (job.score, job.is_highlighted, job.seniority, job.work_mode)
            apply_classification(job, context)
            total += 1
            if before != (job.score, job.is_highlighted, job.seniority, job.work_mode):
                changed += 1
            batch.append(job)
            if len(batch) >= RESCORE_BATCH_SIZE:
                Job.objects.bulk_update(batch, RESCORED_FIELDS)
                batch = []
        if batch:
            Job.objects.bulk_update(batch, RESCORED_FIELDS)
    return total, changed


def save_scoring(
    groups: ScoringProfile | None,
    min_score: int,
    stack_groups: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Persist the profile (``None`` resets to the default) and rescore every job.

    ``stack_groups`` of ``None`` keeps the saved list, minus keys that no longer
    exist in the effective profile.
    """
    effective = groups or PROFILE
    if stack_groups is None:
        stack = [key for key in get_stack_groups() if key in effective]
    else:
        stack = list(stack_groups)
    set_setting(SCORING_PROFILE_KEY, groups or {})
    set_setting(HIGHLIGHT_MIN_SCORE_KEY, min_score)
    set_setting(HIGHLIGHT_STACK_GROUPS_KEY, stack)
    rescore_all()
    return scoring_payload()
