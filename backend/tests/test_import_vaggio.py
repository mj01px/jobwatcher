"""Vaggio import against a small SQLite fixture shaped like the real Vaggio schema."""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from pipeline.models import Application, Interaction, Pitch
from watcher.models import Job, Setting, Source
from watcher.services.vaggio_import import VaggioImportError, import_vaggio

SCHEMA = """
CREATE TABLE jobs_job (
    id INTEGER PRIMARY KEY, created_at datetime, updated_at datetime, title varchar(300),
    company varchar(200), location varchar(200), work_mode varchar(20), seniority varchar(20),
    description TEXT, url varchar(1000), source varchar(20), source_id varchar(200),
    key varchar(64), score INTEGER, tags TEXT, discarded bool, published_at datetime
);
CREATE TABLE pipeline_application (
    id INTEGER PRIMARY KEY, created_at datetime, updated_at datetime, status varchar(20),
    priority smallint, applied_on date, next_step varchar(300), next_step_on date,
    contact varchar(200), has_referral bool, notes TEXT, job_id bigint
);
CREATE TABLE pipeline_interaction (
    id INTEGER PRIMARY KEY, created_at datetime, updated_at datetime, date date,
    title varchar(200), detail TEXT, application_id bigint
);
CREATE TABLE jobs_pitch (
    id INTEGER PRIMARY KEY, created_at datetime, updated_at datetime, texto TEXT,
    modelo varchar(80), instrucao varchar(300), max_chars integer, tokens_entrada integer,
    tokens_saida integer, tokens_pensamento integer, job_id bigint, autor_id INTEGER
);
CREATE TABLE accounts_perfil (
    id INTEGER PRIMARY KEY, created_at datetime, updated_at datetime, nome varchar(120),
    dossie TEXT, termos TEXT, pitch_max_chars integer
);
"""


def _stamp(days_ago: float) -> str:
    return (timezone.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S.%f")


@pytest.fixture
def vaggio_db(tmp_path: Path) -> Path:
    path = tmp_path / "vaggio.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    jobs = [
        # id, title, company, source, source_id, url, discarded, published days ago
        (
            1,
            "Desenvolvedor Python Junior",
            "Acme",
            "gupy",
            "101",
            "https://acme.gupy.io/job/101",
            0,
            2,
        ),
        (2, "Vaga PHP Senior", "Beta", "gupy", "102", "https://beta.gupy.io/job/102", 1, 3),
        (
            3,
            "[CLT] Dev Django",
            "",
            "github",
            "backend-br/vagas#9",
            "https://github.com/backend-br/vagas/issues/9",
            0,
            60,
        ),
        (4, "Analista de Dados", "Gamma", "manual", "", "https://gamma.test/job", 0, None),
        (5, "Old Gupy In Funnel", "Delta", "gupy", "105", "https://delta.gupy.io/job/105", 0, 90),
        (6, "Unknown Source", "X", "linkedin", "1", "https://linkedin.test/1", 0, 1),
    ]
    for job_id, title, company, source, source_id, url, discarded, published in jobs:
        connection.execute(
            "INSERT INTO jobs_job VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job_id,
                _stamp(10),
                _stamp(5),
                title,
                company,
                "Recife",
                "remote",
                "junior",
                "Descricao",
                url,
                source,
                source_id,
                f"hash-{job_id}",
                99,
                json.dumps(["python"]),
                discarded,
                None if published is None else _stamp(published),
            ),
        )
    connection.execute(
        "INSERT INTO pipeline_application VALUES (1, ?, ?, 'interview', 2, '2026-09-02', 'Call', "
        "'2026-09-20', 'Ana', 1, 'Notes', 1)",
        (_stamp(9), _stamp(1)),
    )
    connection.execute(
        "INSERT INTO pipeline_application VALUES "
        "(2, ?, ?, 'applied', 3, NULL, '', NULL, '', 0, '', 5)",
        (_stamp(9), _stamp(1)),
    )
    connection.execute(
        "INSERT INTO pipeline_interaction VALUES (1, ?, ?, '2026-09-02', 'Entrou no funil', '', 1)",
        (_stamp(9), _stamp(9)),
    )
    connection.execute(
        "INSERT INTO pipeline_interaction VALUES (2, ?, ?, '2026-09-05', 'Entrevista', 'RH', 1)",
        (_stamp(8), _stamp(8)),
    )
    connection.execute(
        "INSERT INTO jobs_pitch VALUES "
        "(1, ?, ?, 'Primeira versao', 'gemini-a', '', 1200, 1, 2, 3, 1, 1)",
        (_stamp(7), _stamp(7)),
    )
    connection.execute(
        "INSERT INTO jobs_pitch VALUES "
        "(2, ?, ?, 'Versao final', 'gemini-b', 'curto', 900, 4, 5, 6, 1, 1)",
        (_stamp(6), _stamp(6)),
    )
    connection.execute(
        "INSERT INTO accounts_perfil VALUES (1, ?, ?, 'Me', 'Meu dossie', ?, 1500)",
        (_stamp(10), _stamp(10), json.dumps({"core": {"weight": 12, "terms": ["python"]}})),
    )
    connection.commit()
    connection.close()
    return path


