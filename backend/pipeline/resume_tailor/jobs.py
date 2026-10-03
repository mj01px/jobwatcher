"""Run resume generation in the background so a slow AI call never hits the
client's request timeout.

The tailoring takes 25-105s (a full resume rewrite). Held open as one HTTP
request, that regularly exceeds the desktop webview's ~60s idle timeout, so the
POST only *starts* the work and the client polls for the PDF. One generation runs
at a time (it burns free-tier quota); results are kept briefly for the poller,
then dropped. In-memory is enough: the app is a single process.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field

from django.db import connection

from pipeline.ai.providers.base import LLMNotConfiguredError, LLMUnavailableError
from pipeline.resume_tailor.service import build_filename, generate_tailored_pdf
from watcher.models import Job

logger = logging.getLogger(__name__)

RESULT_TTL_SECONDS = 600.0
MAX_JOBS = 32


class ResumeBusyError(RuntimeError):
    """A generation is already running (only one at a time)."""


@dataclass
class ResumeJob:
    status: str = "pending"  # "pending" | "done" | "error"
    pdf: bytes | None = None
    filename: str = ""
    error_code: str = ""
    error_message: str = ""
    created_at: float = field(default_factory=time.monotonic)


_jobs: dict[str, ResumeJob] = {}
_lock = threading.Lock()
_running = False


def _prune_locked() -> None:
    now = time.monotonic()
    for token in [t for t, j in _jobs.items() if now - j.created_at > RESULT_TTL_SECONDS]:
        _jobs.pop(token, None)
    if len(_jobs) > MAX_JOBS:
        oldest = sorted(_jobs, key=lambda t: _jobs[t].created_at)[: len(_jobs) - MAX_JOBS]
        for token in oldest:
            _jobs.pop(token, None)


def start(job: Job, resume_text: str) -> str:
    """Start a background generation and return its poll token.

    Raises:
        ResumeBusyError: when a generation is already running.
    """
    global _running
    with _lock:
        if _running:
            raise ResumeBusyError("A resume is already being generated")
        _prune_locked()
        token = uuid.uuid4().hex
        _jobs[token] = ResumeJob()
        _running = True
    threading.Thread(
        target=_run, args=(token, job, resume_text), daemon=True, name="resume-gen"
    ).start()
    return token


def _run(token: str, job: Job, resume_text: str) -> None:
    global _running
    code = message = ""
    pdf = filename = None
    try:
        pdf, tailored = generate_tailored_pdf(job, resume_text)
        filename = build_filename(tailored, job)
    except LLMNotConfiguredError as error:
        code, message = "AI_NOT_CONFIGURED", str(error)
    except LLMUnavailableError as error:
        code, message = "AI_UNAVAILABLE", str(error)
    except Exception:
        # Any failure must finish the job as an error, never leave it hanging.
        logger.exception("resume generation failed for job %s", job.pk)
        code, message = "INTERNAL_ERROR", "Resume generation failed"
    finally:
        connection.close()  # this thread opened its own DB connection
        with _lock:
            result = _jobs.get(token)
            if result is not None:
                if pdf is not None and filename is not None:
                    result.pdf, result.filename, result.status = pdf, filename, "done"
                else:
                    result.error_code, result.error_message, result.status = code, message, "error"
            _running = False


def take(token: str) -> ResumeJob | None:
    """Return the job for ``token``; a finished one is removed (one-shot)."""
    with _lock:
        result = _jobs.get(token)
        if result is not None and result.status != "pending":
            _jobs.pop(token, None)
        return result
