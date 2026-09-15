"""Background worker: schedules checks and executes queued check runs."""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from watcher.constants import SCHEDULE_HOURS, WORKER_HEARTBEAT_SECONDS, WORKER_POLL_SECONDS
from watcher.models import CheckRun
from watcher.services.monitor import run_check_now
from watcher.services.runs import (
    claim_next_queued_run,
    enqueue_run,
    mark_interrupted_runs,
    write_worker_heartbeat,
)
from watcher.services.schedule import catch_up_is_needed

logger = logging.getLogger("watcher.worker")

SCHEDULED_JOB_ID = "scheduled-job-check"
HEARTBEAT_JOB_ID = "worker-heartbeat"


def _with_fresh_connection(function: Callable[[], Any]) -> Callable[[], None]:
    """Run a scheduler job with a usable database connection on its thread."""

    def wrapper() -> None:
        close_old_connections()
        try:
            function()
        except Exception:
            logger.exception("Scheduler job %s failed", getattr(function, "__name__", function))
        finally:
            close_old_connections()

    return wrapper


def enqueue_scheduled_run() -> None:
    run, created = enqueue_run(CheckRun.Trigger.SCHEDULED)
    if created:
        logger.info("Queued scheduled check run %s", run.pk)
    else:
        logger.info("Scheduled check skipped, run %s is already %s", run.pk, run.status)


def build_scheduler() -> BackgroundScheduler:
    timezone_name = settings.JOB_WATCHER_TIMEZONE
    scheduler = BackgroundScheduler(timezone=timezone_name)
    scheduler.add_job(
        _with_fresh_connection(enqueue_scheduled_run),
        CronTrigger(
            hour=",".join(str(hour) for hour in SCHEDULE_HOURS),
            minute=0,
            timezone=timezone_name,
        ),
        id=SCHEDULED_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _with_fresh_connection(write_worker_heartbeat),
        "interval",
        seconds=WORKER_HEARTBEAT_SECONDS,
        id=HEARTBEAT_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return scheduler


def prepare_worker() -> None:
    """Startup bookkeeping: close interrupted runs and queue a catch up if needed."""
    interrupted = mark_interrupted_runs()
    if interrupted:
        logger.warning("Marked %s interrupted check run(s) as failed", interrupted)
    if catch_up_is_needed():
        run, created = enqueue_run(CheckRun.Trigger.CATCH_UP)
        if created:
            logger.info("Queued catch up check run %s", run.pk)


def process_next_run() -> bool:
    """Claim and execute one queued run. Returns whether a run was executed."""
    run = claim_next_queued_run()
    if run is None:
        return False
    logger.info("Starting %s check run %s", run.trigger, run.pk)
    run_check_now(run.pk)
    logger.info("Finished check run %s", run.pk)
    return True


class Command(BaseCommand):
    help = "Run the Job Watcher scheduler and check run executor."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process queued runs once and exit (no scheduler).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["once"]:
            prepare_worker()
            while process_next_run():
                pass
            return

        stop = threading.Event()

        def request_stop(signum: int, _frame: Any) -> None:
            logger.info("Received signal %s, stopping worker", signum)
            stop.set()

        for name in ("SIGINT", "SIGTERM"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), request_stop)

        write_worker_heartbeat()
        prepare_worker()
        scheduler = build_scheduler()
        scheduler.start()
        logger.info(
            "Worker started, checks at %s in %s",
            ", ".join(f"{hour:02d}:00" for hour in SCHEDULE_HOURS),
            settings.JOB_WATCHER_TIMEZONE,
        )
        try:
            while not stop.is_set():
                close_old_connections()
                try:
                    if process_next_run():
                        continue
                except Exception:
                    logger.exception("Worker loop iteration failed")
                stop.wait(WORKER_POLL_SECONDS)
        finally:
            scheduler.shutdown(wait=False)
            close_old_connections()
            logger.info("Worker stopped")
