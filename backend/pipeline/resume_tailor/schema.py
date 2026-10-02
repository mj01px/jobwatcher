"""The tailored-resume shape and the normalisation of raw model JSON into it.

Mirrors the ATS schema's philosophy: the model's JSON is never trusted, so every
field is clamped, trimmed and capped here. ``normalize`` never raises; a missing
or malformed field becomes an empty one, and the renderer simply skips empties.
The sections are the candidate's own (summary, skills, experience, projects,
education, languages); the model fills them, it does not invent new ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

NAME_MAX = 120
HEADLINE_MAX = 160
CONTACT_LINE_MAX = 200
MAX_CONTACT_LINES = 3
SUMMARY_MAX = 1000
SKILL_ITEM_MAX = 80
MAX_SKILL_ITEMS = 40
SKILL_LABEL_MAX = 40
MAX_SKILL_GROUPS = 4
TITLE_MAX = 160
META_MAX = 48
SUBTITLE_MAX = 200
BULLET_MAX = 400
MAX_BULLETS = 10
MAX_ENTRIES = 15
LANGUAGES_MAX = 200


@dataclass(frozen=True)
class SkillGroup:
    label: str
    items: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Entry:
    """One experience/project/education row: a title, a right-aligned meta
    (date or year), a muted subtitle (company, stack or URL) and bullets."""

    title: str
    meta: str = ""
    subtitle: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TailoredResume:
    name: str = ""
    headline: str = ""
    contact_lines: list[str] = field(default_factory=list)
    summary: str = ""
    skills: list[SkillGroup] = field(default_factory=list)
    experience: list[Entry] = field(default_factory=list)
    projects: list[Entry] = field(default_factory=list)
    education: list[Entry] = field(default_factory=list)
    languages: str = ""

    def is_empty(self) -> bool:
        """True when nothing worth rendering survived normalisation."""
        return not (
            self.name
            or self.summary
            or self.skills
            or self.experience
            or self.projects
            or self.education
        )


def _text(value: Any, limit: int) -> str:
    return " ".join(value.split())[:limit].strip() if isinstance(value, str) else ""


def _str_list(value: Any, *, item_limit: int, max_items: int) -> list[str]:
    """Unique, non-empty, trimmed strings, order preserved and capped."""
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for raw in value:
        item = _text(raw, item_limit)
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            result.append(item)
        if len(result) >= max_items:
            break
    return result


def _bullets(value: Any) -> list[str]:
    return _str_list(value, item_limit=BULLET_MAX, max_items=MAX_BULLETS)


def _skills(value: Any) -> list[SkillGroup]:
    if not isinstance(value, list):
        return []
    groups: list[SkillGroup] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        label = _text(raw.get("label"), SKILL_LABEL_MAX)
        items = _str_list(raw.get("items"), item_limit=SKILL_ITEM_MAX, max_items=MAX_SKILL_ITEMS)
        if label and items:
            groups.append(SkillGroup(label=label, items=items))
        if len(groups) >= MAX_SKILL_GROUPS:
            break
    return groups


def _entries(value: Any) -> list[Entry]:
    if not isinstance(value, list):
        return []
    entries: list[Entry] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        title = _text(raw.get("title"), TITLE_MAX)
        if not title:
            continue
        entries.append(
            Entry(
                title=title,
                meta=_text(raw.get("meta"), META_MAX),
                subtitle=_text(raw.get("subtitle"), SUBTITLE_MAX),
                bullets=_bullets(raw.get("bullets")),
            )
        )
        if len(entries) >= MAX_ENTRIES:
            break
    return entries


def normalize(data: dict[str, Any]) -> TailoredResume:
    """Turn raw model JSON into a validated ``TailoredResume`` (never raises)."""
    if not isinstance(data, dict):
        return TailoredResume()
    return TailoredResume(
        name=_text(data.get("name"), NAME_MAX),
        headline=_text(data.get("headline"), HEADLINE_MAX),
        contact_lines=_str_list(
            data.get("contact_lines"), item_limit=CONTACT_LINE_MAX, max_items=MAX_CONTACT_LINES
        ),
        summary=_text(data.get("summary"), SUMMARY_MAX),
        skills=_skills(data.get("skills")),
        experience=_entries(data.get("experience")),
        projects=_entries(data.get("projects")),
        education=_entries(data.get("education")),
        languages=_text(data.get("languages"), LANGUAGES_MAX),
    )
