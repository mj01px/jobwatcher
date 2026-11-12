"""Tests for the native "Save as" bridge (``desktop/downloads.py``)."""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import Any

import pytest

webview = pytest.importorskip("webview")

DESKTOP = Path(__file__).resolve().parents[2] / "desktop"
sys.path.insert(0, str(DESKTOP))

import downloads  # noqa: E402

PDF = b"%PDF-1.4 fake"


class FakeWindow:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[tuple[Any, str]] = []

    def create_file_dialog(self, dialog_type: Any, save_filename: str = "") -> Any:
        self.calls.append((dialog_type, save_filename))
        return self.result


def encoded(data: bytes = PDF) -> str:
    return base64.b64encode(data).decode()


@pytest.mark.parametrize("as_tuple", [False, True])
def test_writes_the_file_where_the_user_chose(tmp_path: Path, as_tuple: bool) -> None:
    target = str(tmp_path / "cv.pdf")
    window = FakeWindow((target,) if as_tuple else target)

    assert downloads.save_file(window, "cv.pdf", encoded()) == {"ok": True, "path": target}
    assert Path(target).read_bytes() == PDF
    assert window.calls == [(webview.FileDialog.SAVE, "cv.pdf")]


def test_cancelled_dialog_writes_nothing() -> None:
    assert downloads.save_file(FakeWindow(None), "cv.pdf", encoded()) == {
        "ok": False,
        "cancelled": True,
    }


@pytest.mark.parametrize("data", ["not base64!", 123, None])
def test_rejects_bad_data_before_opening_the_dialog(data: Any) -> None:
    window = FakeWindow("/tmp/never.pdf")
    assert downloads.save_file(window, "cv.pdf", data) == {"ok": False, "error": "invalid_data"}
    assert window.calls == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\cv.pdf", "cv.pdf"),
        ("", "curriculo.pdf"),
        ("..", "curriculo.pdf"),
        (None, "curriculo.pdf"),
    ],
)
def test_suggested_name_is_a_bare_file_name(raw: Any, expected: str) -> None:
    window = FakeWindow(None)
    downloads.save_file(window, raw, encoded())
    assert window.calls[0][1] == expected


def test_reports_a_failed_write(tmp_path: Path) -> None:
    window = FakeWindow(str(tmp_path / "missing-dir" / "cv.pdf"))
    assert downloads.save_file(window, "cv.pdf", encoded()) == {
        "ok": False,
        "error": "write_failed",
    }
