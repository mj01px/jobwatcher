from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from rest_framework.test import APIClient

from tests.conftest import MakeJob, data_of, error_of
from watcher.models import Job, Setting, Source
from watcher.scoring import PROFILE
from watcher.services import github, gupy
from watcher.services.secrets import get_secret, set_secrets

seed_migration = importlib.import_module("watcher.migrations.0002_seed_defaults")
v2_migration = importlib.import_module("watcher.migrations.0004_backfill_v2")


class TestSeedData:
    def test_seed_lists(self) -> None:
        assert len(seed_migration.SEED_COMPANIES) == 74
        assert len(seed_migration.DEFAULT_KEYWORDS) == 28
        assert v2_migration.GUPY_SEARCHES == gupy.DEFAULT_SEARCHES
        assert v2_migration.GITHUB_REPOS == github.REPOS
        assert len(gupy.DEFAULT_SEARCHES) == 38

    @pytest.mark.django_db
    def test_migrations_seed_every_source_kind(self) -> None:
        assert Source.objects.filter(kind="inhire").count() == 74
        assert Source.objects.filter(kind="gupy").count() == 38
        assert Source.objects.filter(kind="github").count() == 4
        manual = Source.objects.get(kind="manual")
        assert (manual.is_hidden, manual.is_active) == (True, False)
        assert Source.objects.filter(target="https://cielo.inhire.app/tecnologia/vagas").exists()

    @pytest.mark.django_db
    def test_v2_seed_is_idempotent(self) -> None:
        from django.apps import apps

        v2_migration.forwards(apps, None)
        assert Source.objects.filter(kind="gupy").count() == 38
        assert Source.objects.filter(kind="manual").count() == 1


@pytest.mark.django_db
class TestV2Backfill:
    def test_backfill_keys_company_names_and_scores(
        self, source: Source, make_job: MakeJob
    ) -> None:
        from django.apps import apps

        job = make_job(
            source,
            external_id="abc",
            key="placeholder",
            company_name="",
            title="Desenvolvedor Python Junior",
        )
        twin_source = Source.objects.create(name="Twin", target="https://acme.inhire.app/x/vagas")
        twin = make_job(twin_source, external_id="abc", key="placeholder-2", company_name="")
        v2_migration.forwards(apps, None)

        job.refresh_from_db()
        twin.refresh_from_db()
        assert job.key == "inhire:abc"
        assert twin.key == f"inhire:abc:{twin.pk}"
        assert job.company_name == "Acme"
        assert job.score > 0
        assert job.is_highlighted is True


@pytest.mark.django_db
class TestScoringSettings:
    def test_get_returns_the_default_profile(self, api_client: APIClient) -> None:
        data = data_of(api_client.get("/api/v1/settings/scoring"))
        assert data["groups"] == PROFILE
        assert data["minScore"] == 25
        assert data["stackGroups"] == ["core", "adjacent"]
        assert data["isDefault"] is True

    def test_put_saves_rescores_and_recomputes_highlight(
        self, api_client: APIClient, source: Source, make_job: MakeJob
    ) -> None:
        job = make_job(source, title="Desenvolvedor Elixir", score=0, is_highlighted=False)
        response = api_client.put(
            "/api/v1/settings/scoring",
            {
                "groups": {"stack": {"weight": 15, "terms": [" elixir ", "", "phoenix"]}},
                "minScore": 25,
            },
            format="json",
        )
        assert response.status_code == 200
        data = data_of(response)
        assert data == {
            "groups": {"stack": {"weight": 15, "terms": ["elixir", "phoenix"]}},
            "minScore": 25,
            # The saved stack groups do not exist in the new profile: no gate.
            "stackGroups": [],
            "isDefault": False,
        }
        job.refresh_from_db()
        assert job.score == 30
        assert job.score_tags == ["elixir"]
        assert job.is_highlighted is True

    def test_null_groups_resets_to_default(self, api_client: APIClient) -> None:
        Setting.objects.create(key="scoring_profile", value={"x": {"weight": 1, "terms": ["a"]}})
        data = data_of(
            api_client.put(
                "/api/v1/settings/scoring", {"groups": None, "minScore": 10}, format="json"
            )
        )
        assert data["isDefault"] is True
        assert data["groups"] == PROFILE
        assert data["minScore"] == 10

    def test_omitted_groups_keep_the_saved_profile(self, api_client: APIClient) -> None:
        custom = {"x": {"weight": 1, "terms": ["a"]}}
        Setting.objects.create(key="scoring_profile", value=custom)
        data = data_of(api_client.put("/api/v1/settings/scoring", {"minScore": 5}, format="json"))
        assert data["groups"] == custom
        assert data["minScore"] == 5

    @pytest.mark.parametrize(
        ("body", "field"),
        [
            ({"groups": {"Bad Key": {"weight": 1, "terms": []}}, "minScore": 1}, "groups.Bad Key"),
            ({"groups": {"ok": {"weight": 101, "terms": []}}, "minScore": 1}, "groups.ok.weight"),
            ({"groups": {"ok": {"weight": True, "terms": []}}, "minScore": 1}, "groups.ok.weight"),
            (
                {"groups": {"ok": {"weight": 1, "terms": "python"}}, "minScore": 1},
                "groups.ok.terms",
            ),
            (
                {"groups": {"ok": {"weight": 1, "terms": ["x" * 81]}}, "minScore": 1},
                "groups.ok.terms",
            ),
            (
                {"groups": {"ok": {"weight": 1, "terms": ["a"] * 301}}, "minScore": 1},
                "groups.ok.terms",
            ),
            ({"groups": [], "minScore": 1}, "groups"),
            ({"groups": None, "minScore": "high"}, "minScore"),
        ],
    )
    def test_invalid_scoring(self, api_client: APIClient, body: dict[str, Any], field: str) -> None:
        response = api_client.put("/api/v1/settings/scoring", body, format="json")
        assert response.status_code == 400
        assert field in {detail["field"] for detail in error_of(response)["details"]}


