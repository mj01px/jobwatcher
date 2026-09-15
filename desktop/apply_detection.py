"""Detects InHire applications sent from inside Job Watcher.

The frontend calls ``window.pywebview.api.open_job(id)`` for InHire jobs. The job
page opens in a child window that gets ``inhire_hook.js`` injected on every load;
the hook reports a successful ``POST /job-talents/public/<jobId>/talents`` back
through that window's bridge. A report only counts when the id is the job that
window shows, and then the job moves into the applications funnel.

pywebview exposes every public attribute of a ``js_api`` object to the page, so
the bridge classes keep their state in underscore attributes and offer exactly
one public method each.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import webview

logger = logging.getLogger("watcher.desktop")

HOOK_PATH = Path(__file__).resolve().parent / "inhire_hook.js"
DETECTED_EVENT = "jobwatcher:application-detected"

Notify = Callable[[str, str], None]


def _as_job_id(value: Any) -> int | None:
    """Accept a positive integer id coming from JavaScript (int or integral float)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int) and value > 0:
        return value
    return None


def _is_inhire_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and host.endswith(".inhire.app")


class MainWindowApi:
    """``js_api`` of the main window: only ``open_job``."""

    def __init__(self, detector: ApplyDetector) -> None:
        self._detector = detector

    def open_job(self, job_id: Any) -> dict[str, Any]:
        return self._detector._open_job(job_id)


class JobWindowApi:
    """``js_api`` of an InHire job window: only ``report_application``."""

    def __init__(self, detector: ApplyDetector, job_id: int, external_id: str) -> None:
        self._detector = detector
        self._job_id = job_id
        self._external_id = external_id

    def report_application(self, external_id: Any) -> bool:
        return self._detector._on_report(self._job_id, self._external_id, external_id)


class ApplyDetector:
    def __init__(self, notify: Notify) -> None:
        self._notify = notify
        self._main_window: Any = None
        self._windows: dict[int, Any] = {}
        self._lock = threading.Lock()
        self._hook: str | None = None

    def main_window_api(self) -> MainWindowApi:
        return MainWindowApi(self)

    def attach_main_window(self, window: Any) -> None:
        self._main_window = window

    def close_all(self) -> None:
        with self._lock:
            windows = list(self._windows.values())
            self._windows.clear()
        for window in windows:
            try:
                window.destroy()
            except Exception:
                logger.exception("Could not close a job window")

    # Called from the main window bridge (a pywebview worker thread).
    def _open_job(self, raw_job_id: Any) -> dict[str, Any]:
        job_id = _as_job_id(raw_job_id)
        if job_id is None:
            return {"ok": False, "error": "invalid_job_id"}

        with self._lock:
            existing = self._windows.get(job_id)
        if existing is not None:
            try:
                existing.show()
                existing.restore()
                return {"ok": True, "reused": True}
            except Exception:
                # The window is gone (closed outside our event); open a fresh one.
                with self._lock:
                    self._windows.pop(job_id, None)

        job = self._load_inhire_job(job_id)
        if job is None:
            return {"ok": False, "error": "not_an_inhire_job"}
        external_id, title, url = job

        try:
            window = webview.create_window(
                title,
                url=url,
                width=1100,
                height=820,
                min_size=(700, 500),
                js_api=JobWindowApi(self, job_id, external_id),
            )
        except Exception:
            logger.exception("Could not open the job window for job %s", job_id)
            return {"ok": False, "error": "window_failed"}

        window.events.loaded += lambda *_args: self._inject_hook(window)
        window.events.closed += lambda *_args: self._forget(job_id, window)
        with self._lock:
            self._windows[job_id] = window
        return {"ok": True, "reused": False}

    def _load_inhire_job(self, job_id: int) -> tuple[str, str, str] | None:
        from django.db import close_old_connections
        from watcher.models import Job

        close_old_connections()
        try:
            job = Job.objects.select_related("source").filter(pk=job_id).first()
            if job is None or job.source.kind != "inhire" or not _is_inhire_url(job.url):
                return None
            return str(job.external_id), job.title, job.url
        except Exception:
            logger.exception("Could not load job %s for the job window", job_id)
            return None
        finally:
            close_old_connections()

    def _hook_script(self) -> str:
        if self._hook is None:
            self._hook = HOOK_PATH.read_text(encoding="utf-8")
        return self._hook

    def _inject_hook(self, window: Any) -> None:
        try:
            window.evaluate_js(self._hook_script())
        except Exception:
            logger.exception("Could not inject the application hook")

    def _forget(self, job_id: int, window: Any) -> None:
        with self._lock:
            if self._windows.get(job_id) is window:
                del self._windows[job_id]

    # Called from a job window bridge (a pywebview worker thread).
    def _on_report(self, job_id: int, expected_external_id: str, reported: Any) -> bool:
        if (
            not isinstance(reported, str)
            or reported.strip().lower() != expected_external_id.lower()
        ):
            logger.warning("Ignored an application report that does not match job %s", job_id)
            return False

        from django.db import close_old_connections
        from pipeline.services import register_detected_application

        close_old_connections()
        try:
            application, changed = register_detected_application(job_id)
            application_id = application.pk
            title = application.job.title
        except Exception:
            logger.exception("Could not register the detected application for job %s", job_id)
            return False
        finally:
            close_old_connections()

        logger.info(
            "Detected InHire application for job %s (application %s, changed=%s)",
            job_id,
            application_id,
            changed,
        )
        self._dispatch_to_main(job_id, application_id, changed)
        if changed:
            self._notify(f"Candidatura registrada: {title}", "Job Watcher")
        return True

    def _dispatch_to_main(self, job_id: int, application_id: int, changed: bool) -> None:
        if self._main_window is None:
            return
        detail = json.dumps({"jobId": job_id, "applicationId": application_id, "changed": changed})
        script = (
            f"window.dispatchEvent(new CustomEvent({json.dumps(DETECTED_EVENT)}, "
            f"{{ detail: {detail} }}))"
        )
        try:
            self._main_window.evaluate_js(script)
        except Exception:
            logger.exception("Could not notify the dashboard about the detected application")
