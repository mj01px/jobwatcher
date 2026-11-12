"""Save a file the frontend produced (the tailored resume PDF) to disk.

WKWebView (macOS) ignores ``<a download>`` on a blob URL and renders the PDF in
the main window instead, with no way back to the dashboard. In the desktop app the
frontend hands the bytes to ``window.pywebview.api.save_file`` and we show the
native "Save as" dialog here.
"""

from __future__ import annotations

import base64
import binascii
import logging
from pathlib import Path
from typing import Any

import webview

logger = logging.getLogger("watcher.desktop")

# A tailored resume is a few hundred KB; anything near this is not one.
MAX_BYTES = 20 * 1024 * 1024
DEFAULT_NAME = "curriculo.pdf"


def _safe_name(raw: Any) -> str:
    """The suggested file name, reduced to a bare name (no directories)."""
    if not isinstance(raw, str):
        return DEFAULT_NAME
    name = Path(raw.replace("\\", "/")).name.strip()
    return name[:120] if name and name not in {".", ".."} else DEFAULT_NAME


def _decode(raw: Any) -> bytes | None:
    if not isinstance(raw, str) or len(raw) > MAX_BYTES * 4 // 3 + 4:
        return None
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return None


def _chosen_path(result: Any) -> Path | None:
    # Cocoa returns the path as a string, WinForms as a one-item tuple.
    if isinstance(result, (tuple, list)):
        result = result[0] if result else None
    return Path(result) if isinstance(result, str) and result else None


def save_file(window: Any, filename: Any, data_base64: Any) -> dict[str, Any]:
    """Ask where to save ``data_base64`` (base64 bytes) and write it there.

    Returns ``{"ok": True, "path": ...}`` when saved, ``{"ok": False, "cancelled":
    True}`` when the user closes the dialog, and ``{"ok": False, "error": ...}``
    on bad input or a failed write.
    """
    data = _decode(data_base64)
    if data is None:
        return {"ok": False, "error": "invalid_data"}

    result = window.create_file_dialog(webview.FileDialog.SAVE, save_filename=_safe_name(filename))
    path = _chosen_path(result)
    if path is None:
        return {"ok": False, "cancelled": True}

    try:
        path.write_bytes(data)
    except OSError:
        logger.exception("Could not save the file")
        return {"ok": False, "error": "write_failed"}
    return {"ok": True, "path": str(path)}
