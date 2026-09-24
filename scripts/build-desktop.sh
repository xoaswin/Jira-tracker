#!/usr/bin/env bash
# Builds the Windows desktop installer end to end: frontend -> packaged
# backend exe -> Electron installer.
#
# Run from WSL, but the backend and Electron steps are shelled out to
# PowerShell against native Windows Python/Node - PyInstaller does not
# cross-compile, and electron-builder's NSIS target is far more reliable run
# natively than through Wine. See PROJECT_CONTEXT.md for the one-time Windows
# build-venv setup (backend/packaging/build_backend.ps1's header comment).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> [1/3] Building frontend..."
( cd "$ROOT/frontend" && npm ci && npm run build )

if [ ! -d "$ROOT/frontend/dist" ]; then
  echo "frontend/dist missing after build - aborting." >&2
  exit 1
fi

echo "==> [2/3] Building backend executable (native Windows via PowerShell)..."
BACKEND_WIN_PATH="$(wslpath -w "$ROOT/backend")"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \
  "cd '$BACKEND_WIN_PATH'; .\\.venv-winbuild\\Scripts\\Activate.ps1; .\\packaging\\build_backend.ps1"

BACKEND_EXE="$ROOT/backend/packaging/dist/jira-tracker-backend/jira-tracker-backend.exe"
if [ ! -f "$BACKEND_EXE" ]; then
  echo "Backend exe not found at $BACKEND_EXE after build - aborting." >&2
  exit 1
fi

if [ ! -f "$ROOT/desktop/assets/icon.ico" ] || [ ! -f "$ROOT/desktop/assets/tray-icon.ico" ]; then
  echo "desktop/assets/icon.ico or tray-icon.ico missing - aborting." >&2
  exit 1
fi

echo "==> [3/3] Building Electron installer (native Windows via PowerShell)..."
DESKTOP_WIN_PATH="$(wslpath -w "$ROOT/desktop")"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \
  "cd '$DESKTOP_WIN_PATH'; npm ci; npm run dist"

echo ""
echo "Done. Installer should be under desktop/release/."