@pytest.mark.django_db
class TestImportVaggio:
    def test_imports_everything(self, vaggio_db: Path) -> None:
        counts = import_vaggio(vaggio_db)

        assert counts.jobs_created == 5
        assert counts.jobs_skipped == 1
        assert counts.jobs_archived == 1
        assert counts.applications_created == 2
        assert counts.interactions_created == 2
        assert counts.pitches_imported == 1
        assert counts.profile_imported is True
        assert counts.expired == 1

        gupy_job = Job.objects.get(key="gupy:101")
        assert gupy_job.source.is_hidden and gupy_job.source.kind == "gupy"
        assert gupy_job.source.name == "Gupy (imported from Vaggio)"
        assert gupy_job.company_name == "Acme"
        assert gupy_job.arrived_new is False
        # Rescored with the imported profile (core python only), not Vaggio's stored 99.
        assert gupy_job.score == 24
        assert gupy_job.first_seen_at < gupy_job.last_seen_at

        discarded = Job.objects.get(key="gupy:102")
        assert (discarded.status, discarded.archive_source, discarded.archive_reason) == (
            "archived",
            "manual",
            "not_interested",
        )
        assert discarded.archive_note == "Imported from Vaggio"

        github_job = Job.objects.get(key="github:https://github.com/backend-br/vagas/issues/9")
        assert github_job.external_id == "backend-br/vagas#9"
        assert (github_job.status, github_job.archive_reason) == ("archived", "expired")

        manual_job = Job.objects.get(source__kind="manual")
        assert manual_job.key.startswith("manual:")

        in_funnel = Job.objects.get(key="gupy:105")
        assert in_funnel.status == "active"

        application = Application.objects.get(job=gupy_job)
        assert (application.status, application.priority, application.contact) == (
            "interview",
            2,
            "Ana",
        )
        assert application.next_step_on is not None and application.has_referral is True
        assert list(application.interactions.order_by("date").values_list("title", flat=True)) == [
            "Entrou no funil",
            "Entrevista",
        ]
        pitch = Pitch.objects.get(job=gupy_job)
        assert (pitch.text, pitch.model, pitch.max_chars, pitch.thinking_tokens) == (
            "Versao final",
            "gemini-b",
            900,
            6,
        )
        assert Setting.objects.get(key="dossier").value == "Meu dossie"
        assert Setting.objects.get(key="pitch_max_chars").value == 1500
        assert Setting.objects.get(key="scoring_profile").value == {
            "core": {"weight": 12, "terms": ["python"]}
        }

    def test_is_idempotent(self, vaggio_db: Path) -> None:
        import_vaggio(vaggio_db)
        counts = import_vaggio(vaggio_db)
        assert counts.jobs_created == 0
        assert counts.jobs_updated == 5
        assert counts.applications_created == 0
        assert counts.interactions_created == 0
        assert counts.pitches_imported == 0
        assert Job.objects.filter(source__is_hidden=True).count() == 5
        assert Interaction.objects.count() == 2
        assert Pitch.objects.count() == 1
        assert Source.objects.filter(target="imported:vaggio").count() == 2

    def test_existing_key_is_kept_and_only_empty_fields_filled(self, vaggio_db: Path) -> None:
        term = Source.objects.create(kind="gupy", name="python", target="python-import")
        existing = Job.objects.create(
            source=term,
            key="gupy:101",
            external_id="101",
            title="Collected title",
            url="https://acme.gupy.io/job/101",
            company_name="",
            location="Olinda",
        )
        import_vaggio(vaggio_db)
        existing.refresh_from_db()
        assert existing.source_id == term.pk
        assert existing.title == "Collected title"
        assert existing.company_name == "Acme"
        assert existing.location == "Olinda"
        assert Application.objects.filter(job=existing).exists()

    def test_command_prints_counts_and_rejects_bad_files(
        self, vaggio_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        call_command("import_vaggio", str(vaggio_db))
        out = capsys.readouterr().out
        assert "jobs_created: 5" in out
        with pytest.raises(CommandError, match="not found"):
            call_command("import_vaggio", str(tmp_path / "missing.sqlite3"))
        empty = tmp_path / "empty.sqlite3"
        sqlite3.connect(empty).close()
        with pytest.raises(VaggioImportError):
            import_vaggio(empty)
