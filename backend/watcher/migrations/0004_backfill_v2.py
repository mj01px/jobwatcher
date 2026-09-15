"""v2 data: backfill job keys, company names and scores; seed Gupy, GitHub and manual sources.

Seed lists are frozen here on purpose (measured by Vaggio in 09/2026): later
edits to the collectors must never change what this migration inserted. The
scores use the scoring engine as it is when the migration runs; later profile
changes rescore through the API or ``manage.py rescore``.
"""

from __future__ import annotations

from typing import Any

from django.db import migrations
from django.utils import timezone

GUPY_SEARCHES = [
    "desenvolvedor",
    "programador",
    "developer",
    "analista de sistemas",
    "analista de desenvolvimento",
    "engenheiro de software",
    "desenvolvimento de software",
    "software",
    "sistemas",
    "backend",
    "back-end",
    "frontend",
    "front-end",
    "fullstack",
    "full stack",
    "python",
    "java",
    "javascript",
    "typescript",
    "node",
    "react",
    "sql",
    "banco de dados",
    "dados",
    "analista de dados",
    "engenheiro de dados",
    "cientista de dados",
    "inteligencia artificial",
    "cloud",
    "devops",
    "seguranca da informacao",
    "analista de suporte",
    "qa",
    "analista de testes",
    "estagio desenvolvimento",
    "estagio tecnologia",
    "estagio ti",
    "estagio dados",
]

GITHUB_REPOS = [
    "backend-br/vagas",
    "soujava/vagas-java",
    "frontendbr/vagas",
    "react-brasil/vagas",
]

DEFAULT_MIN_SCORE = 20
BATCH_SIZE = 500


def _scoring(setting_model: Any) -> tuple[dict[str, Any] | None, int]:
    profile_row = setting_model.objects.filter(key="scoring_profile").first()
    profile = profile_row.value if profile_row and isinstance(profile_row.value, dict) else None
    min_row = setting_model.objects.filter(key="highlight_min_score").first()
    min_score = min_row.value if min_row and isinstance(min_row.value, int) else DEFAULT_MIN_SCORE
    return profile or None, min_score


def forwards(apps: Any, schema_editor: Any) -> None:
    from watcher.scoring import classify

    Source = apps.get_model("watcher", "Source")
    Job = apps.get_model("watcher", "Job")
    Setting = apps.get_model("watcher", "Setting")
    now = timezone.now()
    profile, min_score = _scoring(Setting)

    names = dict(Source.objects.values_list("id", "name"))
    kinds = dict(Source.objects.values_list("id", "kind"))
    used_keys: set[str] = set()
    batch: list[Any] = []
    fields = [
        "key",
        "company_name",
        "score",
        "score_tags",
        "seniority",
        "work_mode",
        "is_highlighted",
    ]
    for job in Job.objects.order_by("id").iterator(chunk_size=BATCH_SIZE):
        base = f"{kinds.get(job.source_id, 'inhire')}:{job.external_id}"
        # Two career pages of the same InHire tenant may list the same job id.
        key = base if base not in used_keys else f"{base}:{job.pk}"
        used_keys.add(key)
        job.key = key
        job.company_name = job.company_name or names.get(job.source_id, "")
        result = classify(job.title, job.description, job.company_name, job.location, profile)
        job.score = result.score
        job.score_tags = result.tags
        job.seniority = result.seniority
        job.work_mode = result.work_mode
        job.is_highlighted = result.score >= min_score
        batch.append(job)
        if len(batch) >= BATCH_SIZE:
            Job.objects.bulk_update(batch, fields)
            batch = []
    if batch:
        Job.objects.bulk_update(batch, fields)

    existing = set(Source.objects.values_list("kind", "target"))
    seeds = [("gupy", term, term) for term in GUPY_SEARCHES]
    seeds += [("github", repo, repo) for repo in GITHUB_REPOS]
    Source.objects.bulk_create(
        Source(kind=kind, name=name, target=target, created_at=now, updated_at=now)
        for kind, name, target in seeds
        if (kind, target) not in existing
    )
    if ("manual", "manual") not in existing:
        Source.objects.create(
            kind="manual",
            name="Manual",
            target="manual",
            is_active=False,
            is_hidden=True,
            created_at=now,
            updated_at=now,
        )


class Migration(migrations.Migration):
    dependencies = [("watcher", "0003_sources_v2")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
