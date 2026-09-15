from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from tests.conftest import ago
from watcher.constants import INTERRUPTED_RUN_ERROR, WORKER_HEARTBEAT_KEY
from watcher.models import CheckRun, Setting
from watcher.services.runs import (
    claim_next_queued_run,
    enqueue_run,
    mark_interrupted_runs,
    record_run_progress,
    run_duration_seconds,
    run_looks_stalled,
    worker_is_online,
    write_worker_heartbeat,
)


def _run(**fields: object) -> CheckRun:
    values: dict[str, object] = {"trigger": CheckRun.Trigger.MANUAL}
    values.update(fields)
    return CheckRun.objects.create(**values)


@pytest.mark.django_db
class TestQueue:
    def test_enqueue_creates_a_queued_run(self) -> None:
        run, created = enqueue_run(CheckRun.Trigger.MANUAL)
        assert created is True
        assert run.status == CheckRun.Status.QUEUED
        assert run.trigger == CheckRun.Trigger.MANUAL

    def test_enqueue_returns_the_active_run_instead_of_duplicating(self) -> None:
        first, _ = enqueue_run(CheckRun.Trigger.MANUAL)
        second, created = enqueue_run(CheckRun.Trigger.SCHEDULED)
        assert created is False
        assert second.pk == first.pk
        assert CheckRun.objects.count() == 1

    def test_enqueue_while_running_returns_running_run(self) -> None:
        running = _run(status=CheckRun.Status.RUNNING, started_at=timezone.now())
        run, created = enqueue_run(CheckRun.Trigger.MANUAL)
        assert (run.pk, created) == (running.pk, False)

    def test_enqueue_after_finished_run_creates_new(self) -> None:
        _run(status=CheckRun.Status.SUCCESS, finished_at=timezone.now())
        _, created = enqueue_run(CheckRun.Trigger.MANUAL)
        assert created is True

    def test_claim_moves_oldest_queued_run_to_running(self) -> None:
        older = _run(requested_at=ago(60))
        _run(requested_at=ago(10))
        claimed = claim_next_queued_run()
        assert claimed is not None
        assert claimed.pk == older.pk
        older.refresh_from_db()
        assert older.status == CheckRun.Status.RUNNING
        assert older.started_at is not None
        assert older.heartbeat_at is not None

    def test_claim_returns_none_without_queued_runs(self) -> None:
        assert claim_next_queued_run() is None

    def test_claim_waits_while_a_run_is_running(self) -> None:
        _run(status=CheckRun.Status.RUNNING, started_at=timezone.now())
        _run()
        assert claim_next_queued_run() is None


@pytest.mark.django_db
class TestInterruptedRuns:
    def test_running_row_is_marked_failed(self) -> None:
        run = _run(status=CheckRun.Status.RUNNING, started_at=ago(60), sources_total=30)
        assert mark_interrupted_runs() == 1
        run.refresh_from_db()
        assert run.status == CheckRun.Status.FAILED
        assert run.finished_at is not None
        assert run.error == INTERRUPTED_RUN_ERROR

    def test_existing_error_is_kept(self) -> None:
        run = _run(status=CheckRun.Status.RUNNING, started_at=ago(60), error="Alpha: boom")
        mark_interrupted_runs()
        run.refresh_from_db()
        assert run.error == "Alpha: boom"

    def test_finished_runs_are_left_untouched(self) -> None:
        run = _run(status=CheckRun.Status.SUCCESS, started_at=ago(60), finished_at=ago(10))
        assert mark_interrupted_runs() == 0
        run.refresh_from_db()
        assert run.status == CheckRun.Status.SUCCESS

    def test_queued_runs_are_left_for_the_worker(self) -> None:
        run = _run()
        assert mark_interrupted_runs() == 0
        run.refresh_from_db()
        assert run.status == CheckRun.Status.QUEUED


@pytest.mark.django_db
class TestRunProgressPersistence:
    def test_progress_accumulates_and_moves_heartbeat(self) -> None:
        run = _run(
            status=CheckRun.Status.RUNNING,
            started_at=ago(5),
            heartbeat_at=ago(5),
            sources_total=3,
        )
        record_run_progress(run.pk, checked=1, found=10, new=2, archived=1)
        record_run_progress(run.pk, checked=1, found=5, new=0, archived=0)
        run.refresh_from_db()
        assert run.sources_checked == 2
        assert run.jobs_found == 15
        assert run.jobs_new == 2
        assert run.jobs_archived == 1
        assert run.heartbeat_at is not None
        assert run.started_at is not None
        assert run.heartbeat_at > run.started_at

    def test_failed_source_still_refreshes_heartbeat_without_counts(self) -> None:
        run = _run(status=CheckRun.Status.RUNNING, started_at=ago(5), heartbeat_at=ago(5))
        before = run.heartbeat_at
        record_run_progress(run.pk)
        run.refresh_from_db()
        assert run.sources_checked == 0
        assert run.jobs_found == 0
        assert run.heartbeat_at is not None
        assert before is not None
        assert run.heartbeat_at > before


class TestStalledDetection:
    def _run(self, **fields: object) -> CheckRun:
        values: dict[str, object] = {
            "status": CheckRun.Status.RUNNING,
            "started_at": ago(600),
            "heartbeat_at": ago(5),
        }
        values.update(fields)
        return CheckRun(**values)

    def test_fresh_heartbeat_is_not_stalled(self) -> None:
        assert run_looks_stalled(self._run()) is False

    def test_old_heartbeat_is_stalled(self) -> None:
        assert run_looks_stalled(self._run(heartbeat_at=ago(3600))) is True

    def test_missing_heartbeat_falls_back_to_started_at(self) -> None:
        assert run_looks_stalled(self._run(heartbeat_at=None)) is True

    def test_finished_run_is_never_stalled(self) -> None:
        run = self._run(status=CheckRun.Status.SUCCESS, heartbeat_at=ago(3600))
        assert run_looks_stalled(run) is False

    def test_none_is_not_stalled(self) -> None:
        assert run_looks_stalled(None) is False


class TestRunDuration:
    def test_duration_is_rounded_seconds(self) -> None:
        started = timezone.now()
        run = CheckRun(started_at=started, finished_at=started + timedelta(seconds=8.7))
        assert run_duration_seconds(run) == 8.7

    def test_unfinished_run_has_no_duration(self) -> None:
        assert run_duration_seconds(CheckRun(started_at=ago(10), finished_at=None)) is None

    def test_unstarted_run_has_no_duration(self) -> None:
        assert run_duration_seconds(CheckRun(started_at=None, finished_at=None)) is None


@pytest.mark.django_db
class TestWorkerHeartbeat:
    def test_offline_without_heartbeat(self) -> None:
        assert worker_is_online() is False

    def test_online_right_after_heartbeat(self) -> None:
        write_worker_heartbeat()
        assert worker_is_online() is True

    def test_offline_when_heartbeat_is_old(self) -> None:
        Setting.objects.create(key=WORKER_HEARTBEAT_KEY, value=ago(120).isoformat())
        assert worker_is_online() is False

    def test_garbage_heartbeat_is_offline(self) -> None:
        Setting.objects.create(key=WORKER_HEARTBEAT_KEY, value="not a date")
        assert worker_is_online() is False
