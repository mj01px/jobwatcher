"""Django settings for Job Watcher.

Every environment specific value comes from environment variables, so the same
code runs in development and in the desktop app.
"""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """Load ``KEY=value`` lines into the environment without overriding real variables."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required when DJANGO_DEBUG is off")
    SECRET_KEY = "dev-only-insecure-job-watcher-key"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173" if DEBUG else "",
)

APP_NAME = "Job Watcher"
DATA_DIR = Path(os.getenv("JOB_WATCHER_DATA_DIR", str(BASE_DIR / "data")))
JOB_WATCHER_TIMEZONE = os.getenv("JOB_WATCHER_TIMEZONE", "America/Sao_Paulo")
FRONTEND_DIST = Path(
    os.getenv("JOB_WATCHER_FRONTEND_DIST", str(BASE_DIR.parent / "frontend" / "dist"))
)
# API keys (Gemini, GitHub) live in this file or in env vars, never in the database.
SECRETS_FILE = Path(os.getenv("JOB_WATCHER_SECRETS_FILE", str(DATA_DIR / "secrets.json")))
# Cross-machine sync folder (a cloud-synced directory such as Google Drive). When
# unset, watcher.services.sync auto-detects Google Drive; empty disables sync.
SYNC_DIR = os.getenv("JOB_WATCHER_SYNC_DIR")
# Base URL of the Gupy portal. The collector reads its Next.js build id and the
# per-term data route from here. If the portal ever moves, override it.
GUPY_API = os.getenv("GUPY_API", "https://portal.gupy.io")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")

# OpenRouter: one API key reaches many models, most with a free tier. It is the
# primary AI provider; Gemini stays as a fallback. The endpoint is OpenAI
# compatible, so we call it with plain httpx (already a dependency).
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# Ordered fallback list. Free model IDs (ending in :free) rotate and get rate
# limited at peak, which is exactly why we keep several: OpenRouter tries the next
# when one is unavailable. Override in Settings or here; check the current free
# lineup at openrouter.ai/models (filter supported_parameters=structured_outputs).
# At most 3: OpenRouter rejects a longer models array (see openrouter.MAX_MODELS).
# Tried in order; the first that answers with valid JSON wins. All free (:free).
# north-mini-code leads because, measured 2026-10-03 on the resume generator (a
# ~3.5 KB JSON that the other free models truncate or break), it was the one that
# returned valid JSON, and fast (~23s); the others stay as fallbacks. Free models
# rotate and 404 when demoted (deepseek-v4-flash-0731:free did), so if one fails
# pick a current one from openrouter.ai/models (filter the :free, JSON-capable
# lineup) or set OPENROUTER_MODELS / Settings.
OPENROUTER_MODELS = env_list(
    "OPENROUTER_MODELS",
    "cohere/north-mini-code:free,"
    "nvidia/nemotron-3-super-120b-a12b:free,"
    "google/gemma-4-31b-it:free",
)

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "rest_framework",
    "watcher",
    "pipeline",
]

MIDDLEWARE = [
    "watcher.api.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES: list[dict[str, object]] = []

DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("JOB_WATCHER_DATABASE", str(DATA_DIR / "job-watcher.sqlite3")),
        "OPTIONS": {
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;",
            "timeout": 30,
            "transaction_mode": "IMMEDIATE",
        },
        # A file based test database behaves like production when the worker
        # code touches SQLite from a second thread.
        "TEST": {"NAME": str(DATA_DIR / "test-job-watcher.sqlite3")},
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "/static/"

# WhiteNoise serves the built SPA (index.html excluded, Django renders it).
WHITENOISE_ROOT = str(FRONTEND_DIST) if FRONTEND_DIST.is_dir() else None
WHITENOISE_USE_FINDERS = False
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_IMMUTABLE_FILE_TEST = r"^/assets/.+[.-][0-9A-Za-z_-]{8,}\.\w+$"

CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_HTTPONLY = False
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["watcher.api.EnvelopeRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["watcher.api.CsrfEnforcedAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "EXCEPTION_HANDLER": "watcher.api.envelope_exception_handler",
    "UNAUTHENTICATED_USER": None,
    "UNAUTHENTICATED_TOKEN": None,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
        # The desktop app logs to stderr, which is not captured anywhere. A rotating
        # file in the data dir keeps the last errors for diagnosis.
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(DATA_DIR / "jobwatcher.log"),
            "maxBytes": 1_000_000,
            "backupCount": 2,
            "formatter": "plain",
            "encoding": "utf-8",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": os.getenv("JOB_WATCHER_LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "apscheduler": {"level": "WARNING"},
        "httpx": {"level": "WARNING"},
        "google_genai": {"level": "WARNING"},
    },
}
