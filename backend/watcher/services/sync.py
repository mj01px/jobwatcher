"""Two-way sync of your Job Watcher data across machines through a shared JSON file.

Both machines scrape the same sources, so the jobs regenerate on each; what this
syncs is what *you* do and configure: applications with their timeline and cover
letters, your manual jobs, your sources, the scoring profile and dossier, and the
API keys. The document lives in a cloud-synced folder (Google Drive by default).

Merge is per record, newest ``updatedAt`` wins, which is safe because the app is
used on one machine at a time. Jobs are matched across machines by ``Job.key``
(``"<kind>:<external id>"``), the same global dedup key the collectors use, so an
application applied on one machine attaches to the matching job on the other.
Sync never deletes: it only creates and updates.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from pipeline.models import Application, Interaction, Pitch
from watcher.constants import (
    DOSSIER_KEY,
    GEMINI_MODEL_KEY,
    HIGHLIGHT_MIN_SCORE_KEY,
    HIGHLIGHT_STACK_GROUPS_KEY,
    MANUAL_SOURCE_TARGET,
    PITCH_MAX_CHARS_KEY,
    SCORING_PROFILE_KEY,
)
from watcher.models import Job, Setting, Source
from watcher.services.scoring import rescore_all
from watcher.services.secrets import ENV_VARS, get_secret, set_secrets

logger = logging.getLogger("watcher.sync")

SCHEMA = 1
SYNC_FOLDER = "JobWatcher"
SYNC_FILENAME = "sync.json"
SYNCED_SOURCE_TARGET = "imported:sync"

# User-owned settings worth carrying between machines. Operational keys
# (heartbeats, visit pings, the overdue-notice date) stay per machine.
# Changing any of these means every job's score may change, so a pull re-scores.
_SCORING_SETTING_KEYS = (
    SCORING_PROFILE_KEY,
    HIGHLIGHT_MIN_SCORE_KEY,
    HIGHLIGHT_STACK_GROUPS_KEY,
)
SYNCED_SETTING_KEYS = (
    *_SCORING_SETTING_KEYS,
    DOSSIER_KEY,
    PITCH_MAX_CHARS_KEY,
    GEMINI_MODEL_KEY,
)

PLACEHOLDER_NAMES = {
    Source.Kind.GUPY: "Gupy (synced)",
    Source.Kind.GITHUB: "GitHub (synced)",
    Source.Kind.INHIRE: "InHire (synced)",
}


@dataclass
class SyncCounts:
    """What a pull changed locally."""

    settings: int = 0
    secrets: int = 0
    sources: int = 0
    jobs: int = 0
    applications: int = 0
    interactions: int = 0
    pitches: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)

    def total(self) -> int:
        return sum(self.as_dict().values())


# --------------------------------------------------------------------------- #
# Location
# --------------------------------------------------------------------------- #
# "My Drive" is localized by Google Drive per account language, so match the
# common names. Anything else: point JOB_WATCHER_SYNC_DIR at the folder.
MY_DRIVE_NAMES = (
    "My Drive",
    "Meu Drive",  # pt
    "Mi unidad",  # es
    "Mon Drive",  # fr
    "Mein Drive",  # de
    "Il mio Drive",  # it
    "Mijn Drive",  # nl
    "マイドライブ",  # ja
    "내 드라이브",  # ko
    "我的云端硬盘",  # zh
)


def _mount_roots() -> list[Path]:
    """Where Google Drive for Desktop may be mounted, before the "My Drive" part."""
    home = Path.home()
    roots = [Path(m) for m in glob.glob(str(home / "Library" / "CloudStorage" / "GoogleDrive-*"))]
    roots.append(home / "Google Drive")
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:  # Windows
        roots += [Path(userprofile) / "Google Drive", Path(userprofile)]
    roots += [Path(f"{letter}:\\") for letter in ("G", "H", "I")]
    return roots


def _personal_drive(mount: Path) -> Path | None:
    """The writable "My Drive" folder inside a mount (handles localized names)."""
    for name in MY_DRIVE_NAMES:
        candidate = mount / name
        if candidate.is_dir():
            return candidate
    # Some setups mount the personal drive directly as the root (e.g. a drive letter).
    if mount.is_dir() and os.access(mount, os.W_OK):
        return mount
    return None


def _drive_candidates() -> list[Path]:
    found: list[Path] = []
    for mount in _mount_roots():
        personal = _personal_drive(mount)
        if personal is not None:
            found.append(personal)
    return found


def sync_root() -> Path | None:
    """The base folder for the sync file, or ``None`` when sync is off."""
    configured = settings.SYNC_DIR
    if configured is not None:
        cleaned = configured.strip()
        return Path(cleaned).expanduser() if cleaned else None
    candidates = _drive_candidates()
    return candidates[0] if candidates else None


def sync_file() -> Path | None:
    root = sync_root()
    return None if root is None else root / SYNC_FOLDER / SYNC_FILENAME


def is_enabled() -> bool:
    return sync_file() is not None


# --------------------------------------------------------------------------- #
# Serialisation helpers
# --------------------------------------------------------------------------- #
def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _date(value: Any) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def _newer(remote: Any, local: datetime | None) -> bool:
    """Whether the remote timestamp should overwrite the local record."""
    remote_dt = _dt(remote)
    if remote_dt is None:
        return False
    return local is None or remote_dt > local


# --------------------------------------------------------------------------- #
# Export (local -> document)
# --------------------------------------------------------------------------- #
def _job_snapshot(job: Job) -> dict[str, Any]:
    return {
        "key": job.key,
        "kind": job.source.kind,
        "externalId": job.external_id,
        "title": job.title,
        "url": job.url,
        "companyName": job.company_name,
        "location": job.location,
        "workMode": job.work_mode,
        "seniority": job.seniority,
        "description": job.description,
        "publishedAt": _iso(job.published_at),
        "status": job.status,
        "archiveSource": job.archive_source,
        "archiveReason": job.archive_reason,
        "archiveNote": job.archive_note,
        "firstVisitedAt": _iso(job.first_visited_at),
        "lastVisitedAt": _iso(job.last_visited_at),
        "lastSeenAt": _iso(job.last_seen_at),
    }


def export_state() -> dict[str, Any]:
    """Build the full sync document from the local database and secrets."""
    settings_out = {
        row.key: {"value": row.value, "updatedAt": _iso(row.updated_at)}
        for row in Setting.objects.filter(key__in=SYNCED_SETTING_KEYS)
    }
    secrets_out = {name: value for name in ENV_VARS if (value := get_secret(name))}
    real_sources = Source.objects.exclude(
        target__in=(MANUAL_SOURCE_TARGET, SYNCED_SOURCE_TARGET)
    )
    sources_out = [
        {
            "kind": source.kind,
            "target": source.target,
            "name": source.name,
            "isActive": source.is_active,
            "isRemoved": source.is_removed,
            "isHidden": source.is_hidden,
            "updatedAt": _iso(source.updated_at),
        }
        for source in real_sources
    ]
    jobs_out = [
        _job_snapshot(job)
        for job in Job.objects.select_related("source").filter(source__kind=Source.Kind.MANUAL)
    ]
    applications_out = []
    for application in Application.objects.select_related("job", "job__source").prefetch_related(
        "interactions"
    ):
        applications_out.append(
            {
                "jobKey": application.job.key,
                "job": _job_snapshot(application.job),
                "status": application.status,
                "priority": application.priority,
                "appliedOn": _iso(application.applied_on),
                "nextStep": application.next_step,
                "nextStepOn": _iso(application.next_step_on),
                "contact": application.contact,
                "hasReferral": application.has_referral,
                "notes": application.notes,
                "createdAt": _iso(application.created_at),
                "updatedAt": _iso(application.updated_at),
                "interactions": [
                    {
                        "date": _iso(item.date),
                        "title": item.title,
                        "detail": item.detail,
                        "createdAt": _iso(item.created_at),
                        "updatedAt": _iso(item.updated_at),
                    }
                    for item in application.interactions.all()
                ],
            }
        )
    pitches_out = [
        {
            "jobKey": pitch.job.key,
            "text": pitch.text,
            "model": pitch.model,
            "instruction": pitch.instruction,
            "maxChars": pitch.max_chars,
            "inputTokens": pitch.input_tokens,
            "outputTokens": pitch.output_tokens,
            "thinkingTokens": pitch.thinking_tokens,
            "createdAt": _iso(pitch.created_at),
            "updatedAt": _iso(pitch.updated_at),
        }
        for pitch in _latest_pitch_per_job()
    ]
    return {
        "schema": SCHEMA,
        "exportedAt": _iso(timezone.now()),
        "settings": settings_out,
        "secrets": secrets_out,
        "sources": sources_out,
        "jobs": jobs_out,
        "applications": applications_out,
        "pitches": pitches_out,
    }


def _latest_pitch_per_job() -> list[Pitch]:
    latest: dict[int, Pitch] = {}
    for pitch in Pitch.objects.select_related("job").order_by("job_id", "-created_at"):
        latest.setdefault(pitch.job_id, pitch)
    return list(latest.values())


# --------------------------------------------------------------------------- #
# Import (document -> local, newest wins)
# --------------------------------------------------------------------------- #
def _placeholder_source(kind: str) -> Source:
    if kind == Source.Kind.MANUAL:
        target, name, active = MANUAL_SOURCE_TARGET, "Manual", False
    else:
        target = SYNCED_SOURCE_TARGET
        name = PLACEHOLDER_NAMES.get(kind, "Synced")
        active = False
    source, _ = Source.objects.get_or_create(
        kind=kind,
        target=target,
        defaults={"name": name, "is_active": active, "is_hidden": True},
    )
    return source


def _ensure_job(snapshot: dict[str, Any]) -> Job | None:
    """Find the job by key, or create it from the snapshot so an application fits."""
    key = snapshot.get("key")
    if not key:
        return None
    existing = Job.objects.filter(key=key).first()
    if existing is not None:
        return existing
    kind = snapshot.get("kind") or Source.Kind.MANUAL
    now = timezone.now()
    job = Job(
        source=_placeholder_source(kind),
        key=key,
        external_id=(snapshot.get("externalId") or key)[:1000],
        title=(snapshot.get("title") or "")[:500],
        url=(snapshot.get("url") or "")[:1000],
        company_name=(snapshot.get("companyName") or "")[:255],
        location=(snapshot.get("location") or "")[:255],
        work_mode=snapshot.get("workMode") or Job.WorkMode.UNKNOWN,
        seniority=snapshot.get("seniority") or Job.Seniority.UNKNOWN,
        description=snapshot.get("description") or "",
        published_at=_dt(snapshot.get("publishedAt")),
        status=snapshot.get("status") or Job.Status.ACTIVE,
        archive_source=snapshot.get("archiveSource"),
        archive_reason=snapshot.get("archiveReason"),
        archive_note=snapshot.get("archiveNote"),
        first_visited_at=_dt(snapshot.get("firstVisitedAt")),
        last_visited_at=_dt(snapshot.get("lastVisitedAt")),
        arrived_new=False,
        first_seen_at=_dt(snapshot.get("lastSeenAt")) or now,
        last_seen_at=_dt(snapshot.get("lastSeenAt")) or now,
    )
    job.save()
    return job


def import_state(remote: dict[str, Any]) -> tuple[SyncCounts, bool]:
    """Apply the remote document to the local database. Returns (counts, needs_rescore)."""
    counts = SyncCounts()
    needs_rescore = False

    with transaction.atomic():
        # Settings
        for key, entry in (remote.get("settings") or {}).items():
            if key not in SYNCED_SETTING_KEYS or not isinstance(entry, dict):
                continue
            local = Setting.objects.filter(key=key).first()
            if _newer(entry.get("updatedAt"), local.updated_at if local else None):
                Setting.objects.update_or_create(
                    key=key,
                    defaults={
                        "value": entry.get("value"),
                        "updated_at": _dt(entry.get("updatedAt")),
                    },
                )
                counts.settings += 1
                if key in _SCORING_SETTING_KEYS:
                    needs_rescore = True

        # Secrets: only fill what this machine is missing, never overwrite.
        fill = {
            name: value
            for name, value in (remote.get("secrets") or {}).items()
            if name in ENV_VARS and value and not get_secret(name)
        }
        if fill:
            set_secrets(fill)
            counts.secrets += len(fill)

        # Sources
        for entry in remote.get("sources") or []:
            kind, target = entry.get("kind"), entry.get("target")
            if not kind or not target:
                continue
            local = Source.objects.filter(kind=kind, target=target).first()
            if _newer(entry.get("updatedAt"), local.updated_at if local else None):
                Source.objects.update_or_create(
                    kind=kind,
                    target=target,
                    defaults={
                        "name": (entry.get("name") or "")[:255],
                        "is_active": bool(entry.get("isActive", True)),
                        "is_removed": bool(entry.get("isRemoved", False)),
                        "is_hidden": bool(entry.get("isHidden", False)),
                        "updated_at": _dt(entry.get("updatedAt")) or timezone.now(),
                    },
                )
                counts.sources += 1

        # Manual jobs (they never regenerate from a scrape)
        for snapshot in remote.get("jobs") or []:
            if Job.objects.filter(key=snapshot.get("key")).exists():
                continue
            if _ensure_job(snapshot) is not None:
                counts.jobs += 1
                needs_rescore = True

        # Applications + interactions
        for entry in remote.get("applications") or []:
            job = _ensure_job(entry.get("job") or {"key": entry.get("jobKey")})
            if job is None:
                continue
            existing = Application.objects.filter(job=job).first()
            if _newer(entry.get("updatedAt"), existing.updated_at if existing else None):
                Application.objects.update_or_create(
                    job=job,
                    defaults={
                        "status": entry.get("status") or Application.Status.INTEREST,
                        "priority": entry.get("priority") or 3,
                        "applied_on": _date(entry.get("appliedOn")),
                        "next_step": entry.get("nextStep") or "",
                        "next_step_on": _date(entry.get("nextStepOn")),
                        "contact": entry.get("contact") or "",
                        "has_referral": bool(entry.get("hasReferral")),
                        "notes": entry.get("notes") or "",
                        "created_at": _dt(entry.get("createdAt")) or timezone.now(),
                        "updated_at": _dt(entry.get("updatedAt")) or timezone.now(),
                    },
                )
                counts.applications += 1
            application = Application.objects.get(job=job)
            for item in entry.get("interactions") or []:
                created_at = _dt(item.get("createdAt")) or timezone.now()
                _, created = Interaction.objects.get_or_create(
                    application=application,
                    date=_date(item.get("date")) or created_at.date(),
                    title=(item.get("title") or "")[:200],
                    created_at=created_at,
                    defaults={
                        "detail": item.get("detail") or "",
                        "updated_at": _dt(item.get("updatedAt")) or created_at,
                    },
                )
                counts.interactions += int(created)

        # Pitches (latest per job)
        for entry in remote.get("pitches") or []:
            job = Job.objects.filter(key=entry.get("jobKey")).first()
            if job is None:
                continue
            current = Pitch.objects.filter(job=job).order_by("-created_at").first()
            if not _newer(entry.get("updatedAt"), current.updated_at if current else None):
                continue
            Pitch.objects.filter(job=job).delete()
            created_at = _dt(entry.get("createdAt")) or timezone.now()
            Pitch.objects.create(
                job=job,
                text=entry.get("text") or "",
                model=(entry.get("model") or "")[:80],
                instruction=(entry.get("instruction") or "")[:300],
                max_chars=entry.get("maxChars") or 1200,
                input_tokens=entry.get("inputTokens") or 0,
                output_tokens=entry.get("outputTokens") or 0,
                thinking_tokens=entry.get("thinkingTokens") or 0,
                created_at=created_at,
                updated_at=_dt(entry.get("updatedAt")) or created_at,
            )
            counts.pitches += 1

    if needs_rescore:
        rescore_all()
    return counts, needs_rescore


# --------------------------------------------------------------------------- #
# Merge (local + remote -> document to write)
# --------------------------------------------------------------------------- #
def _merge_by_key(
    remote: list[dict[str, Any]], local: list[dict[str, Any]], key: Any
) -> list[dict[str, Any]]:
    """Union two record lists, keeping the newest ``updatedAt`` per key."""
    merged: dict[Any, dict[str, Any]] = {key(item): item for item in remote}
    for item in local:
        identity = key(item)
        current = merged.get(identity)
        if current is None or _newer(item.get("updatedAt"), _dt(current.get("updatedAt"))):
            merged[identity] = item
    return list(merged.values())


def _merged_document(remote: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
    settings_merged = dict(remote.get("settings") or {})
    for key, entry in (local.get("settings") or {}).items():
        current = settings_merged.get(key)
        if current is None or _newer(entry.get("updatedAt"), _dt(current.get("updatedAt"))):
            settings_merged[key] = entry
    secrets_merged = {**(remote.get("secrets") or {}), **(local.get("secrets") or {})}
    return {
        "schema": SCHEMA,
        "exportedAt": local.get("exportedAt"),
        "settings": settings_merged,
        "secrets": secrets_merged,
        "sources": _merge_by_key(
            remote.get("sources") or [],
            local.get("sources") or [],
            lambda item: (item.get("kind"), item.get("target")),
        ),
        "jobs": _merge_by_key(
            remote.get("jobs") or [], local.get("jobs") or [], lambda item: item.get("key")
        ),
        "applications": _merge_by_key(
            remote.get("applications") or [],
            local.get("applications") or [],
            lambda item: item.get("jobKey"),
        ),
        "pitches": _merge_by_key(
            remote.get("pitches") or [],
            local.get("pitches") or [],
            lambda item: item.get("jobKey"),
        ),
    }


# --------------------------------------------------------------------------- #
# Disk I/O
# --------------------------------------------------------------------------- #
def _read_document(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Sync file at %s is unreadable, treating it as empty", path)
        return {}
    return payload if isinstance(payload, dict) else {}


def _atomic_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".sync-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #
def sync() -> SyncCounts | None:
    """Pull remote changes into the local database, then write the merged union back.

    Returns the counts of what changed locally, or ``None`` when sync is disabled.
    """
    path = sync_file()
    if path is None:
        return None
    remote = _read_document(path)
    counts, _ = import_state(remote)
    local = export_state()
    _atomic_write(path, _merged_document(remote, local))
    if counts.total():
        logger.info("Sync pulled: %s", counts.as_dict())
    return counts
