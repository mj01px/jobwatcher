"""HTTP views: the JSON API, the health check and the SPA entry point."""

from __future__ import annotations

import math
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import (
    Case,
    Count,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Lower
from django.http import FileResponse, HttpRequest, HttpResponse, HttpResponseNotFound, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.fields import DateTimeField
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from pipeline.dates import local_today
from pipeline.models import ACTIVE_STATUSES, Application
from pipeline.serializers import ApplicationSerializer, PitchSerializer
from pipeline.views import applications_queryset
from watcher.api import ApiError, envelope_response, validation_error
from watcher.constants import (
    ACTIVITY_HISTORY_LIMIT,
    ACTIVITY_HISTORY_MAX,
    ARCHIVE_NOTE_MAX_LENGTH,
    ARCHIVE_REASON_SLUGS,
    COLLECTED_SOURCE_KINDS,
    DOSSIER_KEY,
    GEMINI_MODEL_KEY,
    MANUAL_SOURCE_TARGET,
    OVERDUE_APPLICATIONS_LIMIT,
    PAGE_SIZE,
    PITCH_MAX_CHARS_KEY,
    RECENT_JOBS_LIMIT,
    SOURCE_REMOVED_REASON,
)
from watcher.models import CheckRun, CheckRunSource, Job, Source
from watcher.scoring import PROFILE
from watcher.serializers import (
    CheckRunSerializer,
    JobSerializer,
    RunProgressSerializer,
    SourceSerializer,
    validate_manual_job,
    validate_profile,
    validate_scoring,
    validate_secrets,
    validate_source_create,
    validate_source_patch,
    validate_stack_groups,
)
from watcher.services.collection import manual_key
from watcher.services.pagination import normalize_page
from watcher.services.preferences import profile_payload, secrets_payload, set_setting
from watcher.services.runs import (
    PENDING_STATUSES,
    build_progress,
    enqueue_run,
    run_looks_stalled,
    worker_is_online,
)
from watcher.services.schedule import next_scheduled_run
from watcher.services.scoring import (
    apply_classification,
    get_min_score,
    load_scoring,
    save_scoring,
    saved_profile,
    scoring_payload,
)
from watcher.services.secrets import set_secrets
from watcher.services.visits import (
    IS_NEW_ANNOTATION,
    annotate_is_new,
    new_job_q,
    previous_visit_end,
    register_visit,
)

JOB_VIEWS = ("all", "highlighted", "archived")
LISTING_ORDER = (f"-{IS_NEW_ANNOTATION}", "-first_seen_at", Lower("title"))
HIGHLIGHT_ORDER = ("-score", f"-{IS_NEW_ANNOTATION}", "-first_seen_at", Lower("title"))


def _jobs() -> QuerySet[Job]:
    return Job.objects.select_related("source", "application")


def _job_view_queryset(view: str) -> QuerySet[Job]:
    queryset = annotate_is_new(_jobs(), previous_visit_end())
    if view == "archived":
        return queryset.filter(status=Job.Status.ARCHIVED).order_by(*LISTING_ORDER)
    queryset = queryset.filter(status=Job.Status.ACTIVE, application__isnull=True)
    if view == "highlighted":
        return queryset.filter(is_highlighted=True).order_by(*HIGHLIGHT_ORDER)
    return queryset.order_by(*LISTING_ORDER)


def _kind_order() -> Case:
    return Case(
        *[When(kind=kind, then=Value(index)) for index, kind in enumerate(COLLECTED_SOURCE_KINDS)],
        default=Value(len(COLLECTED_SOURCE_KINDS)),
        output_field=IntegerField(),
    )


def _annotated_sources() -> QuerySet[Source]:
    """Sources with their yield: active, highlighted, in the funnel, last run."""
    last_run_jobs = (
        CheckRunSource.objects.filter(
            source=OuterRef("pk"), run__finished_at__isnull=False, jobs__isnull=False
        )
        .order_by("-run__finished_at", "-run_id")
        .values("jobs")[:1]
    )
    return Source.objects.annotate(
        active_jobs=Count("jobs", filter=Q(jobs__status=Job.Status.ACTIVE), distinct=True),
        highlighted_jobs=Count(
            "jobs",
            filter=Q(
                jobs__status=Job.Status.ACTIVE,
                jobs__is_highlighted=True,
                jobs__application__isnull=True,
            ),
            distinct=True,
        ),
        application_count=Count("jobs", filter=Q(jobs__application__isnull=False), distinct=True),
        last_run_jobs=Subquery(last_run_jobs, output_field=IntegerField()),
    )


def _sources_with_counts() -> QuerySet[Source]:
    return (
        _annotated_sources()
        .filter(is_removed=False, is_hidden=False)
        .annotate(kind_order=_kind_order())
        .order_by("kind_order", Lower("name"), "id")
    )


def _job_payload(job_id: int) -> dict[str, Any]:
    return JobSerializer(_jobs().get(pk=job_id)).data


def _source_payload(source_id: int) -> dict[str, Any]:
    return SourceSerializer(_annotated_sources().get(pk=source_id)).data


def _datetime(value: Any) -> Any:
    return DateTimeField().to_representation(value) if value is not None else None


def _not_found(message: str) -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", message)


def healthcheck(_: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "time": timezone.now().isoformat()})


