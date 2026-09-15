"""Tests for the cross-machine sync service (``watcher.services.sync``)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from django.utils import timezone

from pipeline.models import Application, Interaction
from watcher.constants import DOSSIER_KEY
from watcher.models import Job, Setting, Source
from watcher.services import sync
from watcher.services.secrets import GEMINI_API_KEY, get_secret

from .conftest import MakeJob


def _iso(dt: Any) -> str:
    return dt.isoformat()


# --------------------------------------------------------------------------- #
# Location
# --------------------------------------------------------------------------- #
def test_sync_file_uses_configured_dir(settings: Any, tmp_path: Path) -> None:
    settings.SYNC_DIR = str(tmp_path)
    assert sync.sync_file() == tmp_path / "JobWatcher" / "sync.json"
    assert sync.is_enabled()


def test_empty_sync_dir_disables_sync(settings: Any) -> None:
    settings.SYNC_DIR = ""
    assert sync.sync_file() is None
    assert not sync.is_enabled()
    assert sync.sync() is None


# --------------------------------------------------------------------------- #
# Export / import round trip
# --------------------------------------------------------------------------- #
def test_export_includes_applications_with_job_key(
    source: Source, make_job: MakeJob
) -> None:
    job = make_job(source, key="inhire:abc")
    Application.objects.create(job=job, status=Application.Status.APPLIED)

    document = sync.export_state()
    apps = document["applications"]
    assert len(apps) == 1
    assert apps[0]["jobKey"] == "inhire:abc"
    assert apps[0]["job"]["key"] == "inhire:abc"
    assert apps[0]["status"] == Application.Status.APPLIED


def test_import_creates_missing_job_and_application(db: None) -> None:
    now = timezone.now()
    remote = {
        "applications": [
            {
                "jobKey": "inhire:remote-1",
                "job": {
                    "key": "inhire:remote-1",
                    "kind": "inhire",
                    "externalId": "remote-1",
                    "title": "Backend Dev",
                    "url": "https://acme.inhire.app/vagas/remote-1",
                },
                "status": "applied",
                "createdAt": _iso(now),
                "updatedAt": _iso(now),
                "interactions": [
                    {"date": _iso(now.date()), "title": "Enviei", "createdAt": _iso(now)}
                ],
            }
        ]
    }

    counts, _ = sync.import_state(remote)

    job = Job.objects.get(key="inhire:remote-1")
    application = Application.objects.get(job=job)
    assert application.status == "applied"
    assert counts.applications == 1
    assert Interaction.objects.filter(application=application).count() == 1


def test_import_newer_remote_overwrites_local(
    source: Source, make_job: MakeJob
) -> None:
    job = make_job(source, key="inhire:x")
    old = timezone.now() - timedelta(days=1)
    Application.objects.create(
        job=job, status=Application.Status.INTEREST, updated_at=old, created_at=old
    )

    remote = {
        "applications": [
            {
                "jobKey": "inhire:x",
                "job": {"key": "inhire:x", "kind": "inhire"},
                "status": "interview",
                "updatedAt": _iso(timezone.now()),
            }
        ]
    }
    sync.import_state(remote)

    assert Application.objects.get(job=job).status == "interview"


def test_import_older_remote_is_ignored(source: Source, make_job: MakeJob) -> None:
    job = make_job(source, key="inhire:y")
    now = timezone.now()
    Application.objects.create(
        job=job, status=Application.Status.OFFER, updated_at=now, created_at=now
    )

    remote = {
        "applications": [
            {
                "jobKey": "inhire:y",
                "job": {"key": "inhire:y", "kind": "inhire"},
                "status": "rejected",
                "updatedAt": _iso(now - timedelta(days=2)),
            }
        ]
    }
    sync.import_state(remote)

    assert Application.objects.get(job=job).status == "offer"


def test_import_setting_newest_wins(db: None) -> None:
    Setting.objects.update_or_create(
        key=DOSSIER_KEY,
        defaults={"value": "old dossier", "updated_at": timezone.now() - timedelta(hours=1)},
    )
    remote = {
        "settings": {DOSSIER_KEY: {"value": "new dossier", "updatedAt": _iso(timezone.now())}}
    }

    counts, _ = sync.import_state(remote)

    assert Setting.objects.get(key=DOSSIER_KEY).value == "new dossier"
    assert counts.settings == 1


def test_import_secret_fills_only_when_missing(db: None) -> None:
    remote = {"secrets": {GEMINI_API_KEY: "sk-remote"}}

    counts, _ = sync.import_state(remote)
    assert get_secret(GEMINI_API_KEY) == "sk-remote"
    assert counts.secrets == 1

    # A second import with a different value must not clobber the local key.
    sync.import_state({"secrets": {GEMINI_API_KEY: "sk-other"}})
    assert get_secret(GEMINI_API_KEY) == "sk-remote"


# --------------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------------- #
def test_merge_keeps_newest_record_per_key() -> None:
    now = timezone.now()
    remote = [{"jobKey": "k", "status": "applied", "updatedAt": _iso(now - timedelta(days=1))}]
    local = [{"jobKey": "k", "status": "interview", "updatedAt": _iso(now)}]

    merged = sync._merge_by_key(remote, local, lambda item: item.get("jobKey"))

    assert len(merged) == 1
    assert merged[0]["status"] == "interview"


def test_sync_round_trip_writes_and_reads_file(
    settings: Any, tmp_path: Path, source: Source, make_job: MakeJob
) -> None:
    settings.SYNC_DIR = str(tmp_path)
    job = make_job(source, key="inhire:rt")
    Application.objects.create(job=job, status=Application.Status.APPLIED)

    counts = sync.sync()

    assert counts is not None
    path = sync.sync_file()
    assert path is not None and path.is_file()
    assert any(app["jobKey"] == "inhire:rt" for app in sync._read_document(path)["applications"])
