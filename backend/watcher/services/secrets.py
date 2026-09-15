"""API keys stored outside the database: a JSON file in the data directory.

Environment variables win over the file, so CI or a shell can inject keys.
Values are never logged nor returned by the API; callers only learn whether a
secret is configured.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

GEMINI_API_KEY = "gemini_api_key"
GITHUB_TOKEN = "github_token"

ENV_VARS: dict[str, str] = {
    GEMINI_API_KEY: "GEMINI_API_KEY",
    GITHUB_TOKEN: "GITHUB_TOKEN",
}


def _path() -> Path:
    return Path(settings.SECRETS_FILE)


def _read_file() -> dict[str, str]:
    path = _path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Secrets file at %s is unreadable, ignoring it", path)
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items() if isinstance(value, str)}


def get_secret(name: str) -> str:
    """The secret value, from the environment first and then the file ("" when unset)."""
    env_value = os.environ.get(ENV_VARS.get(name, ""), "").strip()
    if env_value:
        return env_value
    return _read_file().get(name, "").strip()


def is_configured(name: str) -> bool:
    return bool(get_secret(name))


def set_secrets(values: dict[str, str]) -> None:
    """Store or remove secrets in the file. An empty string removes that secret."""
    current = _read_file()
    for name, value in values.items():
        if name not in ENV_VARS:
            raise ValueError(f"Unknown secret {name!r}")
        cleaned = value.strip()
        if cleaned:
            current[name] = cleaned
        else:
            current.pop(name, None)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=2), encoding="utf-8")
    # Best effort: some filesystems ignore POSIX modes.
    with contextlib.suppress(OSError):
        temporary.chmod(0o600)
    temporary.replace(path)