@ensure_csrf_cookie
def spa_index(_: HttpRequest) -> HttpResponse:
    """Serve the built React app for every non API route."""
    index = settings.FRONTEND_DIST / "index.html"
    if not index.is_file():
        return HttpResponseNotFound(
            "Job Watcher frontend is not built. Run `pnpm build` in frontend/ "
            "or use the Vite dev server.",
            content_type="text/plain; charset=utf-8",
        )
    response = FileResponse(index.open("rb"), content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    return response


class ApiNotFoundView(APIView):
    def _not_found(self, *_: Any, **__: Any) -> Response:
        raise _not_found("Resource not found")

    get = post = put = patch = delete = _not_found


class StatusView(APIView):
    def get(self, request: Request) -> Response:
        get_token(request._request)
        last_run = CheckRun.objects.order_by("-requested_at", "-id").first()
        is_running = CheckRun.objects.filter(status__in=PENDING_STATUSES).exists()
        running = (
            CheckRun.objects.filter(status=CheckRun.Status.RUNNING)
            .order_by("-requested_at", "-id")
            .first()
        )
        progress = RunProgressSerializer(build_progress(running)).data if running else None
        return envelope_response(
            {
                "lastRun": CheckRunSerializer(last_run).data if last_run else None,
                "isRunning": is_running,
                "isStalled": run_looks_stalled(last_run),
                "progress": progress,
                "nextRunAt": _datetime(next_scheduled_run()),
                "workerOnline": worker_is_online(),
            }
        )


class OverviewView(APIView):
    def get(self, _: Request) -> Response:
        triage = Q(status=Job.Status.ACTIVE, application__isnull=True)
        previous_end = previous_visit_end()
        job_stats = Job.objects.aggregate(
            active=Count("id", filter=triage),
            new=Count("id", filter=triage & new_job_q(previous_end)),
            highlighted=Count("id", filter=triage & Q(is_highlighted=True)),
            archived=Count("id", filter=Q(status=Job.Status.ARCHIVED)),
        )
        visible = Q(is_removed=False, is_hidden=False)
        source_stats = Source.objects.aggregate(
            active=Count("id", filter=visible & Q(is_active=True)),
            errors=Count("id", filter=visible & Q(last_error__isnull=False)),
        )
        today = local_today()
        active_apps = Application.objects.filter(status__in=ACTIVE_STATUSES)
        overdue_apps = active_apps.filter(next_step_on__lt=today)
        pipeline_stats = {
            "active": active_apps.count(),
            "overdue": overdue_apps.count(),
            "interviews": active_apps.filter(status=Application.Status.INTERVIEW).count(),
        }
        overdue = (
            applications_queryset()
            .filter(pk__in=overdue_apps.values("pk"))
            .order_by("next_step_on", "priority", "id")[:OVERDUE_APPLICATIONS_LIMIT]
        )
        recent = (
            annotate_is_new(_jobs(), previous_end)
            .filter(triage, is_highlighted=True)
            .order_by(f"-{IS_NEW_ANNOTATION}", "-first_seen_at", "id")[:RECENT_JOBS_LIMIT]
        )
        return envelope_response(
            {
                "jobStats": job_stats,
                "sourceStats": source_stats,
                "pipelineStats": pipeline_stats,
                "overdueApplications": ApplicationSerializer(
                    overdue, many=True, context={"today": today}
                ).data,
                "recentJobs": JobSerializer(recent, many=True).data,
            }
        )


class JobListView(APIView):
    def get(self, request: Request) -> Response:
        view = request.query_params.get("view", "all")
        if view not in JOB_VIEWS:
            raise validation_error("view", "view must be one of: all, highlighted, archived.")
        queryset = _job_view_queryset(view)
        total = queryset.count()
        total_pages = math.ceil(total / PAGE_SIZE) if total else 0
        page = normalize_page(request.query_params.get("page"), total_pages)
        offset = (page - 1) * PAGE_SIZE
        jobs = queryset[offset : offset + PAGE_SIZE]
        return envelope_response(
            JobSerializer(jobs, many=True).data,
            meta={"page": page, "perPage": PAGE_SIZE, "total": total, "totalPages": total_pages},
        )

    def post(self, request: Request) -> Response:
        values = validate_manual_job(request.data)
        key = manual_key(values["url"])
        if Job.objects.filter(key=key).exists():
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "CONFLICT",
                "A job with this URL already exists",
                [{"field": "url", "issue": "URL already registered."}],
            )
        source, _ = Source.objects.get_or_create(
            kind=Source.Kind.MANUAL,
            target=MANUAL_SOURCE_TARGET,
            defaults={"name": "Manual", "is_active": False, "is_hidden": True},
        )
        now = timezone.now()
        job = Job(
            source=source,
            key=key,
            external_id=key.removeprefix("manual:"),
            title=values["title"],
            url=values["url"],
            company_name=values["company_name"],
            location=values["location"],
            description=values["description"],
            first_seen_at=now,
            last_seen_at=now,
        )
        apply_classification(job, load_scoring())
        # What the person states wins over what the text suggests.
        if values["work_mode"] != Job.WorkMode.UNKNOWN:
            job.work_mode = values["work_mode"]
        if values["seniority"] != Job.Seniority.UNKNOWN:
            job.seniority = values["seniority"]
        try:
            job.save()
        except IntegrityError as error:
            raise ApiError(
                status.HTTP_409_CONFLICT, "CONFLICT", "A job with this URL already exists"
            ) from error
        return envelope_response(_job_payload(job.pk), status_code=status.HTTP_201_CREATED)


