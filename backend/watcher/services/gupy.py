"""Gupy collector: one source per search term on the public Gupy job portal (from Vaggio).

Endpoint confirmed on 2026-09-02::

    GET https://employability-portal.gupy.io/api/v1/jobs?jobName=<term>&offset=0&limit=100

It returns ``{"data": [...], "pagination": {"total": N, "limit": L, "offset": O}}``.
The search parameter is ``jobName`` (``name`` answers 400).

What the API accepts, measured rather than assumed:

- ``limit`` goes up to 100; 200 answers 400.
- ``offset`` really paginates, pages never overlap.
- ``pagination.total`` is NOT reliable: with ``limit`` of 40 or more it comes back
  pinned at 100 even when 650 results exist (measured on "desenvolvedor":
  ``limit=1`` says 650, ``limit=100`` says 100). Stopping on that field cost 550
  jobs on a single term. The only reliable stop is a short page.
- There is no sort nor date parameter (``sort``, ``orderBy``, ``publishedDate``
  answer 400), so recency is cut on our side (30 day max age).
- ``jobName`` is optional, but without it the API returns the whole portal
  (82,536 jobs on 2026-09-03). The term stays the filter.
- Filters that exist only narrow: ``workplaceType=remote`` and
  ``isRemoteWork=true``. ``jobType``, ``careerPageId``, ``publishedSince``,
  ``skill`` and ``label`` answer 400; ``city``, ``state`` and ``country`` answer 200
  with zero results.

A search is never authoritative: a job missing from one response does not mean
it closed, so Gupy jobs are only archived by the age rule.

How the default terms were picked (measured 2026-09-03 counting unique URLs):

- spelling variants add nothing ("back end", "full-stack", "desenvolvedora"
  brought zero jobs the listed terms did not have);
- generic level terms poison the queue: "estagio" (1,760), "junior" (1,004) and
  "trainee" (226) are 80% to 92% outside tech, and the score does not protect
  you because level terms are worth points. Filtering the domain is the term's
  job, not the score's;
- prefix matching is a trap: "programacao" matches "Programa de Estagio"
  (100 civil engineering jobs), "go" and "swift" (the banking SWIFT) too.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

import httpx
from django.conf import settings

from watcher.services.collection import (
    CollectedJob,
    CollectionError,
    CollectorResult,
    gupy_key,
    strip_html,
)

logger = logging.getLogger(__name__)

DEFAULT_SEARCHES: list[str] = [
    "desenvolvedor",
    "programador",
    "developer",
    "analista de sistemas",
    "analista de desenvolvimento",
    "engenheiro de software",
    "desenvolvimento de software",
    "software",
    "sistemas",
    "backend",
    "back-end",
    "frontend",
    "front-end",
    "fullstack",
    "full stack",
    "python",
    "java",
    "javascript",
    "typescript",
    "node",
    "react",
    "sql",
    "banco de dados",
    "dados",
    "analista de dados",
    "engenheiro de dados",
    "cientista de dados",
    "inteligencia artificial",
    "cloud",
    "devops",
    "seguranca da informacao",
    "analista de suporte",
    "qa",
    "analista de testes",
    "estagio desenvolvimento",
    "estagio tecnologia",
    "estagio ti",
    "estagio dados",
]

# API ceiling. Asking for more answers 400.
PAGE_SIZE = 100
# Safety lock: 20 pages of 100 is more than twice the largest measured term
# ("desenvolvedor", 662). It exists so a wrong ``total`` never loops forever.
MAX_PAGES_PER_SEARCH = 20
# A failing page must not take the rest of the term with it: "desenvolvedor" is
# 7 pages, giving up on the third costs 400 jobs.
ATTEMPTS_PER_PAGE = 3
RETRY_WAITS: tuple[float, ...] = (1.0, 3.0)

REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


class HttpClient(Protocol):
    def get(self, url: str, params: dict[str, Any] | None = ...) -> Any: ...


def build_client() -> httpx.Client:
    # The portal wants a browser looking client, otherwise the API answers 403.
    return httpx.Client(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Origin": "https://portal.gupy.io",
            "Referer": "https://portal.gupy.io/",
        },
    )


def extract_list(payload: Any) -> list[Any]:
    """The API already changed its envelope once. Accept the known variants."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "results", "jobs", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _parse_date(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_item(item: Any) -> CollectedJob | None:
    if not isinstance(item, dict):
        return None
    title = str(item.get("name") or item.get("title") or "").strip()
    url = str(item.get("jobUrl") or item.get("careerPageUrl") or item.get("url") or "").strip()
    if not title or not url:
        return None

    company = ""
    for key in ("careerPageName", "companyName", "company"):
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("name")
        if value:
            company = str(value)
            break

    location = ", ".join(
        str(part) for part in (item.get("city"), item.get("state"), item.get("country")) if part
    )
    if item.get("isRemoteWork"):
        location = f"Remoto{', ' + location if location else ''}"

    skills: Any = item.get("skills") or []
    if isinstance(skills, list):
        skills = " ".join(
            skill.get("name", "") if isinstance(skill, dict) else str(skill) for skill in skills
        )
    context = " ".join(str(item.get(key) or "") for key in ("workplaceType", "type"))
    description = strip_html(str(item.get("description") or ""))

    source_id = str(item.get("id") or "")
    return CollectedJob(
        key=gupy_key(source_id, url),
        external_id=source_id or url,
        title=title[:500],
        url=url[:1000],
        company_name=company.strip()[:255],
        location=location.strip()[:255],
        description=f"{context} {skills}\n\n{description}".strip(),
        published_at=_parse_date(item.get("publishedDate") or item.get("createdAt")),
    )


