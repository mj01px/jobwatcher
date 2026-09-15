"""Funnel API: board, closed applications, edits, timeline and cover letters."""

from __future__ import annotations

import threading
from typing import Any

from django.db.models import Count, QuerySet
from django.utils import timezone
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from pipeline.dates import local_today
from pipeline.models import ACTIVE_STATUSES, CLOSED_STATUSES, Application, Interaction
from pipeline.pitch.dossier import DossierEmptyError
from pipeline.pitch.gemini import GeminiNotConfiguredError, GeminiUnavailableError
from pipeline.pitch.service import generate_and_save
from pipeline.serializers import (
    ApplicationSerializer,
    InteractionSerializer,
    PitchSerializer,
    validate_application_create,
    validate_application_patch,
    validate_interaction,
    validate_pitch_request,
)
from pipeline.services import ApplicationExistsError, enter_pipeline, update_application
from watcher.api import ApiError, envelope_response
from watcher.models import Job

# One generation at a time: it takes seconds and burns free tier quota.
_pitch_lock = threading.Lock()


def applications_queryset() -> QuerySet[Application]:
    return Application.objects.select_related("job__source").annotate(
        interactions_count=Count("interactions")
    )


def _not_found(message: str) -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", message)


def _application_or_404(application_id: int) -> Application:
    application = applications_queryset().filter(pk=application_id).first()
    if application is None:
        raise _not_found("Application not found")
    return application


def _job_or_404(job_id: int) -> Job:
    job = Job.objects.select_related("source").filter(pk=job_id).first()
    if job is None:
        raise _not_found("Job not found")
    return job


def _serialize(applications: Any, *, many: bool = False) -> Any:
    return ApplicationSerializer(applications, many=many, context={"today": local_today()}).data


def _application_payload(application_id: int) -> dict[str, Any]:
    return _serialize(_application_or_404(application_id))


class JobApplicationCreateView(APIView):
    def post(self, request: Request, job_id: int) -> Response:
        job = _job_or_404(job_id)
        requested_status = validate_application_create(request.data)
        try:
            application = enter_pipeline(job, requested_status)
        except ApplicationExistsError as error:
            raise ApiError(
                status.HTTP_409_CONFLICT, "CONFLICT", "This job is already in the funnel"
            ) from error
        return envelope_response(
            _application_payload(application.pk), status_code=status.HTTP_201_CREATED
        )


class ApplicationBoardView(APIView):
    def get(self, _: Request) -> Response:
        today = local_today()
        applications = list(applications_queryset())
        active = [app for app in applications if app.status in ACTIVE_STATUSES]
        columns = []
        for column_status in ACTIVE_STATUSES:
            items = [app for app in active if app.status == column_status]
            items.sort(key=lambda app: (app.priority, -app.updated_at.timestamp(), -app.pk))
            columns.append({"status": column_status, "applications": _serialize(items, many=True)})
        overdue = sorted(
            (app for app in active if app.is_overdue(today)),
            key=lambda app: (app.next_step_on, app.priority, app.pk),
        )
        counts = {value: 0 for value in Application.Status.values}
        for app in applications:
            counts[app.status] += 1
        return envelope_response(
            {"columns": columns, "overdue": _serialize(overdue, many=True), "counts": counts}
        )


class ApplicationClosedView(APIView):
    def get(self, _: Request) -> Response:
        closed = (
            applications_queryset()
            .filter(status__in=CLOSED_STATUSES)
            .order_by("-updated_at", "-id")
        )
        return envelope_response(_serialize(closed, many=True))


class ApplicationDetailView(APIView):
    def get(self, _: Request, application_id: int) -> Response:
        application = _application_or_404(application_id)
        payload = dict(_serialize(application))
        payload["interactions"] = InteractionSerializer(
            application.interactions.order_by("-date", "-id"), many=True
        ).data
        return envelope_response(payload)

    def patch(self, request: Request, application_id: int) -> Response:
        application = _application_or_404(application_id)
        values = validate_application_patch(request.data)
        update_application(application, values)
        return envelope_response(_application_payload(application.pk))

    def delete(self, _: Request, application_id: int) -> Response:
        application = _application_or_404(application_id)
        application.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ApplicationInteractionsView(APIView):
    def post(self, request: Request, application_id: int) -> Response:
        application = _application_or_404(application_id)
        values = validate_interaction(request.data, partial=False)
        now = timezone.now()
        interaction = Interaction.objects.create(
            application=application, created_at=now, updated_at=now, **values
        )
        return envelope_response(
            InteractionSerializer(interaction).data, status_code=status.HTTP_201_CREATED
        )


class InteractionDetailView(APIView):
    def _get(self, interaction_id: int) -> Interaction:
        interaction = Interaction.objects.filter(pk=interaction_id).first()
        if interaction is None:
            raise _not_found("Interaction not found")
        return interaction

    def patch(self, request: Request, interaction_id: int) -> Response:
        interaction = self._get(interaction_id)
        values = validate_interaction(request.data, partial=True)
        for field, value in values.items():
            setattr(interaction, field, value)
        interaction.updated_at = timezone.now()
        interaction.save()
        return envelope_response(InteractionSerializer(interaction).data)

    def delete(self, _: Request, interaction_id: int) -> Response:
        self._get(interaction_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class JobPitchView(APIView):
    def get(self, _: Request, job_id: int) -> Response:
        job = _job_or_404(job_id)
        pitch = job.pitches.order_by("-created_at", "-id").first()  # type: ignore[attr-defined]
        return envelope_response(PitchSerializer(pitch).data if pitch else None)

    def post(self, request: Request, job_id: int) -> Response:
        job = _job_or_404(job_id)
        instruction = validate_pitch_request(request.data)
        if not _pitch_lock.acquire(blocking=False):
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "PITCH_IN_PROGRESS",
                "A cover letter is already being generated",
            )
        try:
            pitch = generate_and_save(job, instruction)
        except DossierEmptyError as error:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "DOSSIER_EMPTY", str(error)
            ) from error
        except GeminiNotConfiguredError as error:
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE, "GEMINI_NOT_CONFIGURED", str(error)
            ) from error
        except GeminiUnavailableError as error:
            raise ApiError(status.HTTP_502_BAD_GATEWAY, "AI_UNAVAILABLE", str(error)) from error
        finally:
            _pitch_lock.release()
        return envelope_response(PitchSerializer(pitch).data, status_code=status.HTTP_201_CREATED)
