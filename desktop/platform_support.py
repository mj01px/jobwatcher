"""Cross-platform desktop integration for Job Watcher.

The tray app needs a handful of things the operating system provides
differently on each platform: where its data lives, how a single instance
reserves its port, how it starts with the session, how it shows a native
error and a notification, and how the tray icon joins the GUI loop. This
module hides every one of those behind a single :class:`Platform` interface.

``current()`` returns the implementation for the host: :class:`WindowsPlatform`
(the original target, behaviour unchanged), :class:`MacPlatform` or
:class:`LinuxPlatform`. Only the standard library is imported here, so the
module can be unit tested without the desktop GUI dependencies installed.
"""

from __future__ import annotations

import logging
import os
import plistlib
import socket
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("watcher.desktop")

APP_NAME = "JobWatcher"
APP_DISPLAY_NAME = "Job Watcher"
BUNDLE_ID = "com.jobwatcher.desktop"


@dataclass(frozen=True)
class LaunchContext:
    """Everything a platform needs to launch the app in the background.

    Attributes:
        desktop_dir: The ``desktop/`` directory that holds ``app.py``.
        python_executable: The interpreter that should run ``app.py``.
        windows_exe: The compiled ``JobWatcher.exe`` (Windows autostart only).
    """

    desktop_dir: Path
    python_executable: Path
    windows_exe: Path

    @property
    def app_script(self) -> Path:
        """Path to ``desktop/app.py``."""
        return self.desktop_dir / "app.py"


