"""Hard wall clock ceiling for a blocking provider call."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


def call_with_deadline(call: Callable[[], Any], timeout: float) -> Any:
    """Run ``call`` and give up after ``timeout`` seconds of wall clock.

    Client timeouts do not bound a whole call: the Gemini SDK held a 503 past two
    minutes, and httpx's timeout is per read, so a slow free model streaming its
    answer ran 38s against a 25s setting. The ceiling is enforced here. The
    worker is a daemon thread: an abandoned call finishes on its own, its result
    is discarded, and it never holds the app open on exit.

    Raises:
        TimeoutError: when ``call`` has not returned within ``timeout``.
    """
    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["value"] = call()
        except Exception as error:  # noqa: BLE001 - re-raised in the caller's thread
            outcome["error"] = error

    worker = threading.Thread(target=run, name="ai-call", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError(f"AI call exceeded {timeout:.0f}s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]
