"""Job Watcher desktop app: API, dashboard and check worker in one tray app.

Serves Django (API and the built SPA) with waitress on 127.0.0.1:17843, runs the
check worker on a thread and shows the dashboard in a native pywebview window
(Edge WebView2 on Windows, WKWebView on macOS). Closing the window only hides it:
the monitor keeps running from the tray icon until "Sair", so the 09/12/15/18
checks happen.

Everything platform specific — the data directory, the single-instance port lock,
autostart, notifications and native dialogs — lives in ``platform_support``.
Windows remains the default target; macOS and Linux are supported side by side.

Data lives in the platform data directory (see ``platform_support``): on Windows
``%LOCALAPPDATA%\\JobWatcher``, on macOS ``~/Library/Application Support/JobWatcher``.
JobWatcher.exe (desktop/Launcher.cs) or JobWatcher.app opens this file; to run it
by hand with the log in the terminal:

    <venv python> desktop/app.py [--background]

``--background`` starts with the window hidden (used by the autostart entry).
"""

from __future__ import annotations

import html
import itertools
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import platform_support
import pystray
import webview
from apply_detection import ApplyDetector
from icon import ICO_PATH, draw_mark, draw_menu_bar_icon
from notifications import APP_TITLE, Notifier
from waitress import create_server

DESKTOP = Path(__file__).resolve().parent
ROOT = DESKTOP.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
DIST = (FRONTEND / "dist").resolve()
EXE = DESKTOP / "JobWatcher.exe"

HOST = "127.0.0.1"
# Fixed on purpose: localStorage (the language
# choice) is stored per origin, and the port is part of the origin.
PORT = 17843

PLATFORM = platform_support.current()
APP_DATA = PLATFORM.data_dir
LOG = APP_DATA / "job-watcher.log"

# A second launch asks the running instance to show its window through this
# route. The custom header cannot be sent cross origin without a preflight,
# so a web page cannot trigger it.
SHOW_PATH = "/__desktop__/show"
SHOW_HEADER = "X-Job-Watcher-Desktop"

WsgiApp = Callable[[dict[str, Any], Callable[..., Any]], Iterable[bytes]]

logger = logging.getLogger("watcher.desktop")


