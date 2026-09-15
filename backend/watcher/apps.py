from __future__ import annotations

from django.apps import AppConfig


class WatcherConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "watcher"
    verbose_name = "Job Watcher"
