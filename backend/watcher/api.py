"""API plumbing: request ids, the response envelope, errors and CSRF."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from typing import Any

from django.http import Http404, HttpRequest, HttpResponse
from rest_framework import exceptions, status
from rest_framework.authentication import BaseAuthentication, CSRFCheck
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class RequestIdMiddleware:
    """Attach a request id to every request and echo it in ``X-Request-ID``."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _REQUEST_ID_PATTERN.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id  # type: ignore[attr-defined]
        response = self.get_response(request)
        response[REQUEST_ID_HEADER] = request_id
        return response


def request_id_of(request: Any) -> str | None:
    return getattr(request, "request_id", None)


class ApiError(exceptions.APIException):
    """API error with an explicit machine readable code and optional details."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(detail=message, code=code)
        self.status_code = status_code
        self.error_code = code
        self.message = message
        self.details = details or []


def validation_error(field: str, issue: str) -> ApiError:
    return ApiError(
        status.HTTP_400_BAD_REQUEST,
        "VALIDATION_ERROR",
        "Invalid request",
        [{"field": field, "issue": issue}],
    )


class CsrfFailed(exceptions.PermissionDenied):
    pass


class CsrfEnforcedAuthentication(BaseAuthentication):
    """No user authentication, but unsafe methods must pass Django's CSRF check."""

    def authenticate(self, request: Request) -> None:
        def dummy_get_response(_: HttpRequest) -> None:  # pragma: no cover
            return None

        check = CSRFCheck(dummy_get_response)
        check.process_request(request._request)
        reason = check.process_view(request._request, None, (), {})
        if reason:
            raise CsrfFailed(f"CSRF failed: {reason}")
        return None


class EnvelopeRenderer(JSONRenderer):
    """Wrap every payload in ``{ data, error, meta }``."""

    def render(
        self,
        data: Any,
        accepted_media_type: str | None = None,
        renderer_context: dict[str, Any] | None = None,
    ) -> bytes:
        context = renderer_context or {}
        response: Response | None = context.get("response")
        if response is None:
            return super().render(data, accepted_media_type, renderer_context)
        if response.status_code == status.HTTP_204_NO_CONTENT:
            return b""
        meta: dict[str, Any] = {"requestId": request_id_of(context.get("request"))}
        if getattr(response, "is_error", False):
            payload: dict[str, Any] = {"data": None, "error": data, "meta": meta}
        else:
            meta.update(getattr(response, "meta", None) or {})
            payload = {"data": data, "error": None, "meta": meta}
        return super().render(payload, accepted_media_type, renderer_context)


def envelope_response(
    data: Any, *, status_code: int = status.HTTP_200_OK, meta: dict[str, Any] | None = None
) -> Response:
    response = Response(data, status=status_code)
    response.meta = meta or {}  # type: ignore[attr-defined]
    return response


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    response = Response(
        {"code": code, "message": message, "details": details or []},
        status=status_code,
        headers=headers,
    )
    response.is_error = True  # type: ignore[attr-defined]
    return response


def _flatten_validation(detail: Any, prefix: str = "") -> list[dict[str, str]]:
    if isinstance(detail, dict):
        items: list[dict[str, str]] = []
        for key, value in detail.items():
            field = f"{prefix}.{key}" if prefix else str(key)
            items.extend(_flatten_validation(value, field))
        return items
    if isinstance(detail, list):
        items = []
        for value in detail:
            items.extend(_flatten_validation(value, prefix))
        return items
    return [{"field": prefix or "non_field_errors", "issue": str(detail)}]


def envelope_exception_handler(exc: Exception, context: dict[str, Any]) -> Response:
    """Translate every exception raised in an API view into the error envelope."""
    # Imported lazily: rest_framework.views loads this module through api_settings.
    from rest_framework.views import set_rollback

    set_rollback()
    if isinstance(exc, ApiError):
        return _error_response(exc.status_code, exc.error_code, exc.message, exc.details)
    if isinstance(exc, CsrfFailed):
        return _error_response(
            status.HTTP_403_FORBIDDEN, "CSRF_FAILED", "CSRF token missing or incorrect"
        )
    if isinstance(exc, Http404 | exceptions.NotFound):
        return _error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Resource not found")
    if isinstance(exc, exceptions.ValidationError):
        return _error_response(
            status.HTTP_400_BAD_REQUEST,
            "VALIDATION_ERROR",
            "Invalid request",
            _flatten_validation(exc.detail),
        )
    if isinstance(exc, exceptions.ParseError):
        return _error_response(
            status.HTTP_400_BAD_REQUEST,
            "VALIDATION_ERROR",
            "Malformed request body",
            [{"field": "body", "issue": str(exc.detail)}],
        )
    if isinstance(exc, exceptions.MethodNotAllowed):
        return _error_response(exc.status_code, "METHOD_NOT_ALLOWED", str(exc.detail))
    if isinstance(exc, exceptions.UnsupportedMediaType):
        return _error_response(exc.status_code, "UNSUPPORTED_MEDIA_TYPE", str(exc.detail))
    if isinstance(exc, exceptions.PermissionDenied):
        return _error_response(exc.status_code, "FORBIDDEN", str(exc.detail))
    if isinstance(exc, exceptions.APIException):
        return _error_response(exc.status_code, "ERROR", str(exc.detail))

    request = context.get("request")
    logger.exception("Unhandled API error (request %s)", request_id_of(request), exc_info=exc)
    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Internal server error"
    )
