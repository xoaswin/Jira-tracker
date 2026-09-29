#!/usr/bin/env bash
# Refresh the standalone app in desktop/release/win-unpacked (what the Start-menu
# shortcut points to) with the current source. Run this after any app code change.
#
# It deliberately AVOIDS electron-builder: on this OneDrive-synced checkout its
# native app-builder.exe is a cloud-only placeholder that fails to execute, and
# the NSIS installer needs Developer Mode for symlinks. Instead it rebuilds the
# pieces by hand: frontend -> PyInstaller backend exe -> swap into win-unpacked
# -> repack app.asar with the pure-JS asar tool. Requires win-unpacked to already
# exist once (produced earlier by an electron-builder run).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WIN_UNPACKED="desktop/release/win-unpacked"
if [ ! -d "$WIN_UNPACKED" ]; then
  echo "ERROR: $WIN_UNPACKED does not exist yet. Run a full electron-builder pass once first." >&2
  exit 1
fi

echo "== closing running app (standing approval for the rebuild flow) =="
# The packaged app runs as "Jira Tracker.exe", not electron.exe. If it survives,
# swapping app.asar under it makes it read pages at stale offsets (garbage in the
# check-in window) and relaunching starts a second copy. /T takes the bundled
# backend (a child process) down with it; the last line catches an orphan.
powershell.exe -NoProfile -Command "taskkill /F /T /IM 'Jira Tracker.exe'; taskkill /F /IM electron.exe; taskkill /F /IM jira-tracker-backend.exe" 2>&1 || true
powershell.exe -NoProfile -Command "Start-Sleep -Seconds 2" 2>&1 || true

echo "== cleaning stale PyInstaller output =="
rm -rf backend/packaging/dist backend/packaging/build 2>&1 || true

echo "== [1/4] frontend build =="
( cd frontend && npm run build ) || { echo "FRONTEND BUILD FAILED"; exit 1; }
[ -d frontend/dist ] || { echo "frontend/dist missing"; exit 1; }

echo "== [2/4] backend exe (PyInstaller, native Windows) =="
BACKEND_WIN="$(wslpath -w "$ROOT/backend")"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \
  "cd '$BACKEND_WIN'; .\\.venv-winbuild\\Scripts\\Activate.ps1; .\\packaging\\build_backend.ps1; exit \$LASTEXITCODE" \
  || { echo "BACKEND BUILD FAILED"; exit 1; }
[ -f "backend/packaging/dist/jira-tracker-backend/jira-tracker-backend.exe" ] || { echo "backend exe missing"; exit 1; }

echo "== [3/4] swap fresh backend into win-unpacked =="
rm -rf "$WIN_UNPACKED/resources/backend"
[ -e "$WIN_UNPACKED/resources/backend" ] && { echo "OLD BACKEND STILL LOCKED (is the app running?)"; exit 1; }
mkdir -p "$WIN_UNPACKED/resources/backend"
cp -r "backend/packaging/dist/jira-tracker-backend/." "$WIN_UNPACKED/resources/backend/"
# A freshly built exe can be briefly locked (Defender scan / OneDrive), and cp
# then silently skips it; retry, and fail loudly rather than ship no backend.
for i in 1 2 3 4 5; do
  [ -f "$WIN_UNPACKED/resources/backend/jira-tracker-backend.exe" ] && break
  sleep 3
  cp "backend/packaging/dist/jira-tracker-backend/jira-tracker-backend.exe" "$WIN_UNPACKED/resources/backend/" 2>/dev/null
done
[ -f "$WIN_UNPACKED/resources/backend/jira-tracker-backend.exe" ] || { echo "BACKEND EXE COPY FAILED"; exit 1; }

echo "== [4/4] repack app.asar (main.js + preload + renderer + assets) =="
STAGE="$(mktemp -d)"
cp desktop/main.js desktop/preload.js desktop/recorder.js desktop/package.json "$STAGE/"
cp -r desktop/renderer "$STAGE/"
cp -r desktop/assets "$STAGE/"
( cd desktop && ./node_modules/.bin/asar pack "$STAGE" "release/win-unpacked/resources/app.asar" ) \
  || { echo "ASAR PACK FAILED"; rm -rf "$STAGE"; exit 1; }
rm -rf "$STAGE"

echo ""
echo "DONE. Relaunch 'Jira Tracker' from the Start menu to pick up the changes."
