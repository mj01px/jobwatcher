"""Output serializers (camelCase) and input validation for the API."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from watcher.constants import PITCH_MAX_CHARS_MAX, PITCH_MAX_CHARS_MIN
from watcher.models import CheckRun, Job, Source
from watcher.services.runs import run_duration_seconds, run_looks_stalled
from watcher.services.visits import IS_NEW_ANNOTATION, job_is_new, previous_visit_end

GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
GROUP_KEY_RE = re.compile(r"^[a-z0-9_]{1,40}$")
GUPY_TERM_MIN = 2
GUPY_TERM_MAX = 100
SCORING_WEIGHT_LIMIT = 100
SCORING_MAX_TERMS = 300
SCORING_TERM_MAX = 80
MANUAL_TITLE_MAX = 300
MANUAL_URL_MAX = 1000
MANUAL_TEXT_MAX = 200


class JobSerializer(serializers.ModelSerializer):
    sourceId = serializers.IntegerField(source="source_id")
    sourceKind = serializers.CharField(source="source.kind")
    sourceName = serializers.CharField(source="source.name")
    companyName = serializers.CharField(source="company_name")
    externalId = serializers.CharField(source="external_id")
    workMode = serializers.CharField(source="work_mode")
    publishedAt = serializers.DateTimeField(source="published_at", allow_null=True)
    scoreTags = serializers.ListField(source="score_tags", child=serializers.CharField())
    scoreGroups = serializers.ListField(source="score_groups", child=serializers.CharField())
    archiveSource = serializers.CharField(source="archive_source", allow_null=True)
    archiveReason = serializers.CharField(source="archive_reason", allow_null=True)
    archiveNote = serializers.CharField(source="archive_note", allow_null=True)
    isHighlighted = serializers.BooleanField(source="is_highlighted")
    isNew = serializers.SerializerMethodField()
    firstSeenAt = serializers.DateTimeField(source="first_seen_at")
    lastSeenAt = serializers.DateTimeField(source="last_seen_at")
    archivedAt = serializers.DateTimeField(source="archived_at", allow_null=True)
    reopenedAt = serializers.DateTimeField(source="reopened_at", allow_null=True)
    firstVisitedAt = serializers.DateTimeField(source="first_visited_at", allow_null=True)
    lastVisitedAt = serializers.DateTimeField(source="last_visited_at", allow_null=True)
    application = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [
            "id",
            "sourceId",
            "sourceKind",
            "sourceName",
            "companyName",
            "externalId",
            "title",
            "url",
            "location",
            "workMode",
            "seniority",
            "publishedAt",
            "score",
            "scoreTags",
            "scoreGroups",
            "status",
            "archiveSource",
            "archiveReason",
            "archiveNote",
            "isHighlighted",
            "isNew",
            "firstSeenAt",
            "lastSeenAt",
            "archivedAt",
            "reopenedAt",
            "firstVisitedAt",
            "lastVisitedAt",
            "application",
        ]
        read_only_fields = fields

    def get_isNew(self, job: Job) -> bool:  # noqa: N802 - camelCase API field
        annotated = getattr(job, IS_NEW_ANNOTATION, None)
        if annotated is not None:
            return bool(annotated)
        return job_is_new(job, self._previous_visit_end())

    def _previous_visit_end(self) -> datetime | None:
        """Read the visit boundary once per serialization, also when nested."""
        root = self.root
        if "previous_visit_end" in self.context:
            return self.context["previous_visit_end"]
        if not hasattr(root, "_previous_visit_end_cache"):
            root._previous_visit_end_cache = previous_visit_end()  # type: ignore[attr-defined]
        return root._previous_visit_end_cache  # type: ignore[attr-defined]

    def get_application(self, job: Job) -> dict[str, Any] | None:
        try:
            application = job.application  # type: ignore[attr-defined]
        except ObjectDoesNotExist:
            return None
        return {"id": application.pk, "status": application.status}


class SourceSerializer(serializers.ModelSerializer):
    isActive = serializers.BooleanField(source="is_active")
    lastCheckedAt = serializers.DateTimeField(source="last_checked_at", allow_null=True)
    lastError = serializers.CharField(source="last_error", allow_null=True)
    activeJobs = serializers.SerializerMethodField()
    highlightedJobs = serializers.SerializerMethodField()
    applications = serializers.SerializerMethodField()
    lastRunJobs = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at")
    updatedAt = serializers.DateTimeField(source="updated_at")

    class Meta:
        model = Source
        fields = [
            "id",
            "kind",
            "name",
            "target",
            "isActive",
            "lastCheckedAt",
            "lastError",
            "activeJobs",
            "highlightedJobs",
            "applications",
            "lastRunJobs",
            "createdAt",
            "updatedAt",
        ]
        read_only_fields = fields

    def get_activeJobs(self, source: Source) -> int:  # noqa: N802 - camelCase API field
        annotated = getattr(source, "active_jobs", None)
        if annotated is not None:
            return int(annotated)
        return source.jobs.filter(status=Job.Status.ACTIVE).count()

    def get_highlightedJobs(self, source: Source) -> int:  # noqa: N802
        annotated = getattr(source, "highlighted_jobs", None)
        if annotated is not None:
            return int(annotated)
        return source.jobs.filter(
            status=Job.Status.ACTIVE, is_highlighted=True, application__isnull=True
        ).count()

    def get_applications(self, source: Source) -> int:
        annotated = getattr(source, "application_count", None)
        if annotated is not None:
            return int(annotated)
        return source.jobs.filter(application__isnull=False).count()

    def get_lastRunJobs(self, source: Source) -> int | None:  # noqa: N802
        if hasattr(source, "last_run_jobs"):
            value = source.last_run_jobs  # type: ignore[attr-defined]
            return None if value is None else int(value)
        row = (
            source.run_states.filter(run__finished_at__isnull=False, jobs__isnull=False)
            .order_by("-run__finished_at", "-run_id")
            .values_list("jobs", flat=True)
            .first()
        )
        return None if row is None else int(row)


class CheckRunSerializer(serializers.ModelSerializer):
    requestedAt = serializers.DateTimeField(source="requested_at")
    startedAt = serializers.DateTimeField(source="started_at", allow_null=True)
    finishedAt = serializers.DateTimeField(source="finished_at", allow_null=True)
    heartbeatAt = serializers.DateTimeField(source="heartbeat_at", allow_null=True)
    sourcesTotal = serializers.IntegerField(source="sources_total")
    sourcesChecked = serializers.IntegerField(source="sources_checked")
    jobsFound = serializers.IntegerField(source="jobs_found")
    jobsNew = serializers.IntegerField(source="jobs_new")
    jobsArchived = serializers.IntegerField(source="jobs_archived")
    durationSeconds = serializers.SerializerMethodField()
    isStalled = serializers.SerializerMethodField()

    class Meta:
        model = CheckRun
        fields = [
            "id",
            "trigger",
            "status",
            "requestedAt",
            "startedAt",
            "finishedAt",
            "heartbeatAt",
            "sourcesTotal",
            "sourcesChecked",
            "jobsFound",
            "jobsNew",
            "jobsArchived",
            "error",
            "durationSeconds",
            "isStalled",
        ]
        read_only_fields = fields

    def get_durationSeconds(self, run: CheckRun) -> float | None:  # noqa: N802
        return run_duration_seconds(run)

    def get_isStalled(self, run: CheckRun) -> bool:  # noqa: N802
        return run_looks_stalled(run)


class RunProgressSerializer(serializers.Serializer):
    runId = serializers.IntegerField()
    startedAt = serializers.DateTimeField(allow_null=True)
    updatedAt = serializers.DateTimeField()
    total = serializers.IntegerField()
    settled = serializers.IntegerField()
    counts = serializers.DictField(child=serializers.IntegerField())
    sources = serializers.ListField(child=serializers.DictField())


def _require_object(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise serializers.ValidationError({"body": "Expected a JSON object."})
    return data


def clean_source_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise serializers.ValidationError({"name": "Name must not be blank."})
    return value.strip()[:255]


def clean_inhire_url(value: Any) -> str:
    """Trim, drop the trailing slash and accept only InHire career pages."""
    if not isinstance(value, str):
        raise serializers.ValidationError({"target": "target must be a string."})
    clean_url = value.strip().rstrip("/")
    parsed = urlparse(clean_url)
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or not hostname.endswith(".inhire.app"):
        raise serializers.ValidationError(
            {"target": "URL must be an http(s) InHire career page (*.inhire.app)."}
        )
    return clean_url


def clean_source_target(kind: str, value: Any) -> str:
    if kind == Source.Kind.INHIRE:
        return clean_inhire_url(value)
    if not isinstance(value, str):
        raise serializers.ValidationError({"target": "target must be a string."})
    cleaned = value.strip()
    if kind == Source.Kind.GUPY:
        if not GUPY_TERM_MIN <= len(cleaned) <= GUPY_TERM_MAX:
            raise serializers.ValidationError(
                {"target": f"Search term must have {GUPY_TERM_MIN} to {GUPY_TERM_MAX} characters."}
            )
        return cleaned
    if kind == Source.Kind.GITHUB:
        if not GITHUB_REPO_RE.match(cleaned):
            raise serializers.ValidationError({"target": "Repository must look like owner/repo."})
        return cleaned
    raise serializers.ValidationError({"kind": "kind must be one of: inhire, gupy, github."})


def validate_source_create(data: Any) -> tuple[str, str, str]:
    body = _require_object(data)
    errors: dict[str, str] = {}
    kind = body.get("kind")
    if kind not in {Source.Kind.INHIRE, Source.Kind.GUPY, Source.Kind.GITHUB}:
        errors["kind"] = "kind must be one of: inhire, gupy, github."
    name = target = ""
    try:
        name = clean_source_name(body.get("name"))
    except serializers.ValidationError as error:
        errors.update(first_messages(error))
    if "kind" not in errors:
        try:
            target = clean_source_target(str(kind), body.get("target"))
        except serializers.ValidationError as error:
            errors.update(first_messages(error))
    if errors:
        raise serializers.ValidationError(errors)
    return str(kind), name, target


def validate_source_patch(kind: str, data: Any) -> dict[str, Any]:
    body = _require_object(data)
    errors: dict[str, str] = {}
    values: dict[str, Any] = {}
    if "name" in body:
        try:
            values["name"] = clean_source_name(body["name"])
        except serializers.ValidationError as error:
            errors.update(first_messages(error))
    if "target" in body:
        try:
            values["target"] = clean_source_target(kind, body["target"])
        except serializers.ValidationError as error:
            errors.update(first_messages(error))
    if "isActive" in body:
        if isinstance(body["isActive"], bool):
            values["is_active"] = body["isActive"]
        else:
            errors["isActive"] = "isActive must be a boolean."
    if errors:
        raise serializers.ValidationError(errors)
    return values


def _optional_text(body: dict[str, Any], field: str, limit: int, errors: dict[str, str]) -> str:
    value = body.get(field)
    if value is None:
        return ""
    if not isinstance(value, str):
        errors[field] = f"{field} must be a string."
        return ""
    cleaned = value.strip()
    if len(cleaned) > limit:
        errors[field] = f"{field} must have at most {limit} characters."
    return cleaned


def validate_manual_job(data: Any) -> dict[str, Any]:
    body = _require_object(data)
    errors: dict[str, str] = {}
    title = body.get("title")
    if not isinstance(title, str) or not title.strip():
        errors["title"] = "Title must not be blank."
    elif len(title.strip()) > MANUAL_TITLE_MAX:
        errors["title"] = f"Title must have at most {MANUAL_TITLE_MAX} characters."
    url = body.get("url")
    clean_url = url.strip() if isinstance(url, str) else ""
    parsed = urlparse(clean_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        errors["url"] = "URL must be an http(s) address."
    elif len(clean_url) > MANUAL_URL_MAX:
        errors["url"] = f"URL must have at most {MANUAL_URL_MAX} characters."
    company = _optional_text(body, "companyName", MANUAL_TEXT_MAX, errors)
    location = _optional_text(body, "location", MANUAL_TEXT_MAX, errors)
    description = body.get("description") or ""
    if not isinstance(description, str):
        errors["description"] = "description must be a string."
        description = ""
    work_mode = body.get("workMode") or Job.WorkMode.UNKNOWN
    if work_mode not in Job.WorkMode.values:
        errors["workMode"] = "workMode must be one of: " + ", ".join(Job.WorkMode.values) + "."
    seniority = body.get("seniority") or Job.Seniority.UNKNOWN
    if seniority not in Job.Seniority.values:
        errors["seniority"] = "seniority must be one of: " + ", ".join(Job.Seniority.values) + "."
    if errors:
        raise serializers.ValidationError(errors)
    return {
        "title": str(title).strip(),
        "url": clean_url,
        "company_name": company,
        "location": location,
        "description": description.strip(),
        "work_mode": work_mode,
        "seniority": seniority,
    }


def validate_scoring(data: Any) -> tuple[dict[str, Any] | None, int | None]:
    """Validate ``{ groups, minScore }``; blank terms are dropped after strip.

    ``stackGroups`` is validated separately by ``validate_stack_groups`` because
    it depends on the effective groups.
    """
    body = _require_object(data)
    errors: dict[str, str] = {}
    groups = body.get("groups")
    cleaned_groups: dict[str, Any] | None = None
    if groups is not None:
        if not isinstance(groups, dict):
            errors["groups"] = "groups must be an object or null."
        else:
            cleaned_groups = {}
            for key, group in groups.items():
                field = f"groups.{key}"
                if not isinstance(key, str) or not GROUP_KEY_RE.match(key):
                    errors[field] = "Group key must match ^[a-z0-9_]{1,40}$."
                    continue
                if not isinstance(group, dict):
                    errors[field] = "Group must be an object with weight and terms."
                    continue
                weight = group.get("weight")
                if (
                    not isinstance(weight, int)
                    or isinstance(weight, bool)
                    or not -SCORING_WEIGHT_LIMIT <= weight <= SCORING_WEIGHT_LIMIT
                ):
                    errors[f"{field}.weight"] = "weight must be an integer from -100 to 100."
                    continue
                terms = group.get("terms")
                if not isinstance(terms, list) or not all(isinstance(term, str) for term in terms):
                    errors[f"{field}.terms"] = "terms must be a list of strings."
                    continue
                stripped = [term.strip() for term in terms if term.strip()]
                if len(stripped) > SCORING_MAX_TERMS:
                    errors[f"{field}.terms"] = f"A group accepts at most {SCORING_MAX_TERMS} terms."
                    continue
                if any(len(term) > SCORING_TERM_MAX for term in stripped):
                    errors[f"{field}.terms"] = (
                        f"Each term must have at most {SCORING_TERM_MAX} characters."
                    )
                    continue
                cleaned_groups[key] = {"weight": weight, "terms": stripped}
    min_score = body.get("minScore")
    if min_score is not None and (not isinstance(min_score, int) or isinstance(min_score, bool)):
        errors["minScore"] = "minScore must be an integer."
        min_score = None
    if errors:
        raise serializers.ValidationError(errors)
    return cleaned_groups, min_score


def validate_stack_groups(data: Any, groups: dict[str, Any]) -> list[str] | None:
    """``stackGroups`` from the body: ``None`` when absent, else keys of ``groups``."""
    body = _require_object(data)
    if "stackGroups" not in body:
        return None
    value = body["stackGroups"]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise serializers.ValidationError({"stackGroups": "stackGroups must be a list of strings."})
    unknown = [item for item in value if item not in groups]
    if unknown:
        raise serializers.ValidationError(
            {"stackGroups": "Unknown scoring group(s): " + ", ".join(unknown) + "."}
        )
    # Keep the order of first appearance, without duplicates.
    return list(dict.fromkeys(value))


def validate_profile(data: Any) -> dict[str, Any]:
    body = _require_object(data)
    errors: dict[str, str] = {}
    values: dict[str, Any] = {}
    if "dossier" in body:
        if isinstance(body["dossier"], str):
            values["dossier"] = body["dossier"]
        else:
            errors["dossier"] = "dossier must be a string."
    if "pitchMaxChars" in body:
        value = body["pitchMaxChars"]
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and PITCH_MAX_CHARS_MIN <= value <= PITCH_MAX_CHARS_MAX
        ):
            values["pitch_max_chars"] = value
        else:
            errors["pitchMaxChars"] = (
                f"pitchMaxChars must be an integer from {PITCH_MAX_CHARS_MIN} "
                f"to {PITCH_MAX_CHARS_MAX}."
            )
    if "geminiModel" in body:
        value = body["geminiModel"]
        if isinstance(value, str) and len(value.strip()) <= 80:
            values["gemini_model"] = value.strip()
        else:
            errors["geminiModel"] = "geminiModel must be a string up to 80 characters."
    if errors:
        raise serializers.ValidationError(errors)
    return values


def validate_secrets(data: Any) -> dict[str, str]:
    body = _require_object(data)
    errors: dict[str, str] = {}
    values: dict[str, str] = {}
    for field, name in (("geminiApiKey", "gemini_api_key"), ("githubToken", "github_token")):
        if field not in body:
            continue
        value = body[field]
        if isinstance(value, str) and len(value) <= 500:
            values[name] = value
        else:
            errors[field] = f"{field} must be a string."
    if errors:
        raise serializers.ValidationError(errors)
    return values


def first_messages(error: serializers.ValidationError) -> dict[str, str]:
    detail = error.detail
    if isinstance(detail, dict):
        return {
            str(key): str(value[0] if isinstance(value, list) else value)
            for key, value in detail.items()
        }
    return {"non_field_errors": str(detail)}
