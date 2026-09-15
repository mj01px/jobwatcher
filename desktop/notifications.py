"""Tray notifications: new highlighted jobs after a run and daily overdue follow-ups.

Backend services live in ``watcher.services.notifications`` and
``watcher.services.preferences``; they are imported inside the functions because
Django is only configured after the desktop app boots.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

logger = logging.getLogger("watcher.desktop")

# Overdue reminders wait for the start of the working day.
OVERDUE_NOTICE_HOUR = 9
APP_TITLE = "Job Watcher"

Notify = Callable[[str, str], None]
T = TypeVar("T")


def new_jobs_message(jobs: Sequence[Any]) -> tuple[str, str] | None:
    """(message, title) for the jobs a run brought in, best score first."""
    if not jobs:
        return None
    best = jobs[0]
    if len(jobs) == 1:
        company = f" ({best.company_name})" if getattr(best, "company_name", "") else ""
        return f"{best.title}{company}, nota {best.score}", "Vaga nova pra você"
    return f"Melhor: {best.title} (nota {best.score})", f"{len(jobs)} vagas novas pra você"


def overdue_message(applications: Sequence[Any]) -> tuple[str, str] | None:
    if not applications:
        return None
    if len(applications) == 1:
        application = applications[0]
        step = application.next_step or application.job.title
        return step, "1 follow-up atrasado"
    return (
        "Abra Candidaturas para ver o que está pendente.",
        f"{len(applications)} follow-ups atrasados",
    )


def _with_db(action: Callable[[], T], default: T) -> T:
    from django.db import close_old_connections

    close_old_connections()
    try:
        return action()
    except Exception:
        logger.exception("Notification database work failed")
        return default
    finally:
        close_old_connections()


class Notifier:
    def __init__(self, notify: Notify) -> None:
        self._notify = notify

    def enabled(self) -> bool:
        from watcher.services.preferences import notifications_enabled

        return _with_db(notifications_enabled, True)

    def set_enabled(self, enabled: bool) -> None:
        from watcher.services.preferences import set_notifications_enabled

        _with_db(lambda: set_notifications_enabled(enabled), None)

    def after_run(self) -> None:
        """Called by the worker right after ``process_next_run()`` finished a run."""
        if not self.enabled():
            return

        def collect() -> list[Any]:
            from watcher.models import CheckRun
            from watcher.services.notifications import new_highlights_for_run

            run_id = (
                CheckRun.objects.exclude(finished_at=None)
                .order_by("-finished_at")
                .values_list("pk", flat=True)
                .first()
            )
            if run_id is None:
                return []
            # Read the attributes now, while the connection is open.
            return [
                _JobSummary(job.title, job.company_name, job.score)
                for job in new_highlights_for_run(run_id)
            ]

        message = new_jobs_message(_with_db(collect, []))
        if message:
            self._send(*message)
        self.maybe_overdue()

    def maybe_overdue(self, now: datetime | None = None) -> None:
        """At most one overdue reminder per local day, from 09:00 on."""
        if not self.enabled():
            return

        def collect() -> list[Any] | None:
            from django.conf import settings
            from watcher.services.notifications import overdue_applications
            from watcher.services.preferences import (
                overdue_notice_last_on,
                set_overdue_notice_last_on,
            )

            local_now = now or datetime.now(ZoneInfo(settings.JOB_WATCHER_TIMEZONE))
            if local_now.hour < OVERDUE_NOTICE_HOUR:
                return None
            today: date = local_now.date()
            if overdue_notice_last_on() == today:
                return None
            set_overdue_notice_last_on(today)
            return [
                _ApplicationSummary(
                    application.next_step, _JobSummary(application.job.title, "", 0)
                )
                for application in overdue_applications()
            ]

        applications = _with_db(collect, None)
        message = overdue_message(applications or [])
        if message:
            self._send(*message)

    def _send(self, message: str, title: str) -> None:
        # Windows truncates balloon text; keep inside its limits.
        self._notify(message[:250], title[:60])


class _JobSummary:
    __slots__ = ("company_name", "score", "title")

    def __init__(self, title: str, company_name: str, score: int) -> None:
        self.title = title
        self.company_name = company_name
        self.score = score


class _ApplicationSummary:
    __slots__ = ("job", "next_step")

    def __init__(self, next_step: str, job: _JobSummary) -> None:
        self.next_step = next_step
        self.job = job


__all__ = ["APP_TITLE", "Notifier", "new_jobs_message", "overdue_message"]
