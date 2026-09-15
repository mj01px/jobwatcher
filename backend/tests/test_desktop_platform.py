"""Tests for the desktop cross-platform layer (``desktop/platform_support.py``).

The module depends only on the standard library, so these tests run inside the
backend suite without the pywebview/pystray GUI stack installed. GUI- and
OS-bound methods (``set_process_identity``, ``start_tray``, Windows ctypes
dialogs) are exercised on their own platform, not here.
"""

from __future__ import annotations

import plistlib
import socket
import sys
from pathlib import Path

import pytest

DESKTOP = Path(__file__).resolve().parents[2] / "desktop"
sys.path.insert(0, str(DESKTOP))

import platform_support as ps  # noqa: E402


@pytest.fixture
def context(tmp_path: Path) -> ps.LaunchContext:
    return ps.LaunchContext(
        desktop_dir=tmp_path / "desktop",
        python_executable=tmp_path / "venv" / "bin" / "python",
        windows_exe=tmp_path / "desktop" / "JobWatcher.exe",
    )


@pytest.mark.parametrize(
    "platform_name,expected",
    [("win32", ps.WindowsPlatform), ("darwin", ps.MacPlatform), ("linux", ps.LinuxPlatform)],
)
def test_current_selects_platform_for_host(
    monkeypatch: pytest.MonkeyPatch, platform_name: str, expected: type[ps.Platform]
) -> None:
    monkeypatch.setattr(ps.sys, "platform", platform_name)
    assert isinstance(ps.current(), expected)


def test_launch_context_app_script(context: ps.LaunchContext) -> None:
    assert context.app_script == context.desktop_dir / "app.py"


def test_mac_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert ps.MacPlatform().data_dir == tmp_path / "Library" / "Application Support" / "JobWatcher"


def test_windows_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    assert ps.WindowsPlatform().data_dir == tmp_path / "AppData" / "Local" / "JobWatcher"


def test_linux_data_dir_uses_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    assert ps.LinuxPlatform().data_dir == tmp_path / "share" / "JobWatcher"


def test_vite_command_uses_platform_binary(tmp_path: Path) -> None:
    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "vite").touch()
    (bin_dir / "vite.cmd").touch()

    assert ps.MacPlatform().vite_command(tmp_path) == [str(bin_dir / "vite"), "build"]
    assert ps.WindowsPlatform().vite_command(tmp_path) == [str(bin_dir / "vite.cmd"), "build"]


def test_vite_command_missing_dependencies_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Frontend dependencies are missing"):
        ps.MacPlatform().vite_command(tmp_path)


def test_subprocess_flags_default_is_zero() -> None:
    assert ps.MacPlatform().subprocess_flags() == 0
    assert ps.LinuxPlatform().subprocess_flags() == 0


def test_osa_quote_escapes_quotes_and_backslashes() -> None:
    assert ps._osa_quote('a "b" \\ c') == '"a \\"b\\" \\\\ c"'


def test_mac_autostart_writes_and_removes_plist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, context: ps.LaunchContext
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(ps.subprocess, "run", lambda *a, **k: None)
    platform = ps.MacPlatform()
    plist_path = tmp_path / "Library" / "LaunchAgents" / "com.jobwatcher.desktop.plist"

    assert not platform.autostart_enabled()

    platform.set_autostart(True, context)
    assert platform.autostart_enabled()
    with plist_path.open("rb") as handle:
        agent = plistlib.load(handle)
    assert agent["Label"] == "com.jobwatcher.desktop"
    assert agent["RunAtLoad"] is True
    assert agent["ProgramArguments"] == [
        str(context.python_executable),
        str(context.app_script),
        "--background",
    ]

    platform.set_autostart(False, context)
    assert not platform.autostart_enabled()
    assert not plist_path.exists()


def test_linux_autostart_writes_desktop_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, context: ps.LaunchContext
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    platform = ps.LinuxPlatform()
    entry = tmp_path / "config" / "autostart" / "com.jobwatcher.desktop.desktop"

    platform.set_autostart(True, context)
    body = entry.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in body
    assert f"Exec={context.python_executable} {context.app_script} --background" in body

    platform.set_autostart(False, context)
    assert not entry.exists()


def test_mac_send_notification_invokes_osascript(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(ps.subprocess, "run", lambda cmd, **k: calls.append(cmd))

    ps.MacPlatform().send_notification(None, "5 vagas novas", "Job Watcher")

    assert len(calls) == 1
    assert calls[0][0] == "osascript"
    assert "display notification" in calls[0][-1]


def test_base_reserve_port_rejects_second_binder() -> None:
    platform = ps.LinuxPlatform()  # uses the base POSIX bind
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    first = platform.reserve_port("127.0.0.1", port)
    try:
        with pytest.raises(OSError):
            platform.reserve_port("127.0.0.1", port)
    finally:
        first.close()
