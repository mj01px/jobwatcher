"""Scoring engine (ported from Vaggio): pure functions, no database and no HTTP."""

from __future__ import annotations

import pytest

from tests.conftest import MakeJob
from watcher.models import Job, Setting, Source
from watcher.scoring import classify, contains, normalize
from watcher.scoring.engine import detect_seniority, detect_work_mode, score_text, years_penalty
from watcher.services.scoring import rescore_all


class TestNormalize:
    def test_strips_accents_and_case(self) -> None:
        assert normalize("Estágio em Análise") == "estagio em analise"

    def test_collapses_whitespace(self) -> None:
        assert normalize("java    junior\n\nremoto") == "java junior remoto"

    def test_empty(self) -> None:
        assert normalize("") == ""


class TestContains:
    def test_matches_whole_word(self) -> None:
        assert contains("python jr remoto", "jr")

    def test_does_not_match_inside_another_word(self) -> None:
        # The trap that justifies word boundaries: "sr" must not match "srv".
        assert not contains("servidor srv linux", "sr")
        assert not contains("vaga jrxyz", "jr")

    def test_matches_compound_term(self) -> None:
        assert contains("vaga com home office", "home office")


class TestScoreText:
    def test_title_counts_double(self) -> None:
        in_title, _ = score_text("python", "")
        in_body, _ = score_text("", "python")
        assert in_title == in_body * 2

    def test_one_hit_per_group(self) -> None:
        # python, django and sql are all "core": three title hits still count once.
        one, _ = score_text("python", "")
        three, _ = score_text("python django sql", "")
        assert one == three

    def test_tags_only_for_positive_weights(self) -> None:
        _, tags = score_text("desenvolvedor php senior", "")
        assert tags == []

    def test_penalty_pulls_the_score_down(self) -> None:
        positive, _ = score_text("python junior", "")
        with_php, _ = score_text("python junior php", "")
        assert with_php < positive

    def test_custom_profile(self) -> None:
        profile = {"stack": {"weight": 7, "terms": ["elixir"]}}
        assert score_text("elixir dev", "", profile) == (14, ["elixir"])


class TestYearsPenalty:
    def test_no_requirement(self) -> None:
        assert years_penalty("vaga para iniciante") == 0

    def test_two_years_is_not_penalized(self) -> None:
        assert years_penalty("2 anos de experiencia") == 0

    def test_three_years(self) -> None:
        assert years_penalty("3 anos de experiencia") == -12

    def test_five_years_or_more(self) -> None:
        assert years_penalty("7 anos de atuacao") == -25

    def test_accents_do_not_escape_the_penalty(self) -> None:
        assert years_penalty("5 anos de vivência na área") == -25
        assert years_penalty("3 anos de experiência") == -12


class TestDetectors:
    def test_internship_before_junior(self) -> None:
        assert detect_seniority("estagio em desenvolvimento junior") == "internship"

    def test_senior_before_mid(self) -> None:
        assert detect_seniority("desenvolvedor senior pl") == "senior"

    def test_no_signal(self) -> None:
        assert detect_seniority("desenvolvedor de software") == "unknown"

    def test_work_mode(self) -> None:
        assert detect_work_mode("vaga remoto") == "remote"
        assert detect_work_mode("modelo hibrido") == "hybrid"
        assert detect_work_mode("trabalho presencial") == "onsite"
        assert detect_work_mode("sem informacao") == "unknown"


class TestClassify:
    def test_target_job_scores_high(self) -> None:
        result = classify(
            "Desenvolvedor Python Junior - Fintech",
            "Vaga remota com Django e PostgreSQL.",
        )
        assert result.score == 64
        assert result.tags == ["python", "fintech", "junior"]
        assert result.seniority == "junior"

    def test_off_profile_job_goes_negative(self) -> None:
        result = classify("Analista PHP Senior", "Laravel, 5 anos de experiencia em atuacao")
        assert result.score == -115
        assert result.seniority == "senior"


@pytest.mark.django_db
class TestRescore:
    def test_rescores_with_the_saved_profile(self, source: Source, make_job: MakeJob) -> None:
        job = make_job(source, title="Desenvolvedor Python Junior", score=0)
        total, changed = rescore_all()
        job.refresh_from_db()
        assert total >= 1
        assert changed >= 1
        assert job.score == 44
        assert "python" in job.score_tags
        assert job.is_highlighted is True

        Setting.objects.create(key="scoring_profile", value={"x": {"weight": 1, "terms": ["zzz"]}})
        rescore_all()
        job.refresh_from_db()
        assert (job.score, job.is_highlighted) == (0, False)

    def test_rescore_command(
        self, source: Source, make_job: MakeJob, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from django.core.management import call_command

        make_job(source, title="Desenvolvedor Python Junior")
        call_command("rescore")
        assert "Rescored" in capsys.readouterr().out
        assert Job.objects.filter(score=44).exists()
