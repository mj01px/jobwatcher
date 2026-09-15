"""Calendar dates in the monitor timezone (dates of the funnel are local, not UTC)."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone


def local_today() -> date:
    return timezone.now().astimezone(ZoneInfo(settings.JOB_WATCHER_TIMEZONE)).date()
