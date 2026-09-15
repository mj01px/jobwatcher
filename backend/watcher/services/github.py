"""GitHub collector: one source per Brazilian community vacancy repository (from Vaggio).

Every job is an open issue. The REST API is public and documented, so there is
no account block risk. Without a token the limit is 60 requests per hour; a
personal token with public scope raises it to 5000 (set it in Settings).

Repositories measured on 2026-09-02 (exist, not archived, open issues):
backend-br/vagas (~49 open), soujava/vagas-java (~43), frontendbr/vagas (~31,
idle since 03/2026) and react-brasil/vagas (~10, idle since 01/2024). Left out
on purpose: phpdevbr, androiddevbr, vuejs-br, qa-brasil, uxbrasil (off target or
idle for years); lerrua/remote-jobs-brazil is archived.

A repo snapshot is authoritative only when every open issue page was read: the
loop ended on a short (or empty) page, with no page limit hit and no failure.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

import httpx

from watcher.services.collection import (
    CollectedJob,
    CollectionError,
    CollectorResult,
    github_key,
)
from watcher.services.secrets import GITHUB_TOKEN, get_secret

logger = logging.getLogger(__name__)

REPOS: list[str] = [
    "backend-br/vagas",
    "soujava/vagas-java",
    "frontendbr/vagas",
    "react-brasil/vagas",
]

API = "https://api.github.com/repos/{repo}/issues"
# 100 is the GitHub page ceiling. Three pages cover 300 issues per repo, far
# above the largest measured queue (49).
PER_PAGE = 100
MAX_PAGES = 3
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.0
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
USER_AGENT = "job-watcher/2.0 (personal use; job search)"

# Pinned rules and moderation issues are not jobs.
NOT_A_JOB_RE = re.compile(
    r"(regras?\b|rules\b|leia\b|read me|como (postar|divulgar)|template|aten[çc][ãa]o)",
    re.IGNORECASE,
)

# Bodies usually follow a template with a company line. The ``[*_`\s]*`` after
# "empresa" covers the two forms that really appear, "**Empresa:** Acme" and
# "**Empresa**: Acme", which only differ in where the bold closes.
COMPANY_RE = re.compile(
    r"^\s*(?:[#*\->\s]*)(?:nome\s+da\s+)?empresa[*_`\s]*[:\-]\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)


class HttpClient(Protocol):
    def get(
        self, url: str, params: dict[str, Any] | None = ..., headers: dict[str, str] | None = ...
    ) -> Any: ...


def build_client() -> httpx.Client:
    return httpx.Client(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )


def request_headers(token: str = "") -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    if token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def company_from_body(body: str) -> str:
    """Use the company line when the body follows the template, else "" (never invent)."""
    match = COMPANY_RE.search(body)
    if not match:
        return ""
    value = re.sub(r"[*_`#\[\]]", "", match.group(1)).strip()
    return value[:200] if 1 < len(value) < 120 else ""


def parse_issue(issue: Any, repo: str) -> CollectedJob | None:
    if not isinstance(issue, dict) or "pull_request" in issue:
        return None
    title = str(issue.get("title") or "").strip()
    url = str(issue.get("html_url") or "").strip()
    if not title or not url or NOT_A_JOB_RE.search(title):
        return None

    body = str(issue.get("body") or "")
    labels = [
        str(label.get("name", "")) for label in issue.get("labels") or [] if isinstance(label, dict)
    ]
    published_at = None
    if issue.get("created_at"):
        try:
            published_at = datetime.fromisoformat(str(issue["created_at"]).replace("Z", "+00:00"))
        except ValueError:
            published_at = None

    # The company comes from the body, never the title. Titles in these repos
    # are too free form ("[CLT] Company - Role", "Role | Company") and splitting
    # them corrupted both the title and the score.
    return CollectedJob(
        key=github_key(url),
        external_id=f"{repo}#{issue.get('number')}",
        title=title[:500],
        url=url[:1000],
        company_name=company_from_body(body),
        description=f"{body}\n\nLabels: {', '.join(labels)}\nRepo: {repo}",
        published_at=published_at,
    )


def fetch_issues_page(
    client: HttpClient,
    repo: str,
    page: int,
    *,
    token: str = "",
    per_page: int = PER_PAGE,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Any]:
    """One page of open issues, retrying only transient failures.

    Raises:
        CollectionError: on a non transient HTTP error, a bad payload or after retries.
    """
    params = {
        "state": "open",
        "sort": "created",
        "direction": "desc",
        "per_page": per_page,
        "page": page,
    }
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.get(
                API.format(repo=repo), params=params, headers=request_headers(token)
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            last_error = str(error) or type(error).__name__
        else:
            status_code = response.status_code
            if status_code in RETRYABLE_STATUS_CODES:
                last_error = f"HTTP {status_code}"
            elif status_code >= 400:
                raise CollectionError(
                    f"GitHub API returned HTTP {status_code} for {repo!r} page {page}"
                )
            else:
                try:
                    payload = response.json()
                except ValueError as error:
                    raise CollectionError(
                        f"GitHub API returned invalid JSON for {repo!r}"
                    ) from error
                if not isinstance(payload, list):
                    raise CollectionError(f"GitHub API returned an unexpected payload for {repo!r}")
                return payload
        if attempt < MAX_ATTEMPTS:
            sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise CollectionError(
        f"GitHub API request failed for {repo!r} page {page} after {MAX_ATTEMPTS} attempts: "
        f"{last_error}"
    )


def collect_repo(
    client: HttpClient,
    repo: str,
    *,
    token: str = "",
    per_page: int = PER_PAGE,
    max_pages: int = MAX_PAGES,
    sleep: Callable[[float], None] = time.sleep,
) -> CollectorResult:
    """Read the open issues of one repo.

    Raises:
        CollectionError: when the first page cannot be read.
    """
    jobs: dict[str, CollectedJob] = {}
    authoritative = False
    warning: str | None = None

    for page in range(1, max_pages + 1):
        try:
            issues = fetch_issues_page(
                client, repo, page, token=token, per_page=per_page, sleep=sleep
            )
        except CollectionError as error:
            if page == 1:
                raise
            warning = str(error)
            break

        for issue in issues:
            job = parse_issue(issue, repo)
            if job is not None:
                jobs.setdefault(job.key, job)

        # A short page is the last one: do not spend a request (and quota,
        # 60 per hour without a token) asking for an empty page.
        if len(issues) < per_page:
            authoritative = True
            break

    return CollectorResult(jobs=list(jobs.values()), authoritative=authoritative, warning=warning)


def collect_github_repo(repo: str) -> CollectorResult:
    """Synchronous entry point used by the monitor (runs in a worker thread)."""
    with build_client() as client:
        return collect_repo(client, repo, token=get_secret(GITHUB_TOKEN))
