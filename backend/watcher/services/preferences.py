"""Small typed accessors over the settings table."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings as django_settings
from django.utils import timezone

from watcher.constants import (
    DEFAULT_PITCH_MAX_CHARS,
    DOSSIER_KEY,
    GEMINI_MODEL_KEY,
    NOTIFICATIONS_ENABLED_KEY,
    OVERDUE_NOTICE_LAST_ON_KEY,
    PITCH_MAX_CHARS_KEY,
)
from watcher.models import Setting
from watcher.services.secrets import GEMINI_API_KEY, GITHUB_TOKEN, is_configured


def get_setting(key: str, default: Any = None) -> Any:
    row = Setting.objects.filter(key=key).first()
    return default if row is None else row.value


def set_setting(key: str, value: Any) -> None:
    Setting.objects.update_or_create(
        key=key, defaults={"value": value, "updated_at": timezone.now()}
    )


def get_dossier() -> str:
    value = get_setting(DOSSIER_KEY, "")
    return value if isinstance(value, str) else ""


def get_pitch_max_chars() -> int:
    value = get_setting(PITCH_MAX_CHARS_KEY, DEFAULT_PITCH_MAX_CHARS)
    return (
        value if isinstance(value, int) and not isinstance(value, bool) else DEFAULT_PITCH_MAX_CHARS
    )


def get_gemini_model() -> str:
    value = get_setting(GEMINI_MODEL_KEY, "")
    return (
        value.strip() if isinstance(value, str) and value.strip() else django_settings.GEMINI_MODEL
    )


def notifications_enabled() -> bool:
    value = get_setting(NOTIFICATIONS_ENABLED_KEY, True)
    return value if isinstance(value, bool) else True


def set_notifications_enabled(enabled: bool) -> None:
    set_setting(NOTIFICATIONS_ENABLED_KEY, bool(enabled))


def overdue_notice_last_on() -> date | None:
    """Local date of the last overdue follow up notification, if any."""
    value = get_setting(OVERDUE_NOTICE_LAST_ON_KEY)
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def set_overdue_notice_last_on(day: date) -> None:
    set_setting(OVERDUE_NOTICE_LAST_ON_KEY, day.isoformat())


def profile_payload() -> dict[str, Any]:
    return {
        "dossier": get_dossier(),
        "pitchMaxChars": get_pitch_max_chars(),
        "geminiModel": get_gemini_model(),
        "geminiConfigured": is_configured(GEMINI_API_KEY),
        "githubConfigured": is_configured(GITHUB_TOKEN),
    }


def secrets_payload() -> dict[str, bool]:
    return {
        "geminiConfigured": is_configured(GEMINI_API_KEY),
        "githubConfigured": is_configured(GITHUB_TOKEN),
    }