def _redirect_output() -> None:
    """Send stdout and stderr to the session log when there is no console.

    A windowless launcher (pythonw.exe on Windows, a .app bundle on macOS)
    leaves sys.stdout as None, so Django and worker logs would vanish. Must run
    before django.setup(), which binds the log handler to the sys.stderr of
    that moment. One file per session keeps it from growing.
    """
    is_pythonw = Path(sys.executable).name.lower() == "pythonw.exe"
    if sys.stdout is not None and not is_pythonw:
        return
    output = LOG.open("w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = output


def _screen(title: str, text: str = "", log: str = "") -> str:
    """Local page shown while the app starts or when it fails to."""
    paragraph = f"<p>{html.escape(text)}</p>" if text else ""
    block = f"<pre>{html.escape(log)}</pre>" if log else ""
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><style>
body {{ margin: 0; min-height: 100vh; display: grid; place-content: center;
  gap: 10px; padding: 0 24px; text-align: center; background: #f3f4f2;
  color: #244f5b; font: 15px/1.5 "Segoe UI", system-ui, sans-serif; }}
h1 {{ margin: 0; font-size: 22px; font-weight: 600; }}
h1::before {{ content: ""; display: block; width: 48px; height: 6px;
  margin: 0 auto 14px; background: #ffc33e; }}
p {{ margin: 0; color: #758b99; }}
pre {{ max-width: 80vw; max-height: 50vh; overflow: auto; text-align: left;
  font-size: 12px; color: #758b99; white-space: pre-wrap; }}
</style><h1>{html.escape(title)}</h1>{paragraph}{block}</html>"""


def _secret_key() -> str:
    """Generate the Django secret key once and keep it next to the database."""
    path = APP_DATA / "secret_key"
    if not path.is_file() or not path.read_text(encoding="utf-8").strip():
        path.write_text(secrets.token_urlsafe(50), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


def _configure_environment() -> None:
    """Production settings for the local app, independent of backend/.env."""
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
    os.environ["DJANGO_DEBUG"] = "0"
    os.environ["DJANGO_SECRET_KEY"] = _secret_key()
    os.environ["DJANGO_ALLOWED_HOSTS"] = f"{HOST},localhost"
    os.environ["JOB_WATCHER_DATA_DIR"] = str(APP_DATA / "data")
    os.environ["JOB_WATCHER_FRONTEND_DIST"] = str(DIST)


def _frontend_is_stale() -> bool:
    """Whether any frontend source changed after the last build (or no build)."""
    index = DIST / "index.html"
    if not index.exists():
        return True
    built_at = index.stat().st_mtime
    sources = itertools.chain(
        [FRONTEND / "index.html", FRONTEND / "vite.config.ts", FRONTEND / "package.json"],
        (FRONTEND / "src").rglob("*"),
    )
    return any(path.is_file() and path.stat().st_mtime > built_at for path in sources)


def _build_frontend() -> None:
    """Run vite build. When it fails and an older build exists, keep that one."""
    # Plain `vite build`, without the `tsc -b` step: a type error must not stop
    # the dashboard from opening.
    result = subprocess.run(
        PLATFORM.vite_command(FRONTEND),
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=PLATFORM.subprocess_flags(),
        check=False,
    )
    if result.returncode == 0:
        return
    output = (result.stdout + result.stderr)[-3000:]
    if (DIST / "index.html").exists():
        print(f"vite build failed, using the previous build.\n{output}", file=sys.stderr)
        return
    raise RuntimeError(f"vite build failed and there is no previous build.\n{output}")


def _django() -> WsgiApp:
    """Set up Django, apply pending migrations and return its WSGI app."""
    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)

    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application

    application = get_wsgi_application()
    # New migrations arrive with a git pull and nobody runs manage.py here.
    call_command("migrate", interactive=False, verbosity=0)
    return application


def _router(django_app: WsgiApp, on_show: Callable[[], None]) -> WsgiApp:
    """Django for everything, plus the private route a second launch uses."""
    header_key = "HTTP_" + SHOW_HEADER.upper().replace("-", "_")

    def application(environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        if environ.get("PATH_INFO") == SHOW_PATH:
            if environ.get("REQUEST_METHOD") == "POST" and environ.get(header_key) == "show":
                on_show()
                start_response("204 No Content", [])
                return []
            start_response("404 Not Found", [("Content-Type", "text/plain")])
            return [b"not found"]
        return django_app(environ, start_response)

    return application


def _show_running_instance() -> bool:
    """Ask an already running Job Watcher to show its window."""
    request = urllib.request.Request(
        f"http://{HOST}:{PORT}{SHOW_PATH}", method="POST", headers={SHOW_HEADER: "show"}
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status == 204
    except OSError:
        return False


def _launch_context() -> platform_support.LaunchContext:
    """Describe how this install should be relaunched in the background."""
    return platform_support.LaunchContext(
        desktop_dir=DESKTOP,
        python_executable=Path(sys.executable),
        windows_exe=EXE,
    )


def autostart_enabled() -> bool:
    return PLATFORM.autostart_enabled()


def set_autostart(enabled: bool) -> None:
    PLATFORM.set_autostart(enabled, _launch_context())


class Worker:
    """The run_worker command loop, on a thread instead of its own process."""

    def __init__(self, on_run_finished: Callable[[], None]) -> None:
        self._stop = threading.Event()
        self._scheduler: Any = None
        self._on_run_finished = on_run_finished

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="check-worker").start()

    def stop(self) -> None:
        self._stop.set()
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)

    def _run(self) -> None:
        from django.db import close_old_connections
        from watcher.constants import WORKER_POLL_SECONDS
        from watcher.management.commands.run_worker import (
            build_scheduler,
            prepare_worker,
            process_next_run,
        )
        from watcher.services.runs import write_worker_heartbeat

        try:
            write_worker_heartbeat()
            prepare_worker()
            self._scheduler = build_scheduler()
            self._scheduler.start()
            logger.info("Desktop worker started")
        except Exception:
            logger.exception("Desktop worker failed to start")
            return

        while not self._stop.is_set():
            close_old_connections()
            try:
                if process_next_run():
                    self._run_finished()
                    continue
            except Exception:
                logger.exception("Worker loop iteration failed")
            self._stop.wait(WORKER_POLL_SECONDS)
        close_old_connections()

    def _run_finished(self) -> None:
        try:
            self._on_run_finished()
        except Exception:
            logger.exception("After run hook failed")


class DesktopApp:
    def __init__(self, background: bool) -> None:
        self.background = background
        self.quitting = False
        self.tray: pystray.Icon | None = None
        self.notifier = Notifier(self.notify)
        self.detector = ApplyDetector(self.notify)
        self.worker = Worker(self.notifier.after_run)
        self.window = webview.create_window(
            "Job Watcher",
            html=_screen("Starting Job Watcher"),
            width=1320,
            height=860,
            min_size=(900, 600),
            hidden=background,
            # Only open_job: InHire jobs open in a window that detects the application.
            js_api=self.detector.main_window_api(),
        )
        self.detector.attach_main_window(self.window)
        self.window.events.closing += self._on_closing

    def _on_closing(self) -> bool:
        # Closing hides the window; only "Sair" in the tray stops the monitor.
        if self.quitting:
            return True
        self.window.hide()
        return False

    def show(self) -> None:
        self.window.show()
        self.window.restore()

    def notify(self, message: str, title: str = APP_TITLE) -> None:
        """Desktop notification (tray balloon on Windows, osascript on macOS)."""
        PLATFORM.send_notification(self.tray, message, title)

    def _startup_overdue_notice(self) -> None:
        # Give the tray icon time to appear; notifications need it visible.
        time.sleep(8)
        self.notifier.maybe_overdue()

    def boot(self, sock: socket.socket) -> None:
        """Build the frontend if needed, start Django, the worker and the tray."""
        try:
            if _frontend_is_stale():
                self.window.load_html(
                    _screen(
                        "Updating the interface",
                        "The frontend changed. This takes a few seconds.",
                    )
                )
                _build_frontend()
            _configure_environment()
            server = create_server(_router(_django(), self.show), sockets=[sock], threads=8)
            threading.Thread(target=server.run, daemon=True, name="waitress").start()
            self.worker.start()
            self._start_tray()
            threading.Thread(
                target=self._startup_overdue_notice, daemon=True, name="overdue-notice"
            ).start()
            self.window.load_url(f"http://{HOST}:{PORT}/")
        except Exception:
            # Thread boundary: without this the error dies silently and the
            # window stays on the loading screen forever.
            traceback.print_exc()
            self.window.load_html(
                _screen(
                    "Job Watcher could not start",
                    f"Full log at {LOG}",
                    traceback.format_exc()[-3000:],
                )
            )
            self.show()

    def _start_tray(self) -> None:
        # Brazilian Portuguese, the app default language.
        items = [
            pystray.MenuItem("Abrir Job Watcher", self._tray_open, default=True),
            pystray.MenuItem("Verificar agora", self._tray_check_now),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Notificações",
                self._tray_toggle_notifications,
                checked=lambda _item: self.notifier.enabled(),
            ),
        ]
        if PLATFORM.autostart_supported():
            items.append(
                pystray.MenuItem(
                    PLATFORM.autostart_menu_label,
                    self._tray_toggle_autostart,
                    checked=lambda _item: autostart_enabled(),
                )
            )
        items.append(pystray.MenuItem("Sair", self._tray_quit))
        menu = pystray.Menu(*items)

        # macOS scales the image to the menu bar, so it gets a padded variant;
        # the Windows notification area keeps the full-bleed mark.
        image = draw_menu_bar_icon(64) if PLATFORM.name == "macos" else draw_mark(64)

        # The icon is built through this factory so macOS can create it on the
        # main thread (AppKit requires it); see platform_support.start_tray.
        def make_icon() -> pystray.Icon:
            return pystray.Icon("job-watcher", image, "Job Watcher", menu)

        PLATFORM.start_tray(make_icon, self._set_tray)

    def _set_tray(self, icon: pystray.Icon) -> None:
        self.tray = icon

    def _tray_open(self, _icon: Any = None, _item: Any = None) -> None:
        self.show()

    def _tray_check_now(self, _icon: Any = None, _item: Any = None) -> None:
        from django.db import close_old_connections
        from watcher.models import CheckRun
        from watcher.services.runs import enqueue_run

        close_old_connections()
        try:
            enqueue_run(CheckRun.Trigger.MANUAL)
        except Exception:
            logger.exception("Could not queue a check from the tray")
        finally:
            close_old_connections()

    def _tray_toggle_autostart(self, _icon: Any = None, _item: Any = None) -> None:
        set_autostart(not autostart_enabled())

    def _tray_toggle_notifications(self, _icon: Any = None, _item: Any = None) -> None:
        self.notifier.set_enabled(not self.notifier.enabled())

    def _tray_quit(self, _icon: Any = None, _item: Any = None) -> None:
        self.quitting = True
        try:
            self.worker.stop()
            self.detector.close_all()
            if self.tray is not None:
                self.tray.stop()
            self.window.destroy()
        finally:
            # macOS won't exit on its own; on Windows/Linux this is a no-op.
            PLATFORM.terminate()


def main() -> None:
    APP_DATA.mkdir(parents=True, exist_ok=True)
    _redirect_output()
    PLATFORM.set_process_identity()
    background = "--background" in sys.argv[1:]

    try:
        sock = PLATFORM.reserve_port(HOST, PORT)
    except OSError:
        if background or _show_running_instance():
            return
        PLATFORM.show_error(
            "Job Watcher",
            f"Port {PORT} is already in use by another program.\n\nStop it and try again.",
        )
        return

    app = DesktopApp(background)
    # Persistent storage keeps localStorage (language choice) between launches.
    webview.start(
        app.boot,
        (sock,),
        private_mode=False,
        storage_path=str(APP_DATA / "webview"),
        icon=str(ICO_PATH) if ICO_PATH.exists() else None,
    )
    # Window destroyed by "Quit": exit now, even with a check still running on
    # a thread (the next start marks it as interrupted).
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