class JobDetailView(APIView):
    def get(self, _: Request, job_id: int) -> Response:
        job = _jobs().filter(pk=job_id).first()
        if job is None:
            raise _not_found("Job not found")
        payload = dict(JobSerializer(job).data)
        payload["description"] = job.description
        pitch = job.pitches.order_by("-created_at", "-id").first()  # type: ignore[attr-defined]
        payload["pitch"] = PitchSerializer(pitch).data if pitch else None
        return envelope_response(payload)


class JobArchiveView(APIView):
    def post(self, request: Request, job_id: int) -> Response:
        data = request.data if isinstance(request.data, dict) else {}
        reason = data.get("reason")
        if not isinstance(reason, str) or reason not in ARCHIVE_REASON_SLUGS:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "INVALID_ARCHIVE_REASON",
                "Invalid archive reason",
                [{"field": "reason", "issue": "Unknown archive reason."}],
            )
        note = data.get("note") or ""
        if not isinstance(note, str):
            raise validation_error("note", "note must be a string.")
        updated = Job.objects.filter(pk=job_id).update(
            status=Job.Status.ARCHIVED,
            archive_source=Job.ArchiveSource.MANUAL,
            archive_reason=reason,
            archive_note=note.strip()[:ARCHIVE_NOTE_MAX_LENGTH] or None,
            archived_at=timezone.now(),
            arrived_new=False,
        )
        if not updated:
            raise _not_found("Job not found")
        return envelope_response(_job_payload(job_id))


class JobRestoreView(APIView):
    def post(self, _: Request, job_id: int) -> Response:
        updated = Job.objects.filter(pk=job_id).update(
            status=Job.Status.ACTIVE,
            archive_source=None,
            archive_reason=None,
            archive_note=None,
            archived_at=None,
            reopened_at=None,
        )
        if not updated:
            raise _not_found("Job not found")
        return envelope_response(_job_payload(job_id))


class JobVisitView(APIView):
    def post(self, _: Request, job_id: int) -> Response:
        now = timezone.now()
        with transaction.atomic():
            job = get_object_or_404(Job, pk=job_id)
            job.first_visited_at = job.first_visited_at or now
            job.last_visited_at = now
            job.save(update_fields=["first_visited_at", "last_visited_at"])
        return envelope_response(_job_payload(job_id))