def fetch_page(
    client: HttpClient,
    api: str,
    term: str,
    offset: int,
    *,
    per_page: int = PAGE_SIZE,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[Any, str | None]:
    """One page, retried when the answer does not come.

    Returns:
        ``(payload, None)`` on success or ``(None, error)`` after giving up.
    """
    last_error = ""
    for attempt in range(ATTEMPTS_PER_PAGE):
        try:
            response = client.get(
                api, params={"jobName": term, "offset": offset, "limit": per_page}
            )
            response.raise_for_status()
            return response.json(), None
        except Exception as error:  # noqa: BLE001 - any failure of the page is retried
            last_error = str(error) or type(error).__name__
            logger.warning(
                "gupy %r offset %s, attempt %s of %s: %s",
                term,
                offset,
                attempt + 1,
                ATTEMPTS_PER_PAGE,
                last_error,
            )
            if attempt < ATTEMPTS_PER_PAGE - 1:
                sleep(RETRY_WAITS[min(attempt, len(RETRY_WAITS) - 1)])
    return None, last_error


def collect_term(
    client: HttpClient,
    term: str,
    *,
    api: str | None = None,
    per_page: int = PAGE_SIZE,
    max_pages: int = MAX_PAGES_PER_SEARCH,
    sleep: Callable[[float], None] = time.sleep,
) -> CollectorResult:
    """Sweep a whole term, page by page, stopping on the first short page.

    Raises:
        CollectionError: when the first page never answers (nothing to apply).
    """
    endpoint = (api or settings.GUPY_API).rstrip("/")
    per_page = min(per_page, PAGE_SIZE)
    jobs: dict[str, CollectedJob] = {}
    warning: str | None = None
    offset = 0

    for page_index in range(max_pages):
        payload, error = fetch_page(client, endpoint, term, offset, per_page=per_page, sleep=sleep)
        if payload is None:
            if page_index == 0:
                raise CollectionError(f"Gupy search {term!r} did not answer: {error}")
            # Partial failure: keep what arrived, but the run must not pass for
            # a quiet day because the API went down halfway.
            warning = f"Gupy search {term!r} stopped at offset {offset}: {error}"
            break

        items = extract_list(payload)
        if not items:
            break
        for item in items:
            job = parse_item(item)
            if job is not None:
                jobs.setdefault(job.key, job)
        if len(items) < per_page:
            break
        offset += len(items)

    return CollectorResult(jobs=list(jobs.values()), authoritative=False, warning=warning)


def collect_gupy_term(term: str) -> CollectorResult:
    """Synchronous entry point used by the monitor (runs in a worker thread)."""
    with build_client() as client:
        return collect_term(client, term)
