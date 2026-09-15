"""camelCase output and input validation for the funnel, timeline and pitches."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.utils import timezone
from rest_framework import serializers

from pipeline.dates import local_today
from pipeline.models import Application, Interaction, Pitch
from watcher.serializers import JobSerializer, first_messages

NEXT_STEP_MAX = 300
CONTACT_MAX = 200
INTERACTION_TITLE_MAX = 200
PITCH_INSTRUCTION_MAX = 300


class ApplicationSerializer(serializers.ModelSerializer):
    job = JobSerializer()
    appliedOn = serializers.DateField(source="applied_on", allow_null=True)
    nextStep = serializers.CharField(source="next_step")
    nextStepOn = serializers.DateField(source="next_step_on", allow_null=True)
    hasReferral = serializers.BooleanField(source="has_referral")
    isOverdue = serializers.SerializerMethodField()
    daysIdle = serializers.SerializerMethodField()
    interactionsCount = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at")
    updatedAt = serializers.DateTimeField(source="updated_at")

    class Meta:
        model = Application
        fields = [
            "id",
            "job",
            "status",
            "priority",
            "appliedOn",
            "nextStep",
            "nextStepOn",
            "contact",
            "hasReferral",
            "notes",
            "isOverdue",
            "daysIdle",
            "interactionsCount",
            "createdAt",
            "updatedAt",
        ]
        read_only_fields = fields

    def get_isOverdue(self, application: Application) -> bool:  # noqa: N802
        return application.is_overdue(self.context.get("today"))

    def get_daysIdle(self, application: Application) -> int:  # noqa: N802
        return max((timezone.now() - application.updated_at).days, 0)

    def get_interactionsCount(self, application: Application) -> int:  # noqa: N802
        annotated = getattr(application, "interactions_count", None)
        if annotated is not None:
            return int(annotated)
        return application.interactions.count()


class InteractionSerializer(serializers.ModelSerializer):
    applicationId = serializers.IntegerField(source="application_id")
    createdAt = serializers.DateTimeField(source="created_at")

    class Meta:
        model = Interaction
        fields = ["id", "applicationId", "date", "title", "detail", "createdAt"]
        read_only_fields = fields


class PitchSerializer(serializers.ModelSerializer):
    jobId = serializers.IntegerField(source="job_id")
    maxChars = serializers.IntegerField(source="max_chars")
    chars = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at")

    class Meta:
        model = Pitch
        fields = ["id", "jobId", "text", "model", "instruction", "maxChars", "chars", "createdAt"]
        read_only_fields = fields

    def get_chars(self, pitch: Pitch) -> int:
        return len(pitch.text)


def _require_object(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise serializers.ValidationError({"body": "Expected a JSON object."})
    return data


def _parse_date(value: Any, field: str, errors: dict[str, str]) -> date | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    errors[field] = f"{field} must be a YYYY-MM-DD date or null."
    return None


def _text(value: Any, field: str, limit: int | None, errors: dict[str, str]) -> str:
    if not isinstance(value, str):
        errors[field] = f"{field} must be a string."
        return ""
    cleaned = value.strip()
    if limit is not None and len(cleaned) > limit:
        errors[field] = f"{field} must have at most {limit} characters."
    return cleaned


def validate_application_create(data: Any) -> str:
    body = data if isinstance(data, dict) else {}
    status = body.get("status") or Application.Status.APPLIED
    if status not in {Application.Status.INTEREST, Application.Status.APPLIED}:
        raise serializers.ValidationError({"status": "status must be interest or applied."})
    return str(status)


def validate_application_patch(data: Any) -> dict[str, Any]:
    body = _require_object(data)
    errors: dict[str, str] = {}
    values: dict[str, Any] = {}
    if "status" in body:
        if body["status"] in Application.Status.values:
            values["status"] = body["status"]
        else:
            errors["status"] = (
                "status must be one of: " + ", ".join(Application.Status.values) + "."
            )
    if "priority" in body:
        priority = body["priority"]
        if isinstance(priority, int) and not isinstance(priority, bool) and 1 <= priority <= 5:
            values["priority"] = priority
        else:
            errors["priority"] = "priority must be an integer from 1 to 5."
    if "appliedOn" in body:
        values["applied_on"] = _parse_date(body["appliedOn"], "appliedOn", errors)
    if "nextStepOn" in body:
        values["next_step_on"] = _parse_date(body["nextStepOn"], "nextStepOn", errors)
    if "nextStep" in body:
        values["next_step"] = _text(body["nextStep"], "nextStep", NEXT_STEP_MAX, errors)
    if "contact" in body:
        values["contact"] = _text(body["contact"], "contact", CONTACT_MAX, errors)
    if "notes" in body:
        values["notes"] = _text(body["notes"], "notes", None, errors)
    if "hasReferral" in body:
        if isinstance(body["hasReferral"], bool):
            values["has_referral"] = body["hasReferral"]
        else:
            errors["hasReferral"] = "hasReferral must be a boolean."
    if errors:
        raise serializers.ValidationError(errors)
    return values


def validate_interaction(data: Any, *, partial: bool) -> dict[str, Any]:
    body = _require_object(data)
    errors: dict[str, str] = {}
    values: dict[str, Any] = {}
    if "title" in body or not partial:
        title = _text(body.get("title"), "title", INTERACTION_TITLE_MAX, errors)
        if not title and "title" not in errors:
            errors["title"] = "Title must not be blank."
        values["title"] = title
    if "detail" in body:
        detail = body["detail"]
        values["detail"] = "" if detail is None else _text(detail, "detail", None, errors)
    if "date" in body:
        parsed = _parse_date(body["date"], "date", errors)
        if parsed is None and "date" not in errors:
            errors["date"] = "date must be a YYYY-MM-DD date."
        values["date"] = parsed
    elif not partial:
        values["date"] = local_today()
    if errors:
        raise serializers.ValidationError(errors)
    return values


def validate_pitch_request(data: Any) -> str:
    body = data if isinstance(data, dict) else {}
    instruction = body.get("instruction") or ""
    if not isinstance(instruction, str):
        raise serializers.ValidationError({"instruction": "instruction must be a string."})
    if len(instruction.strip()) > PITCH_INSTRUCTION_MAX:
        raise serializers.ValidationError(
            {"instruction": f"instruction must have at most {PITCH_INSTRUCTION_MAX} characters."}
        )
    return instruction.strip()


__all__ = [
    "ApplicationSerializer",
    "InteractionSerializer",
    "PitchSerializer",
    "first_messages",
    "validate_application_create",
    "validate_application_patch",
    "validate_interaction",
    "validate_pitch_request",
]
