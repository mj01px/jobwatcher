"""v3 data: v1 "applied" archives become applications in the funnel."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import migrations


def forwards(apps: Any, schema_editor: Any) -> None:
    from pipeline.services import convert_applied_archives

    convert_applied_archives(
        job_model=apps.get_model("watcher", "Job"),
        application_model=apps.get_model("pipeline", "Application"),
        interaction_model=apps.get_model("pipeline", "Interaction"),
        timezone_name=settings.JOB_WATCHER_TIMEZONE,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0001_initial"),
        ("watcher", "0007_v3_highlight_gate"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