class SourceListView(APIView):
    def get(self, _: Request) -> Response:
        return envelope_response(SourceSerializer(_sources_with_counts(), many=True).data)

    def post(self, request: Request) -> Response:
        kind, name, target = validate_source_create(request.data)
        now = timezone.now()
        with transaction.atomic():
            source = Source.objects.filter(kind=kind, target=target).first()
            if source is None:
                source = Source.objects.create(
                    kind=kind,
                    name=name,
                    target=target,
                    is_active=True,
                    is_removed=False,
                    created_at=now,
                    updated_at=now,
                )
            else:
                source.name = name
                source.is_active = True
                source.is_removed = False
                source.is_hidden = False
                source.updated_at = now
                source.save(
                    update_fields=["name", "is_active", "is_removed", "is_hidden", "updated_at"]
                )
        return envelope_response(_source_payload(source.pk), status_code=status.HTTP_201_CREATED)


class SourceDetailView(APIView):
    def _get_source(self, source_id: int) -> Source:
        source = Source.objects.filter(pk=source_id, is_removed=False, is_hidden=False).first()
        if source is None:
            raise _not_found("Source not found")
        return source

    def patch(self, request: Request, source_id: int) -> Response:
        source = self._get_source(source_id)
        values = validate_source_patch(source.kind, request.data)
        if "target" in values and (
            Source.objects.filter(kind=source.kind, target=values["target"])
            .exclude(pk=source.pk)
            .exists()
        ):
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "CONFLICT",
                "Another source already uses this target",
                [{"field": "target", "issue": "Target already registered."}],
            )
        if values:
            for field, value in values.items():
                setattr(source, field, value)
            source.updated_at = timezone.now()
            try:
                source.save(update_fields=[*values.keys(), "updated_at"])
            except IntegrityError as error:
                raise ApiError(
                    status.HTTP_409_CONFLICT, "CONFLICT", "Another source already uses this target"
                ) from error
        return envelope_response(_source_payload(source.pk))

    def delete(self, _: Request, source_id: int) -> Response:
        source = self._get_source(source_id)
        now = timezone.now()
        with transaction.atomic():
            Source.objects.filter(pk=source.pk).update(
                is_active=False, is_removed=True, updated_at=now
            )
            Job.objects.filter(source_id=source.pk, status=Job.Status.ACTIVE).update(
                status=Job.Status.ARCHIVED,
                archive_source=Job.ArchiveSource.SOURCE,
                archive_reason=SOURCE_REMOVED_REASON,
                archive_note=None,
                archived_at=now,
                arrived_new=False,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ScoringSettingsView(APIView):
    def get(self, _: Request) -> Response:
        return envelope_response(scoring_payload())

    def put(self, request: Request) -> Response:
        groups, min_score = validate_scoring(request.data)
        if "groups" not in request.data:
            groups = saved_profile()
        stack_groups = validate_stack_groups(request.data, groups or PROFILE)
        return envelope_response(
            save_scoring(groups, get_min_score() if min_score is None else min_score, stack_groups)
        )


class ProfileSettingsView(APIView):
    def get(self, _: Request) -> Response:
        return envelope_response(profile_payload())

    def put(self, request: Request) -> Response:
        values = validate_profile(request.data)
        keys = {
            "dossier": DOSSIER_KEY,
            "pitch_max_chars": PITCH_MAX_CHARS_KEY,
            "gemini_model": GEMINI_MODEL_KEY,
        }
        for field, value in values.items():
            set_setting(keys[field], value)
        return envelope_response(profile_payload())


class SecretsSettingsView(APIView):
    def put(self, request: Request) -> Response:
        set_secrets(validate_secrets(request.data))
        return envelope_response(secrets_payload())


class VisitView(APIView):
    def post(self, _: Request) -> Response:
        visit = register_visit()
        return envelope_response(
            {
                "visitStartedAt": _datetime(visit["visit_started_at"]),
                "previousVisitEndedAt": _datetime(visit["previous_visit_ended_at"]),
            }
        )


class CheckRunListView(APIView):
    def get(self, request: Request) -> Response:
        raw_limit = request.query_params.get("limit")
        limit = ACTIVITY_HISTORY_LIMIT
        if raw_limit not in (None, ""):
            try:
                limit = int(raw_limit)
            except ValueError as error:
                raise validation_error("limit", "limit must be an integer.") from error
            if limit < 1:
                raise validation_error("limit", "limit must be at least 1.")
            limit = min(limit, ACTIVITY_HISTORY_MAX)
        runs = CheckRun.objects.order_by("-requested_at", "-id")[:limit]
        return envelope_response(CheckRunSerializer(runs, many=True).data)

    def post(self, _: Request) -> Response:
        run, _created = enqueue_run(CheckRun.Trigger.MANUAL)
        return envelope_response(CheckRunSerializer(run).data, status_code=status.HTTP_202_ACCEPTED)
