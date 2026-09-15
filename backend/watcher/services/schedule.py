"""Daily schedule math: next slot, most recent slot and catch up detection."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings

from watcher.constants import SCHEDULE_HOURS
from watcher.models import CheckRun


def schedule_zone() -> ZoneInfo:
    return ZoneInfo(settings.JOB_WATCHER_TIMEZONE)


def most_recent_scheduled_time(now: datetime) -> datetime:
    candidates = [
        now.replace(hour=hour, minute=0, second=0, microsecond=0) for hour in SCHEDULE_HOURS
    ]
    past = [candidate for candidate in candidates if candidate <= now]
    if past:
        return max(past)
    yesterday = now - timedelta(days=1)
    return yesterday.replace(hour=max(SCHEDULE_HOURS), minute=0, second=0, microsecond=0)


def next_scheduled_run(now: datetime | None = None) -> datetime:
    """Next 09/12/15/18 slot strictly after ``now`` in the schedule timezone."""
    zone = schedule_zone()
    local_now = (now or datetime.now(zone)).astimezone(zone)
    candidates = [
        local_now.replace(hour=hour, minute=0, second=0, microsecond=0) for hour in SCHEDULE_HOURS
    ]
    future = [candidate for candidate in candidates if candidate > local_now]
    if future:
        return min(future)
    tomorrow = local_now + timedelta(days=1)
    return tomorrow.replace(hour=min(SCHEDULE_HOURS), minute=0, second=0, microsecond=0)


def catch_up_is_needed(now: datetime | None = None) -> bool:
    """True when the last completed run finished before the latest missed slot."""
    zone = schedule_zone()
    local_now = (now or datetime.now(zone)).astimezone(zone)
    last = (
        CheckRun.objects.filter(
            status__in=(CheckRun.Status.SUCCESS, CheckRun.Status.PARTIAL),
            finished_at__isnull=False,
        )
        .order_by("-finished_at")
        .values_list("finished_at", flat=True)
        .first()
    )
    if last is None:
        return True
    return last.astimezone(zone) < most_recent_scheduled_time(local_now)