class Platform:
    """Cross-platform defaults, overridden per operating system."""

    name = "generic"
    autostart_menu_label = "Iniciar com o sistema"

    # -- storage --------------------------------------------------------
    @property
    def data_dir(self) -> Path:
        """Directory for the database, secret key, session log and webview data."""
        return Path.home() / f".{APP_NAME.lower()}"

    # -- process identity ----------------------------------------------
    def set_process_identity(self) -> None:
        """Give the app its own identity in the OS switcher. Best effort, never raises."""

    # -- single instance -----------------------------------------------
    def reserve_port(self, host: str, port: int) -> socket.socket:
        """Bind ``port`` exclusively so a second launch fails.

        On POSIX a plain bind already refuses a second binder while the socket
        is open, which is exactly the single-instance signal the app relies on.

        Raises:
            OSError: The port is already taken.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((host, port))
        except OSError:
            sock.close()
            raise
        return sock

    # -- frontend build ------------------------------------------------
    def vite_command(self, frontend: Path) -> list[str]:
        """Command that runs ``vite build`` from the local install.

        Raises:
            RuntimeError: The frontend dependencies were never installed.
        """
        vite = frontend / "node_modules" / ".bin" / "vite"
        if not vite.exists():
            raise RuntimeError(
                "Frontend dependencies are missing. Run: cd frontend && corepack pnpm install"
            )
        return [str(vite), "build"]

    def subprocess_flags(self) -> int:
        """Extra ``creationflags`` for spawned processes (Windows hides consoles)."""
        return 0

    # -- autostart ------------------------------------------------------
    def autostart_supported(self) -> bool:
        """Whether "start with the session" can be toggled from the tray."""
        return False

    def autostart_enabled(self) -> bool:
        return False

    def set_autostart(self, enabled: bool, context: LaunchContext) -> None:
        logger.info("Autostart is not supported on %s", self.name)

    # -- tray -----------------------------------------------------------
    def start_tray(
        self, make_icon: Callable[[], Any], on_ready: Callable[[Any], None]
    ) -> None:
        """Build the pystray icon with ``make_icon`` and run it alongside the app.

        ``on_ready`` receives the icon so the app can stop it later. On Windows
        and Linux the icon owns its own thread; macOS overrides this because
        AppKit objects must be created on the main thread (see
        :class:`MacPlatform`).
        """
        icon = make_icon()
        on_ready(icon)
        threading.Thread(target=icon.run, daemon=True, name="tray").start()

    # -- shutdown -------------------------------------------------------
    def terminate(self) -> None:
        """Force the process to exit after the tray asked to quit.

        Windows and Linux let ``window.destroy()`` unwind the GUI loop and then
        exit from ``main()``; macOS overrides this (see :class:`MacPlatform`).
        """

    # -- user feedback --------------------------------------------------
    def show_error(self, title: str, message: str) -> None:
        """Show a blocking, native error to the user."""
        print(f"{title}: {message}", file=sys.stderr)

    def send_notification(self, tray: Any, message: str, title: str) -> None:
        """Show a desktop notification. Never raises."""
        if tray is None:
            return
        try:
            tray.notify(message, title)
        except Exception:
            logger.exception("Could not show a notification")


class WindowsPlatform(Platform):
    """The original target: Edge WebView2, tray balloons, Startup shortcut."""

    name = "windows"
    autostart_menu_label = "Iniciar com o Windows"

    @property
    def data_dir(self) -> Path:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / APP_NAME

    def _startup_link(self) -> Path:
        base = os.environ.get("APPDATA") or str(Path.home())
        return (
            Path(base)
            / "Microsoft/Windows/Start Menu/Programs/Startup"
            / f"{APP_DISPLAY_NAME}.lnk"
        )

    def set_process_identity(self) -> None:
        # Own AppUserModelID: otherwise the taskbar groups the window under Python.
        import ctypes

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JobWatcher.Desktop")
        except Exception:
            logger.exception("Could not set the AppUserModelID")

    def reserve_port(self, host: str, port: int) -> socket.socket:
        # waitress enables SO_REUSEADDR, which on Windows lets a second process
        # bind the same port and steal requests. An exclusive bind makes the
        # second launch fail instead, which is how it detects a running instance.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((host, port))
        except OSError:
            sock.close()
            raise
        return sock

    def vite_command(self, frontend: Path) -> list[str]:
        vite = frontend / "node_modules" / ".bin" / "vite.cmd"
        if not vite.exists():
            raise RuntimeError(
                "Frontend dependencies are missing. Run: cd frontend && corepack pnpm install"
            )
        return [str(vite), "build"]

    def subprocess_flags(self) -> int:
        return subprocess.CREATE_NO_WINDOW

    def autostart_supported(self) -> bool:
        return True

    def autostart_enabled(self) -> bool:
        return self._startup_link().exists()

    def set_autostart(self, enabled: bool, context: LaunchContext) -> None:
        """Create or remove the Startup folder shortcut that launches hidden."""
        link = self._startup_link()
        if not enabled:
            link.unlink(missing_ok=True)
            return
        if not context.windows_exe.exists():
            logger.warning(
                "Cannot enable start with Windows: %s was not built", context.windows_exe
            )
            return
        script = (
            "$s = New-Object -ComObject WScript.Shell; "
            f"$l = $s.CreateShortcut('{link}'); "
            f"$l.TargetPath = '{context.windows_exe}'; $l.Arguments = '--background'; "
            f"$l.WorkingDirectory = '{context.desktop_dir}'; "
            f"$l.IconLocation = '{context.windows_exe},0'; "
            "$l.Description = 'Job Watcher'; $l.Save()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            creationflags=self.subprocess_flags(),
            check=False,
        )

    def show_error(self, title: str, message: str) -> None:
        import ctypes

        try:
            ctypes.windll.user32.MessageBoxW(None, message, title, 0x30)  # MB_ICONWARNING
        except Exception:
            super().show_error(title, message)


class MacPlatform(Platform):
    """macOS: WKWebView (via pywebview), osascript feedback, LaunchAgent autostart."""

    name = "macos"
    autostart_menu_label = "Abrir ao iniciar o Mac"

    @property
    def data_dir(self) -> Path:
        return Path.home() / "Library" / "Application Support" / APP_NAME

    def _agent_plist(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{BUNDLE_ID}.plist"

    def start_tray(
        self, make_icon: Callable[[], Any], on_ready: Callable[[Any], None]
    ) -> None:
        # The status-bar item is an NSWindow, which AppKit only lets us create
        # on the main thread. The app runs boot() on a worker thread, so hop
        # onto pywebview's already-running main loop to build it there, then
        # run_detached() attaches it instead of starting a second loop.
        from PyObjCTools import AppHelper

        def build() -> None:
            try:
                icon = make_icon()
                on_ready(icon)
                # pystray's default setup flips `visible` from a worker thread,
                # which touches AppKit off the main thread and renders a glitched,
                # oversized item. Pass a no-op setup and show it here, on the main
                # thread, so the status item is sized to the menu bar correctly.
                icon.run_detached(setup=lambda _icon: None)
                icon.visible = True
            except Exception:
                logger.exception("Could not start the menu-bar icon")

        AppHelper.callAfter(build)

    def autostart_supported(self) -> bool:
        return True

    def autostart_enabled(self) -> bool:
        return self._agent_plist().exists()

    def set_autostart(self, enabled: bool, context: LaunchContext) -> None:
        """Write or remove a LaunchAgent that opens the app hidden at login."""
        plist = self._agent_plist()
        if not enabled:
            if plist.exists():
                subprocess.run(
                    ["launchctl", "unload", str(plist)], check=False, capture_output=True
                )
                plist.unlink(missing_ok=True)
            return
        plist.parent.mkdir(parents=True, exist_ok=True)
        agent = {
            "Label": BUNDLE_ID,
            "ProgramArguments": [
                str(context.python_executable),
                str(context.app_script),
                "--background",
            ],
            "WorkingDirectory": str(context.desktop_dir.parent / "backend"),
            "RunAtLoad": True,
            "ProcessType": "Interactive",
        }
        with plist.open("wb") as handle:
            plistlib.dump(agent, handle)
        # Reload so the change takes effect without a logout.
        subprocess.run(["launchctl", "unload", str(plist)], check=False, capture_output=True)
        subprocess.run(["launchctl", "load", str(plist)], check=False, capture_output=True)

    def terminate(self) -> None:
        # pywebview keeps the NSApplication loop alive even after the window is
        # destroyed (the status item is still attached), so main() would never
        # get to exit. As an LSUIElement app there is no Dock or Force Quit
        # entry either, so a stuck process is unclosable: exit hard here.
        sys.stdout.flush()
        os._exit(0)

    def show_error(self, title: str, message: str) -> None:
        script = (
            f"display dialog {_osa_quote(message)} with title {_osa_quote(title)} "
            'buttons {"OK"} default button "OK" with icon caution'
        )
        try:
            subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
        except Exception:
            super().show_error(title, message)

    def send_notification(self, tray: Any, message: str, title: str) -> None:
        # The tray backend on macOS uses a deprecated notification API; osascript
        # is more reliable and does not need the icon to be visible yet.
        script = f"display notification {_osa_quote(message)} with title {_osa_quote(title)}"
        try:
            subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
        except Exception:
            logger.exception("Could not show a notification")


class LinuxPlatform(Platform):
    """Linux: XDG data directory and a freedesktop autostart entry."""

    name = "linux"
    autostart_menu_label = "Iniciar com a sessão"

    @property
    def data_dir(self) -> Path:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        return Path(base) / APP_NAME

    def _autostart_entry(self) -> Path:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        return Path(base) / "autostart" / f"{BUNDLE_ID}.desktop"

    def autostart_supported(self) -> bool:
        return True

    def autostart_enabled(self) -> bool:
        return self._autostart_entry().exists()

    def set_autostart(self, enabled: bool, context: LaunchContext) -> None:
        entry = self._autostart_entry()
        if not enabled:
            entry.unlink(missing_ok=True)
            return
        entry.parent.mkdir(parents=True, exist_ok=True)
        exec_line = (
            f"{context.python_executable} {context.app_script} --background"
        )
        entry.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_DISPLAY_NAME}\n"
            f"Exec={exec_line}\n"
            "X-GNOME-Autostart-enabled=true\n"
            "Terminal=false\n",
            encoding="utf-8",
        )


def _osa_quote(text: str) -> str:
    """Quote a string as an AppleScript string literal."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def current() -> Platform:
    """Return the :class:`Platform` implementation for the host OS."""
    if sys.platform == "win32":
        return WindowsPlatform()
    if sys.platform == "darwin":
        return MacPlatform()
    return LinuxPlatform()


__all__ = [
    "APP_DISPLAY_NAME",
    "APP_NAME",
    "BUNDLE_ID",
    "LaunchContext",
    "LinuxPlatform",
    "MacPlatform",
    "Platform",
    "WindowsPlatform",
    "current",
]
