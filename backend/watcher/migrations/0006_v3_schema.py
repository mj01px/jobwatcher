"""v3 schema: ``is_new`` becomes ``arrived_new`` and jobs remember their scoring groups."""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("watcher", "0005_job_key_unique"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="job", name="idx_jobs_listing_order"),
        migrations.RenameField(model_name="job", old_name="is_new", new_name="arrived_new"),
        migrations.AddField(
            model_name="job",
            name="score_groups",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddIndex(
            model_name="job",
            index=models.Index(fields=["status", "-first_seen_at"], name="idx_jobs_listing_order"),
        ),
    ]
