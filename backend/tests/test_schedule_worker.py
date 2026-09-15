from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from django.utils import timezone

from tests.conftest import ago
from watcher.management.commands import run_worker
from watcher.models import CheckRun
from watcher.services.schedule import (
    catch_up_is_needed,
    most_recent_scheduled_time,
    next_scheduled_run,
)

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def local(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=SAO_PAULO)


class TestScheduleMath:
    def test_most_recent_slot_same_day(self) -> None:
        assert most_recent_scheduled_time(local(2026, 9, 14, 13, 30)) == local(2026, 9, 14, 12)

    def test_exact_slot_counts_as_past(self) -> None:
        assert most_recent_scheduled_time(local(2026, 9, 14, 15)) == local(2026, 9, 14, 15)

    def test_before_first_slot_uses_yesterday_last_slot(self) -> None:
        assert most_recent_scheduled_time(local(2026, 9, 14, 7)) == local(2026, 9, 13, 18)

    def test_next_run_later_today(self) -> None:
        assert next_scheduled_run(local(2026, 9, 14, 9, 1)) == local(2026, 9, 14, 12)

    def test_next_run_is_strictly_after_now(self) -> None:
        assert next_scheduled_run(local(2026, 9, 14, 12)) == local(2026, 9, 14, 15)

    def test_next_run_after_last_slot_is_tomorrow_morning(self) -> None:
        assert next_scheduled_run(local(2026, 9, 14, 19)) == local(2026, 9, 15, 9)

    def test_next_run_accepts_utc_input(self) -> None:
        utc_now = datetime(2026, 9, 14, 12, 30, tzinfo=ZoneInfo("UTC"))  # 09:30 in Sao Paulo
        assert next_scheduled_run(utc_now) == local(2026, 9, 14, 12)


@pytest.mark.django_db
class TestCatchUp:
    def _finished(self, status: str, finished_at: datetime) -> CheckRun:
        return CheckRun.objects.create(
            trigger=CheckRun.Trigger.SCHEDULED,
            status=status,
            started_at=finished_at - timedelta(seconds=10),
            finished_at=finished_at,
        )

    def test_needed_without_any_completed_run(self) -> None:
        assert catch_up_is_needed(local(2026, 9, 14, 10)) is True

    def test_not_needed_when_last_run_is_after_latest_slot(self) -> None:
        self._finished(CheckRun.Status.SUCCESS, local(2026, 9, 14, 9, 1))
        assert catch_up_is_needed(local(2026, 9, 14, 11)) is False

    def test_needed_when_last_run_is_before_latest_slot(self) -> None:
        self._finished(CheckRun.Status.PARTIAL, local(2026, 9, 14, 9, 1))
        assert catch_up_is_needed(local(2026, 9, 14, 12, 30)) is True

    def test_failed_runs_do_not_count(self) -> None:
        self._finished(CheckRun.Status.FAILED, local(2026, 9, 14, 12, 5))
        assert catch_up_is_needed(local(2026, 9, 14, 12, 30)) is True


@pytest.mark.django_db
class TestWorker:
    def test_prepare_marks_interrupted_and_queues_catch_up(self) -> None:
        running = CheckRun.objects.create(
            trigger=CheckRun.Trigger.MANUAL, status=CheckRun.Status.RUNNING, started_at=ago(90)
        )
        run_worker.prepare_worker()
        running.refresh_from_db()
        assert running.status == CheckRun.Status.FAILED
        queued = CheckRun.objects.get(status=CheckRun.Status.QUEUED)
        assert queued.trigger == CheckRun.Trigger.CATCH_UP

    def test_prepare_skips_catch_up_after_recent_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(run_worker, "catch_up_is_needed", lambda: False)
        run_worker.prepare_worker()
        assert not CheckRun.objects.filter(status=CheckRun.Status.QUEUED).exists()

    def test_process_next_run_claims_and_executes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        executed: list[int] = []
        monkeypatch.setattr(run_worker, "run_check_now", executed.append)
        run = CheckRun.objects.create(trigger=CheckRun.Trigger.MANUAL)
        assert run_worker.process_next_run() is True
        assert executed == [run.pk]
        run.refresh_from_db()
        assert run.status == CheckRun.Status.RUNNING

    def test_process_next_run_is_idle_without_queue(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(run_worker, "run_check_now", lambda _run_id: None)
        assert run_worker.process_next_run() is False

    def test_scheduled_enqueue_is_skipped_while_running(self) -> None:
        CheckRun.objects.create(
            trigger=CheckRun.Trigger.MANUAL,
            status=CheckRun.Status.RUNNING,
            started_at=timezone.now(),
        )
        run_worker.enqueue_scheduled_run()
        assert CheckRun.objects.count() == 1

    def test_scheduled_enqueue_creates_scheduled_run(self) -> None:
        run_worker.enqueue_scheduled_run()
        assert CheckRun.objects.get().trigger == CheckRun.Trigger.SCHEDULED

    def test_scheduler_configuration(self) -> None:
        scheduler = run_worker.build_scheduler()
        job = scheduler.get_job(run_worker.SCHEDULED_JOB_ID)
        assert job is not None
        assert isinstance(job.trigger, CronTrigger)
        fields = {field.name: str(field) for field in job.trigger.fields}
        assert fields["hour"] == "9,12,15,18"
        assert fields["minute"] == "0"
        assert str(job.trigger.timezone) == "America/Sao_Paulo"
        assert job.coalesce is True
        assert job.max_instances == 1
        assert job.misfire_grace_time == 3600

        heartbeat = scheduler.get_job(run_worker.HEARTBEAT_JOB_ID)
        assert heartbeat is not None
        assert isinstance(heartbeat.trigger, IntervalTrigger)
        assert heartbeat.trigger.interval == timedelta(seconds=10)
