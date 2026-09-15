"""InHire collector: reads a company's public job posts through the InHire API."""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from watcher.scoring.engine import detect_work_mode
from watcher.scoring.text import normalize
from watcher.services.collection import CollectedJob, CollectionError, strip_html

API_URL = "https://api.inhire.app/job-posts/public/pages/lean"
# Public job page: the lean listing above has titles only, this one has the description.
DETAIL_URL = "https://api.inhire.app/job-posts/public/pages/{job_id}"
DEFAULT_CAREER_PAGE = "default"

REQUEST_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
MAX_CONCURRENCY = 5
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.0
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

JOB_PATH_PATTERN = re.compile(r"/vagas/([^/?#]+)", re.IGNORECASE)
LOCATION_MAX_LENGTH = 255

# workplaceType values seen on the API, mapped to the words the scoring engine
# recognises, so a later rescore keeps detecting the same work mode.
WORKPLACE_LABELS: dict[str, str] = {
    "remote": "Remoto",
    "hybrid": "Híbrido",
    "on-site": "Presencial",
    "onsite": "Presencial",
    "presential": "Presencial",
}

logger = logging.getLogger(__name__)

__all__ = [
    "CollectionError",
    "JobDetail",
    "ScrapedJob",
    "apply_detail",
    "collect_company",
    "detail_fields",
    "fetch_job_details",
]


@dataclass(frozen=True, slots=True)
class ScrapedJob:
    external_id: str
    title: str
    url: str


def extract_external_id(url: str) -> str | None:
    match = JOB_PATH_PATTERN.search(urlparse(url).path)
    if not match:
        return None
    candidate = match.group(1).strip()
    if candidate.lower() in {"", "vagas"}:
        return None
    return candidate


def extract_tenant(company_url: str) -> str:
    host = (urlparse(company_url).hostname or "").strip().lower()
    label = host.split(".")[0] if host else ""
    if not label or label in {"inhire", "www", "api"}:
        raise CollectionError(f"Cannot determine InHire tenant from URL: {company_url!r}")
    return label


def extract_career_page(company_url: str) -> str:
    segments = [segment for segment in urlparse(company_url).path.split("/") if segment]
    if segments and segments[-1].lower() == "vagas":
        segments = segments[:-1]
    return segments[0] if segments else DEFAULT_CAREER_PAGE


def _record_career_pages(record: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    identifier = record.get("careerPageId")
    if isinstance(identifier, str) and identifier:
        values.add(identifier)
    career_page = record.get("careerPage")
    if isinstance(career_page, dict):
        for key in ("careerPage", "id", "name"):
            value = career_page.get(key)
            if isinstance(value, str) and value:
                values.add(value)
    return values


def _job_slug(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title.casefold())
    ascii_title = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character) and ord(character) < 128
    )
    # InHire removes paired punctuation instead of treating it as a word break.
    # This turns "Desenvolvedor(a)" into "desenvolvedora".
    ascii_title = re.sub(r"[()\[\]{}'\"]", "", ascii_title)
    return re.sub(r"[^a-z0-9]+", "-", ascii_title).strip("-")


def _job_link(company_url: str, job_id: str, title: str) -> str:
    parsed = urlparse(company_url)
    path = parsed.path.rstrip("/")
    if not path.lower().endswith("/vagas"):
        path = f"{path}/vagas" if path else "/vagas"
    base_url = f"{parsed.scheme}://{parsed.netloc}{path}/{job_id}"
    slug = _job_slug(title)
    return f"{base_url}/{slug}" if slug else base_url


def records_to_jobs(records: list[Any], company_url: str, career_page: str) -> list[ScrapedJob]:
    jobs: dict[str, ScrapedJob] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        if career_page not in _record_career_pages(record):
            continue
        job_id = record.get("jobId")
        title = (record.get("displayName") or "").strip()
        if not isinstance(job_id, str) or not job_id or not title:
            continue
        jobs[job_id] = ScrapedJob(job_id, title, _job_link(company_url, job_id, title))
    return list(jobs.values())


async def _request_json(
    client: httpx.AsyncClient, url: str, tenant: str, subject: str, expected: type
) -> Any:
    """GET an InHire public endpoint with the shared retry policy.

    Only timeouts, transport errors, 429 and 5xx are retried.

    Raises:
        CollectionError: any other HTTP error, invalid JSON, an unexpected
            payload type, or retries exhausted.
    """
    headers = {"Content-Type": "application/json", "X-Tenant": tenant}
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = await client.get(url, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as error:
            last_error = error
        else:
            if response.status_code in RETRYABLE_STATUS_CODES:
                last_error = CollectionError(
                    f"InHire API returned HTTP {response.status_code} for {subject}"
                )
            elif response.status_code >= 400:
                raise CollectionError(
                    f"InHire API returned HTTP {response.status_code} for {subject}"
                )
            else:
                try:
                    payload = response.json()
                except ValueError as error:
                    raise CollectionError(
                        f"InHire API returned invalid JSON for {subject}"
                    ) from error
                if not isinstance(payload, expected):
                    raise CollectionError(
                        f"InHire API returned an unexpected payload for {subject}"
                    )
                return payload

        if attempt < MAX_ATTEMPTS:
            await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)

    raise CollectionError(
        f"InHire API request failed for {subject} after {MAX_ATTEMPTS} attempts: {last_error}"
    )


