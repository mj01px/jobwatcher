"""Settings for the test suite, independent of any local ``.env`` file."""

from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-insecure-job-watcher-key")

from config.settings import *  # noqa: F403
