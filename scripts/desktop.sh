#!/usr/bin/env bash
# Builds the Job Watcher desktop app on macOS (and Linux): installs the desktop
# dependencies into backend/.venv, builds the frontend and, on macOS, assembles
# desktop/JobWatcher.app so the dashboard opens without a Terminal window.
#
# Code changes do NOT require running this again: the app only opens
# desktop/app.py, which uses the backend as is and rebuilds a stale frontend.
#
# Autostart (open at login) is toggled from the tray menu, not here.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="$ROOT/backend/.venv/bin/python"

if [[ ! -x "$PY" ]]; then
    echo "Virtual environment not found at backend/.venv"
    echo "Run:  python3 -m venv backend/.venv"
    exit 1
fi
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
    echo "Frontend dependencies are not installed."
    echo "Run:  cd frontend && corepack pnpm install"
    exit 1
fi

echo "[1/4] Desktop dependencies in the venv..."
"$PY" -m pip install --disable-pip-version-check -q -r backend/requirements-desktop.txt

echo "[2/4] Icon..."
"$PY" desktop/icon.py

echo "[3/4] Frontend build..."
( cd frontend && corepack pnpm exec vite build )

if [[ "$(uname)" != "Darwin" ]]; then
    echo
    echo "Done. Start it with:  $PY desktop/app.py"
    echo "It also runs from the tray; enable 'start with the session' there."
    exit 0
fi

echo "[4/4] Building JobWatcher.app..."
APP="$ROOT/desktop/JobWatcher.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Job Watcher</string>
    <key>CFBundleDisplayName</key><string>Job Watcher</string>
    <key>CFBundleIdentifier</key><string>com.jobwatcher.desktop</string>
    <key>CFBundleExecutable</key><string>jobwatcher</string>
    <key>CFBundleIconFile</key><string>job-watcher.icns</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>LSMinimumSystemVersion</key><string>11.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <!-- Menu-bar app: no Dock icon, the tray icon is the entry point. -->
    <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

# The launcher runs the venv Python on app.py. The repo path is baked in, like
# the Windows shortcut: rerun this script if the project ever moves.
cat > "$APP/Contents/MacOS/jobwatcher" <<LAUNCHER
#!/bin/bash
exec "$PY" "$ROOT/desktop/app.py" "\$@"
LAUNCHER
chmod +x "$APP/Contents/MacOS/jobwatcher"

# Best-effort .icns from the drawn mark; the app still runs without it.
if command -v iconutil >/dev/null && command -v sips >/dev/null; then
    ICONSET="$(mktemp -d)/job-watcher.iconset"
    mkdir -p "$ICONSET"
    if PYTHONPATH="$ROOT/desktop" "$PY" -c \
        "from icon import draw_mark; draw_mark(1024).save('$ICONSET/icon_512x512@2x.png')" 2>/dev/null; then
        for size in 16 32 128 256 512; do
            sips -z "$size" "$size" "$ICONSET/icon_512x512@2x.png" \
                --out "$ICONSET/icon_${size}x${size}.png" >/dev/null 2>&1 || true
            sips -z "$((size*2))" "$((size*2))" "$ICONSET/icon_512x512@2x.png" \
                --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null 2>&1 || true
        done
        iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/job-watcher.icns" 2>/dev/null \
            || echo "    (skipped .icns generation)"
    fi
fi

# Install into /Applications so it shows up in Launchpad and Spotlight. The
# launcher points at this repo by absolute path, so the copy stays in sync with
# code changes. Falls back to ~/Applications when /Applications is not writable.
DEST="/Applications"
[[ -w "$DEST" ]] || { DEST="$HOME/Applications"; mkdir -p "$DEST"; }
rm -rf "$DEST/JobWatcher.app"
ditto "$APP" "$DEST/JobWatcher.app"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
[[ -x "$LSREGISTER" ]] && "$LSREGISTER" -f "$DEST/JobWatcher.app" 2>/dev/null || true

echo
echo "Done. Installed to $DEST/JobWatcher.app — open it from Launchpad or Spotlight."
echo "Closing the window keeps the checks running from the menu-bar icon; use"
echo "'Sair' there to stop. Enable 'open at login' from the same menu."
