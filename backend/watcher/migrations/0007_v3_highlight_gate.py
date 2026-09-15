"""v3 data: rescore every job with the stack gate and raise the default minimum score.

The minimum moves from 20 to 25 only when the saved value is still the old
default; a value the user picked stays. Scores use the engine as it is when the
migration runs, like 0004.
"""

from __future__ import annotations

from typing import Any

from django.db import migrations

OLD_DEFAULT_MIN_SCORE = 20
NEW_DEFAULT_MIN_SCORE = 25
DEFAULT_STACK_GROUPS = ["core", "adjacent"]
BATCH_SIZE = 500
FIELDS = ["score", "score_tags", "score_groups", "seniority", "work_mode", "is_highlighted"]


def forwards(apps: Any, schema_editor: Any) -> None:
    from django.utils import timezone

    from watcher.scoring import classify

    Job = apps.get_model("watcher", "Job")
    Setting = apps.get_model("watcher", "Setting")
    now = timezone.now()

    min_row = Setting.objects.filter(key="highlight_min_score").first()
    if min_row is None or min_row.value == OLD_DEFAULT_MIN_SCORE:
        Setting.objects.update_or_create(
            key="highlight_min_score",
            defaults={"value": NEW_DEFAULT_MIN_SCORE, "updated_at": now},
        )
        min_score = NEW_DEFAULT_MIN_SCORE
    else:
        min_score = min_row.value if isinstance(min_row.value, int) else NEW_DEFAULT_MIN_SCORE

    profile_row = Setting.objects.filter(key="scoring_profile").first()
    profile = profile_row.value if profile_row and isinstance(profile_row.value, dict) else None
    stack_row = Setting.objects.filter(key="highlight_stack_groups").first()
    stack = stack_row.value if stack_row and isinstance(stack_row.value, list) else None
    stack_groups = set(DEFAULT_STACK_GROUPS if stack is None else stack)

    batch: list[Any] = []
    for job in Job.objects.order_by("id").iterator(chunk_size=BATCH_SIZE):
        result = classify(
            job.title, job.description, job.company_name, job.location, profile or None
        )
        job.score = result.score
        job.score_tags = result.tags
        job.score_groups = result.groups
        job.seniority = result.seniority
        job.work_mode = result.work_mode
        job.is_highlighted = result.score >= min_score and (
            not stack_groups or not stack_groups.isdisjoint(result.groups)
        )
        batch.append(job)
        if len(batch) >= BATCH_SIZE:
            Job.objects.bulk_update(batch, FIELDS)
            batch = []
    if batch:
        Job.objects.bulk_update(batch, FIELDS)


class Migration(migrations.Migration):
    dependencies = [
        ("watcher", "0006_v3_schema"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
