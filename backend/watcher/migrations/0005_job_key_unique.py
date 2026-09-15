from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("watcher", "0004_backfill_v2")]

    operations = [
        migrations.AlterField(
            model_name="job",
            name="key",
            field=models.CharField(max_length=1100, unique=True),
        ),
    ]