async def _fetch_records(client: httpx.AsyncClient, tenant: str) -> list[Any]:
    payload: list[Any] = await _request_json(client, API_URL, tenant, f"tenant {tenant!r}", list)
    return payload


async def collect_company(client: httpx.AsyncClient, company_url: str) -> list[ScrapedJob]:
    """Collect the jobs of one company career page.

    Raises:
        CollectionError: when the listing cannot be fetched or confirmed.
    """
    tenant = extract_tenant(company_url)
    career_page = extract_career_page(company_url)
    records = await _fetch_records(client, tenant)

    if career_page != DEFAULT_CAREER_PAGE:
        known_pages: set[str] = set()
        for record in records:
            if isinstance(record, dict):
                known_pages |= _record_career_pages(record)
        if career_page not in known_pages:
            raise CollectionError(
                f"Career page {career_page!r} was not present in the InHire response "
                f"for tenant {tenant!r}; refusing to archive jobs on an unconfirmed page"
            )

    return records_to_jobs(records, company_url, career_page)


@dataclass(frozen=True, slots=True)
class JobDetail:
    """What the public job page adds to a listing entry."""

    description: str
    location: str
    published_at: datetime | None
    workplace: str  # "Remoto", "Híbrido", "Presencial" or ""


def _parse_datetime(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def detail_location(raw: Any) -> str:
    """Location arrives as "Sao Paulo, SP, BR"; an object or a list is accepted too."""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        parts = [raw.get(key) for key in ("city", "state", "country", "name")]
        return ", ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())
    if isinstance(raw, list):
        return ", ".join(text for text in (detail_location(item) for item in raw) if text)
    return ""


def parse_job_detail(payload: dict[str, Any]) -> JobDetail:
    workplace = payload.get("workplaceType")
    label = (
        WORKPLACE_LABELS.get(workplace.strip().lower(), "") if isinstance(workplace, str) else ""
    )
    description = payload.get("description")
    return JobDetail(
        description=strip_html(description) if isinstance(description, str) else "",
        location=detail_location(payload.get("location")),
        published_at=(
            _parse_datetime(payload.get("publishedAt"))
            or _parse_datetime(payload.get("lastPublishedAt"))
        ),
        workplace=label,
    )


async def fetch_job_detail(client: httpx.AsyncClient, tenant: str, job_id: str) -> JobDetail:
    """Fetch one public job page.

    Raises:
        CollectionError: when the page cannot be fetched or parsed.
    """
    url = DETAIL_URL.format(job_id=job_id)
    subject = f"job {job_id!r} of tenant {tenant!r}"
    payload: dict[str, Any] = await _request_json(client, url, tenant, subject, dict)
    return parse_job_detail(payload)


async def fetch_job_details(
    client: httpx.AsyncClient,
    tenant: str,
    job_ids: Iterable[str],
    *,
    semaphore: asyncio.Semaphore | None = None,
    on_done: Callable[[str, bool], None] | None = None,
) -> dict[str, JobDetail]:
    """Fetch several job pages with bounded concurrency.

    A page that fails is logged and left out: the caller keeps the job with its
    title only and asks again on the next run.
    """
    limit = semaphore or asyncio.Semaphore(MAX_CONCURRENCY)
    details: dict[str, JobDetail] = {}

    async def one(job_id: str) -> None:
        async with limit:
            try:
                details[job_id] = await fetch_job_detail(client, tenant, job_id)
                succeeded = True
            except CollectionError as error:
                logger.warning("InHire job details unavailable: %s", error)
                succeeded = False
        if on_done is not None:
            on_done(job_id, succeeded)

    await asyncio.gather(*(one(job_id) for job_id in dict.fromkeys(job_ids)))
    return details


def detail_fields(title: str, detail: JobDetail) -> dict[str, Any]:
    """Job field values from a job page.

    The workplace label only lands in the location when the title, description
    and location do not state the work mode themselves.
    """
    location = detail.location
    if detail.workplace:
        text = normalize(f"{title} {detail.description} {location}")
        if detect_work_mode(text) == "unknown":
            location = f"{location} · {detail.workplace}" if location else detail.workplace
    return {
        "description": detail.description,
        "location": location[:LOCATION_MAX_LENGTH],
        "published_at": detail.published_at,
    }


def apply_detail(job: CollectedJob, detail: JobDetail) -> CollectedJob:
    return replace(job, **detail_fields(job.title, detail))
