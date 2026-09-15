from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from pipeline.models import Application
from watcher.models import CheckRun, CheckRunSource, Job, Source


@pytest.fixture(autouse=True)
def isolated_secrets(
    settings: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """Every test gets its own secrets file and no key from the real environment."""
    path = tmp_path / "secrets.json"
    settings.SECRETS_FILE = path
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    yield path


@pytest.fixture(autouse=True)
def no_inhire_job_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run tests patch the InHire listing; never let job page fetches hit the network.

    Tests that exercise the job pages patch ``monitor.fetch_job_details`` again.
    """

    async def no_details(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr("watcher.services.monitor.fetch_job_details", no_details)


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def csrf_client() -> APIClient:
    return APIClient(enforce_csrf_checks=True)


@pytest.fixture
def clean_sources(db: None) -> None:
    """Remove the seeded sources so a test controls every row."""
    CheckRunSource.objects.all().delete()
    CheckRun.objects.all().delete()
    Application.objects.all().delete()
    Job.objects.all().delete()
    Source.objects.all().delete()


@pytest.fixture
def source(db: None) -> Source:
    return Source.objects.create(name="Acme", target="https://acme.inhire.app/vagas")


MakeJob = Callable[..., Job]


@pytest.fixture
def make_job(db: None) -> MakeJob:
    counter = {"value": 0}

    def factory(source: Source, **fields: Any) -> Job:
        counter["value"] += 1
        index = counter["value"]
        now = timezone.now()
        values: dict[str, Any] = {
            "external_id": f"job-{index}",
            "key": f"{source.kind}:job-{index}-{source.pk}",
            "title": f"Role {index:04d}",
            "url": f"https://example.test/vagas/{index}",
            "company_name": source.name,
            "first_seen_at": now,
            "last_seen_at": now,
        }
        values.update(fields)
        return Job.objects.create(source=source, **values)

    return factory


def ago(seconds: float) -> datetime:
    return timezone.now() - timedelta(seconds=seconds)


def data_of(response: Any) -> Any:
    body = response.json()
    assert body["error"] is None, body
    assert body["meta"]["requestId"]
    return body["data"]


def error_of(response: Any) -> dict[str, Any]:
    body = response.json()
    assert body["data"] is None, body
    return body["error"]
