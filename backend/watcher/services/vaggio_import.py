"""One way import of a Vaggio SQLite database into Job Watcher.

Reads the Vaggio file directly (no Vaggio code), so it works with the plain
``vaggio.sqlite3``. Idempotent: running it again updates rows, never duplicates.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone

from pipeline.models import Application, Interaction, Pitch
from watcher.constants import (
    DOSSIER_KEY,
    IMPORT_NOTE,
    IMPORTED_SOURCE_TARGET,
    MANUAL_SOURCE_TARGET,
    PITCH_MAX_CHARS_KEY,
    SCORING_PROFILE_KEY,
)
from watcher.models import Job, Source
from watcher.services.collection import github_key, gupy_key, manual_key
from watcher.services.monitor import expire_old_jobs
from watcher.services.preferences import set_setting
from watcher.services.scoring import rescore_all

PLACEHOLDER_NAMES = {
    Source.Kind.GUPY: "Gupy (imported from Vaggio)",
    Source.Kind.GITHUB: "GitHub (imported from Vaggio)",
}
FILLABLE_FIELDS = ("company_name", "location", "description", "published_at")


class VaggioImportError(RuntimeError):
    """The file is missing or is not a Vaggio database."""


@dataclass
class ImportCounts:
    jobs_created: int = 0
    jobs_updated: int = 0
    jobs_skipped: int = 0
    jobs_archived: int = 0
    applications_created: int = 0
    applications_updated: int = 0
    interactions_created: int = 0
    pitches_imported: int = 0
    profile_imported: bool = False
    expired: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _date(value: Any) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def _connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise VaggioImportError(f"Vaggio database not found at {path}")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    if "jobs_job" not in tables:
        connection.close()
        raise VaggioImportError(f"{path} does not look like a Vaggio database (no jobs_job table)")
    return connection


def _rows(connection: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    if table not in tables:
        return []
    # ``table`` is always one of the fixed Vaggio table names above, never input.
    return list(connection.execute(f"SELECT * FROM {table} ORDER BY id"))


def _placeholder(kind: str) -> Source:
    if kind == Source.Kind.MANUAL:
        source, _ = Source.objects.get_or_create(
            kind=Source.Kind.MANUAL,
            target=MANUAL_SOURCE_TARGET,
            defaults={"name": "Manual", "is_active": False, "is_hidden": True},
        )
        return source
    source, _ = Source.objects.get_or_create(
        kind=kind,
        target=IMPORTED_SOURCE_TARGET,
        defaults={"name": PLACEHOLDER_NAMES[kind], "is_active": False, "is_hidden": True},
    )
    return source


def _job_identity(row: sqlite3.Row) -> tuple[str, str, str] | None:
    """``(kind, key, external_id)`` of a Vaggio job, or ``None`` for unknown sources."""
    kind = row["source"]
    url = row["url"] or ""
    source_id = row["source_id"] or ""
    if kind == Source.Kind.GUPY:
        return kind, gupy_key(source_id, url), source_id or url
    if kind == Source.Kind.GITHUB:
        return kind, github_key(url), source_id or url
    if kind == Source.Kind.MANUAL:
        key = manual_key(url)
        return kind, key, key.removeprefix("manual:")
    return None


def _import_job(row: sqlite3.Row, counts: ImportCounts) -> Job | None:
    identity = _job_identity(row)
    if identity is None:
        counts.jobs_skipped += 1
        return None
    kind, key, external_id = identity
    values = {
        "company_name": (row["company"] or "")[:255],
        "location": (row["location"] or "")[:255],
        "description": row["description"] or "",
        "published_at": _datetime(row["published_at"]),
    }
    existing = Job.objects.filter(key=key).first()
    if existing is not None:
        changed = [
            field for field in FILLABLE_FIELDS if not getattr(existing, field) and values[field]
        ]
        for field in changed:
            setattr(existing, field, values[field])
        if changed:
            existing.save(update_fields=changed)
        counts.jobs_updated += 1
        return existing

    created_at = _datetime(row["created_at"]) or timezone.now()
    updated_at = _datetime(row["updated_at"]) or created_at
    job = Job(
        source=_placeholder(kind),
        key=key,
        external_id=external_id[:1000],
        title=(row["title"] or "")[:500],
        url=(row["url"] or "")[:1000],
        work_mode=row["work_mode"] or Job.WorkMode.UNKNOWN,
        seniority=row["seniority"] or Job.Seniority.UNKNOWN,
        score=row["score"] or 0,
        score_tags=json.loads(row["tags"] or "[]"),
        arrived_new=False,
        first_seen_at=created_at,
        last_seen_at=updated_at,
        **values,
    )
    if row["discarded"]:
        job.status = Job.Status.ARCHIVED
        job.archive_source = Job.ArchiveSource.MANUAL
        job.archive_reason = "not_interested"
        job.archive_note = IMPORT_NOTE
        job.archived_at = updated_at
        counts.jobs_archived += 1
    job.save()
    counts.jobs_created += 1
    return job


def _import_application(row: sqlite3.Row, job: Job, counts: ImportCounts) -> Application:
    values = {
        "status": row["status"],
        "priority": row["priority"] or 3,
        "applied_on": _date(row["applied_on"]),
        "next_step": row["next_step"] or "",
        "next_step_on": _date(row["next_step_on"]),
        "contact": row["contact"] or "",
        "has_referral": bool(row["has_referral"]),
        "notes": row["notes"] or "",
        "created_at": _datetime(row["created_at"]) or timezone.now(),
        "updated_at": _datetime(row["updated_at"]) or timezone.now(),
    }
    application, created = Application.objects.update_or_create(job=job, defaults=values)
    if created:
        counts.applications_created += 1
    else:
        counts.applications_updated += 1
    return application


def import_vaggio(path: Path) -> ImportCounts:
    """Import jobs, applications, interactions, pitches and profile from Vaggio.

    Raises:
        VaggioImportError: when the file is missing or not a Vaggio database.
    """
    counts = ImportCounts()
    connection = _connect(path)
    try:
        with transaction.atomic():
            jobs_by_vaggio_id: dict[int, Job] = {}
            for row in _rows(connection, "jobs_job"):
                job = _import_job(row, counts)
                if job is not None:
                    jobs_by_vaggio_id[row["id"]] = job

            applications_by_vaggio_id: dict[int, Application] = {}
            for row in _rows(connection, "pipeline_application"):
                job = jobs_by_vaggio_id.get(row["job_id"])
                if job is not None:
                    applications_by_vaggio_id[row["id"]] = _import_application(row, job, counts)

            for row in _rows(connection, "pipeline_interaction"):
                application = applications_by_vaggio_id.get(row["application_id"])
                if application is None:
                    continue
                created_at = _datetime(row["created_at"]) or timezone.now()
                _, created = Interaction.objects.get_or_create(
                    application=application,
                    date=_date(row["date"]) or created_at.date(),
                    title=(row["title"] or "")[:200],
                    created_at=created_at,
                    defaults={
                        "detail": row["detail"] or "",
                        "updated_at": _datetime(row["updated_at"]) or created_at,
                    },
                )
                counts.interactions_created += int(created)

            latest_pitch: dict[int, sqlite3.Row] = {}
            for row in _rows(connection, "jobs_pitch"):
                current = latest_pitch.get(row["job_id"])
                if current is None or (row["created_at"] or "") >= (current["created_at"] or ""):
                    latest_pitch[row["job_id"]] = row
            for vaggio_job_id, row in latest_pitch.items():
                job = jobs_by_vaggio_id.get(vaggio_job_id)
                if job is None:
                    continue
                created_at = _datetime(row["created_at"]) or timezone.now()
                if Pitch.objects.filter(job=job, text=row["texto"]).exists():
                    continue
                Pitch.objects.filter(job=job).delete()
                Pitch.objects.create(
                    job=job,
                    text=row["texto"],
                    model=(row["modelo"] or "")[:80],
                    instruction=(row["instrucao"] or "")[:300],
                    max_chars=row["max_chars"] or 1200,
                    input_tokens=row["tokens_entrada"] or 0,
                    output_tokens=row["tokens_saida"] or 0,
                    thinking_tokens=row["tokens_pensamento"] or 0,
                    created_at=created_at,
                    updated_at=_datetime(row["updated_at"]) or created_at,
                )
                counts.pitches_imported += 1

            profiles = _rows(connection, "accounts_perfil")
            if profiles:
                profile = profiles[0]
                if (profile["dossie"] or "").strip():
                    set_setting(DOSSIER_KEY, profile["dossie"])
                    counts.profile_imported = True
                if profile["pitch_max_chars"]:
                    set_setting(PITCH_MAX_CHARS_KEY, int(profile["pitch_max_chars"]))
                terms = json.loads(profile["termos"] or "{}")
                if isinstance(terms, dict) and terms:
                    set_setting(SCORING_PROFILE_KEY, terms)

            rescore_all()
            counts.expired = expire_old_jobs()
    finally:
        connection.close()
    return counts
