"""Rescore every job with the saved scoring profile: ``manage.py rescore``."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from watcher.services.scoring import rescore_all


class Command(BaseCommand):
    help = "Reapply the scoring profile to every stored job."

    def handle(self, *args: Any, **options: Any) -> None:
        total, changed = rescore_all()
        self.stdout.write(f"Rescored {total} jobs, {changed} changed.")
