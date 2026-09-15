"""Sync applications, jobs and settings with the shared cloud file: ``manage.py sync``."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from watcher.services import sync as sync_service


class Command(BaseCommand):
    help = "Pull changes from the shared sync file and push the merged state back."

    def handle(self, *args: Any, **options: Any) -> None:
        path = sync_service.sync_file()
        if path is None:
            self.stdout.write(
                "Sync is disabled: no folder found. Set JOB_WATCHER_SYNC_DIR to a "
                "cloud-synced directory (e.g. your Google Drive)."
            )
            return
        self.stdout.write(f"Sync file: {path}")
        counts = sync_service.sync()
        if counts is None:
            return
        for name, value in counts.as_dict().items():
            self.stdout.write(f"{name}: {value}")
        self.stdout.write(self.style.SUCCESS("Done."))
