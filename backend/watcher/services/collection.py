"""Shared collector contract: what every source returns and how jobs are keyed."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import datetime

_TAG_RE = re.compile(r"<[^>]+>")
_SPACES_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    """Descriptions come as HTML with entities; score and read plain text instead."""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _SPACES_RE.sub(" ", text).strip()


class CollectionError(RuntimeError):
    """Raised when a source listing could not be retrieved or trusted.

    Raising this instead of returning an empty list guarantees the monitor
    never treats a failed collection as "the source has no jobs" and never
    archives every job because of a transient or structural failure.
    """


@dataclass(frozen=True, slots=True)
class CollectedJob:
    """A job as a source returned it, before scoring and before the database."""

    key: str
    external_id: str
    title: str
    url: str
    company_name: str = ""
    location: str = ""
    description: str = ""
    published_at: datetime | None = None


@dataclass(slots=True)
class CollectorResult:
    """One source snapshot.

    ``authoritative`` means the listing is complete, so a job missing from it
    really left the source. ``warning`` describes a partial failure: the jobs
    that did arrive are still applied, but the run records the problem.
    """

    jobs: list[CollectedJob] = field(default_factory=list)
    authoritative: bool = False
    warning: str | None = None


def inhire_key(job_id: str) -> str:
    return f"inhire:{job_id}"


def gupy_key(source_id: str, url: str) -> str:
    return f"gupy:{source_id}" if source_id else f"gupy:{url.strip()}"


def github_key(url: str) -> str:
    return f"github:{url.strip()}"


def manual_key(url: str) -> str:
    digest = hashlib.sha256(url.strip().lower().encode("utf-8")).hexdigest()
    return f"manual:{digest}"