@pytest.mark.django_db
class TestProfileSettings:
    def test_defaults(self, api_client: APIClient) -> None:
        assert data_of(api_client.get("/api/v1/settings/profile")) == {
            "dossier": "",
            "pitchMaxChars": 1200,
            "geminiModel": "gemini-3.7-flash",
            "geminiConfigured": False,
            "githubConfigured": False,
        }

    def test_put_updates_given_fields(self, api_client: APIClient) -> None:
        data = data_of(
            api_client.put(
                "/api/v1/settings/profile",
                {"dossier": "About me", "pitchMaxChars": 900, "geminiModel": " gemini-x "},
                format="json",
            )
        )
        assert data["dossier"] == "About me"
        assert data["pitchMaxChars"] == 900
        assert data["geminiModel"] == "gemini-x"
        data = data_of(
            api_client.put("/api/v1/settings/profile", {"pitchMaxChars": 300}, format="json")
        )
        assert data["dossier"] == "About me"

    @pytest.mark.parametrize(
        "body",
        [
            {"pitchMaxChars": 299},
            {"pitchMaxChars": 5001},
            {"pitchMaxChars": "1000"},
            {"dossier": 1},
        ],
    )
    def test_invalid_profile(self, api_client: APIClient, body: dict[str, Any]) -> None:
        assert api_client.put("/api/v1/settings/profile", body, format="json").status_code == 400


@pytest.mark.django_db
class TestSecrets:
    def test_secrets_are_written_to_the_file_and_never_returned(
        self, api_client: APIClient, isolated_secrets: Path
    ) -> None:
        response = api_client.put(
            "/api/v1/settings/secrets",
            {"geminiApiKey": " gem-123 ", "githubToken": "ghp_abc"},
            format="json",
        )
        assert data_of(response) == {"geminiConfigured": True, "githubConfigured": True}
        assert "gem-123" not in response.content.decode()
        assert json.loads(isolated_secrets.read_text(encoding="utf-8")) == {
            "gemini_api_key": "gem-123",
            "github_token": "ghp_abc",
        }
        profile = data_of(api_client.get("/api/v1/settings/profile"))
        assert profile["geminiConfigured"] is True
        assert "gem-123" not in json.dumps(profile)
        stored = json.dumps(list(Setting.objects.values_list("value", flat=True)))
        assert "gem-123" not in stored

    def test_empty_string_removes_only_that_secret(self, api_client: APIClient) -> None:
        set_secrets({"gemini_api_key": "a", "github_token": "b"})
        data = data_of(
            api_client.put("/api/v1/settings/secrets", {"githubToken": ""}, format="json")
        )
        assert data == {"geminiConfigured": True, "githubConfigured": False}

    def test_env_var_wins_over_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        set_secrets({"github_token": "from-file"})
        assert get_secret("github_token") == "from-file"
        monkeypatch.setenv("GITHUB_TOKEN", "from-env")
        assert get_secret("github_token") == "from-env"

    def test_invalid_secret_value(self, api_client: APIClient) -> None:
        response = api_client.put("/api/v1/settings/secrets", {"geminiApiKey": 42}, format="json")
        assert response.status_code == 400

    def test_keywords_route_is_gone(self, api_client: APIClient) -> None:
        assert api_client.get("/api/v1/settings/keywords").status_code == 404


def test_job_model_has_no_company_field() -> None:
    assert not hasattr(Job, "company")
