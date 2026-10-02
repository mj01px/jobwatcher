"""Gupy collector: one source per search term on the public Gupy job portal.

The old REST API (``employability-portal.gupy.io/api/v1/jobs``) was retired and
now answers 404. The portal moved to a Next.js app and serves the same search
data through its data route, measured 2026-10-02::

    GET https://portal.gupy.io/_next/data/<buildId>/job-search/term=<term>.json?page=<N>

It returns ``{"pageProps": {"initialJobList": {"data": [...],
"pagination": {"total": N, "limit": 12, "offset": O}}}}``. Each item carries the
same fields the old API did (``id``, ``name``, ``jobUrl``, ``careerPageName``,
``city``, ``state``, ``country``, ``publishedDate``, ``workplaceType``, ``type``,
``description``), so :func:`parse_item` is unchanged.

What the route accepts, measured rather than assumed:

- ``<term>`` lives in the path, URL encoded (spaces and accents included);
  without it the route is a different page, so the term stays the filter.
- ``page`` is the only pagination knob. ``limit`` is pinned at 12 and
  ``offset``/``perPage``/``pageSize`` are ignored, so a term is swept 12 jobs at
  a time.
- ``pagination.total`` is still NOT reliable: a large term comes back pinned at
  100 ("desenvolvedor" measured 100 with 12 per page). The only reliable stop is
  a short page.
- ``<buildId>`` is Next.js' deploy hash. It is part of the path and rotates on
  every Gupy deploy, so it is scraped from the portal HTML once per term rather
  than hardcoded.

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
import re
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import quote

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

# The portal's fixed page size. ``limit`` is ignored; ``?page=N`` is the only knob.
PAGE_SIZE = 12
# Safety lock: 50 pages of 12 is 600 jobs, more than any term returns in the
# 30 day window we keep. It exists so a wrong ``total`` never loops forever.
MAX_PAGES_PER_SEARCH = 50
# A failing page must not take the rest of the term with it.
ATTEMPTS_PER_PAGE = 3
RETRY_WAITS: tuple[float, ...] = (1.0, 3.0)

REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

# The deploy hash sits in the portal HTML as ``"buildId":"<hash>"``.
BUILD_ID_RE = re.compile(r'"buildId"\s*:\s*"([^"]+)"')


class HttpResponse(Protocol):
    @property
    def text(self) -> str: ...
    def raise_for_status(self) -> Any: ...
    def json(self) -> Any: ...


class HttpClient(Protocol):
    def get(self, url: str, params: dict[str, Any] | None = ...) -> Any: ...


def build_client() -> httpx.Client:
    # The portal wants a browser looking client, otherwise it answers 403.
    return httpx.Client(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json,*/*",
            "Origin": "https://portal.gupy.io",
            "Referer": "https://portal.gupy.io/",
        },
    )


def data_url(portal: str, build_id: str, term: str) -> str:
    """The Next.js data route for one search term (the term lives in the path)."""
    return f"{portal}/_next/data/{build_id}/job-search/term={quote(term, safe='')}.json"


def resolve_build_id(
    client: HttpClient,
    portal: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Scrape the portal's current Next.js build id.

    It is part of the data route path and rotates on every Gupy deploy, so it is
    read fresh rather than hardcoded.

    Raises:
        CollectionError: when the portal HTML never answers or carries no build id.
    """
    url = f"{portal}/job-search"
    last_error = ""
    for attempt in range(ATTEMPTS_PER_PAGE):
        try:
            response = client.get(url)
            response.raise_for_status()
            match = BUILD_ID_RE.search(response.text)
            if match:
                return match.group(1)
            last_error = "no buildId in portal HTML"
        except Exception as error:  # noqa: BLE001 - any failure is retried
            last_error = str(error) or type(error).__name__
        logger.warning(
            "gupy build id, attempt %s of %s: %s", attempt + 1, ATTEMPTS_PER_PAGE, last_error
        )
        if attempt < ATTEMPTS_PER_PAGE - 1:
            sleep(RETRY_WAITS[min(attempt, len(RETRY_WAITS) - 1)])
    raise CollectionError(f"Gupy portal build id unavailable: {last_error}")


def extract_list(payload: Any) -> list[Any]:
    """Dig the job list out of the data route envelope (and legacy variants)."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        page_props = payload.get("pageProps")
        if isinstance(page_props, dict):
            job_list = page_props.get("initialJobList")
            if isinstance(job_list, dict) and isinstance(job_list.get("data"), list):
                return job_list["data"]
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
    if item.get("isRemoteWork") or item.get("workplaceType") == "remote":
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
    portal: str,
    build_id: str,
    term: str,
    page: int,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[Any, str | None]:
    """One page, retried when the answer does not come.

    Returns:
        ``(payload, None)`` on success or ``(None, error)`` after giving up.
    """
    url = data_url(portal, build_id, term)
    last_error = ""
    for attempt in range(ATTEMPTS_PER_PAGE):
        try:
            response = client.get(url, params={"page": page})
            response.raise_for_status()
            return response.json(), None
        except Exception as error:  # noqa: BLE001 - any failure of the page is retried
            last_error = str(error) or type(error).__name__
            logger.warning(
                "gupy %r page %s, attempt %s of %s: %s",
                term,
                page,
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
    portal: str | None = None,
    build_id: str | None = None,
    max_pages: int = MAX_PAGES_PER_SEARCH,
    sleep: Callable[[float], None] = time.sleep,
) -> CollectorResult:
    """Sweep a whole term, page by page, stopping on the first short page.

    Raises:
        CollectionError: when the build id or the first page never answers
            (nothing to apply).
    """
    base = (portal or settings.GUPY_API).rstrip("/")
    if build_id is None:
        build_id = resolve_build_id(client, base, sleep=sleep)
    jobs: dict[str, CollectedJob] = {}
    warning: str | None = None

    for page in range(1, max_pages + 1):
        payload, error = fetch_page(client, base, build_id, term, page, sleep=sleep)
        if payload is None:
            if page == 1:
                raise CollectionError(f"Gupy search {term!r} did not answer: {error}")
            # Partial failure: keep what arrived, but the run must not pass for
            # a quiet day because the portal went down halfway.
            warning = f"Gupy search {term!r} stopped at page {page}: {error}"
            break

        items = extract_list(payload)
        if not items:
            break
        for item in items:
            job = parse_item(item)
            if job is not None:
                jobs.setdefault(job.key, job)
        if len(items) < PAGE_SIZE:
            break

    return CollectorResult(jobs=list(jobs.values()), authoritative=False, warning=warning)


def collect_gupy_term(term: str) -> CollectorResult:
    """Synchronous entry point used by the monitor (runs in a worker thread)."""
    with build_client() as client:
        return collect_term(client, term)
