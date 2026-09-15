"""v2 schema: companies become sources, jobs gain Vaggio fields.

Renames keep every existing row (companies, jobs, check runs). The job ``key``
is added nullable here, backfilled in 0004 and made unique in 0005.
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models

SOURCE_KINDS = [
    ("inhire", "Inhire"),
    ("gupy", "Gupy"),
    ("github", "Github"),
    ("manual", "Manual"),
]


class Migration(migrations.Migration):
    dependencies = [("watcher", "0002_seed_defaults")]

    operations = [
        # Indexes and constraints that reference renamed fields go first.
        migrations.RemoveIndex(model_name="company", name="idx_companies_active"),
        migrations.RemoveConstraint(model_name="job", name="uniq_jobs_company_external_id"),
        migrations.RemoveIndex(model_name="job", name="idx_jobs_company_status"),
        migrations.RemoveConstraint(model_name="checkruncompany", name="uniq_run_company"),
        migrations.RemoveIndex(model_name="checkruncompany", name="idx_run_companies_position"),
        # Company -> Source.
        migrations.RenameModel(old_name="Company", new_name="Source"),
        migrations.AlterModelTable(name="source", table="sources"),
        migrations.RenameField(model_name="source", old_name="url", new_name="target"),
        migrations.AlterField(
            model_name="source", name="target", field=models.CharField(max_length=500)
        ),
        migrations.AddField(
            model_name="source",
            name="kind",
            field=models.CharField(choices=SOURCE_KINDS, default="inhire", max_length=16),
        ),
        migrations.AddField(
            model_name="source", name="is_hidden", field=models.BooleanField(default=False)
        ),
        migrations.AddConstraint(
            model_name="source",
            constraint=models.UniqueConstraint(
                fields=("kind", "target"), name="uniq_sources_kind_target"
            ),
        ),
        migrations.AddIndex(
            model_name="source",
            index=models.Index(fields=["is_active", "is_removed"], name="idx_sources_active"),
        ),
        # Job.
        migrations.RenameField(model_name="job", old_name="company", new_name="source"),
        migrations.AlterField(
            model_name="job",
            name="source",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="jobs",
                to="watcher.source",
            ),
        ),
        migrations.AlterField(
            model_name="job", name="external_id", field=models.CharField(max_length=1000)
        ),
        migrations.AddField(
            model_name="job",
            name="key",
            field=models.CharField(max_length=1100, null=True),
        ),
        migrations.AddField(
            model_name="job",
            name="company_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="job",
            name="location",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="job",
            name="work_mode",
            field=models.CharField(
                choices=[
                    ("remote", "Remote"),
                    ("hybrid", "Hybrid"),
                    ("onsite", "Onsite"),
                    ("unknown", "Unknown"),
                ],
                default="unknown",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="job",
            name="seniority",
            field=models.CharField(
                choices=[
                    ("internship", "Internship"),
                    ("junior", "Junior"),
                    ("mid", "Mid"),
                    ("senior", "Senior"),
                    ("unknown", "Unknown"),
                ],
                default="unknown",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="job",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="job",
            name="published_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(model_name="job", name="score", field=models.IntegerField(default=0)),
        migrations.AddField(
            model_name="job",
            name="score_tags",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddIndex(
            model_name="job",
            index=models.Index(fields=["source", "status"], name="idx_jobs_source_status"),
        ),
        migrations.AddIndex(
            model_name="job",
            index=models.Index(fields=["status", "-score"], name="idx_jobs_status_score"),
        ),
        migrations.AddIndex(
            model_name="job",
            index=models.Index(fields=["status", "published_at"], name="idx_jobs_status_published"),
        ),
        # Check runs.
        migrations.RenameField(
            model_name="checkrun", old_name="companies_total", new_name="sources_total"
        ),
        migrations.RenameField(
            model_name="checkrun", old_name="companies_checked", new_name="sources_checked"
        ),
        migrations.RenameModel(old_name="CheckRunCompany", new_name="CheckRunSource"),
        migrations.AlterModelTable(name="checkrunsource", table="check_run_sources"),
        migrations.RenameField(model_name="checkrunsource", old_name="company", new_name="source"),
        migrations.AlterField(
            model_name="checkrunsource",
            name="source",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="run_states",
                to="watcher.source",
            ),
        ),
        migrations.AlterField(
            model_name="checkrunsource",
            name="run",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="source_states",
                to="watcher.checkrun",
            ),
        ),
        migrations.AddField(
            model_name="checkrunsource",
            name="kind",
            field=models.CharField(default="inhire", max_length=16),
        ),
        migrations.AddConstraint(
            model_name="checkrunsource",
            constraint=models.UniqueConstraint(fields=("run", "source"), name="uniq_run_source"),
        ),
        migrations.AddIndex(
            model_name="checkrunsource",
            index=models.Index(fields=["run", "position"], name="idx_run_sources_position"),
        ),
    ]
