"""System timeline titles switch from English to Brazilian Portuguese."""

from __future__ import annotations

from typing import Any

from django.db import migrations


def forwards(apps: Any, schema_editor: Any) -> None:
    from pipeline.services import translate_legacy_titles

    translate_legacy_titles(interaction_model=apps.get_model("pipeline", "Interaction"))


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0002_convert_applied_archives"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
