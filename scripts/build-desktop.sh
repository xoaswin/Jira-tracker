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
# npm install (not ci): the project lives on a OneDrive-synced folder, where
# `npm ci` wiping node_modules triggers OneDrive's mass-delete prompt and can
# hit EBUSY locks. install is gentler and reproducible enough for a local build.
( cd "$ROOT/frontend" && npm install && npm run build )

if [ ! -d "$ROOT/frontend/dist" ]; then
  echo "frontend/dist missing after build - aborting." >&2
  exit 1
fi

echo "==> [2/3] Building backend executable (native Windows via PowerShell)..."
BACKEND_WIN_PATH="$(wslpath -w "$ROOT/backend")"
# PowerShell does not turn a failing native command's exit code into a
# terminating error by default, so without the explicit $LASTEXITCODE check
# this powershell.exe call (and bash's set -e) would silently treat an
# internal build_backend.ps1 failure as success.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \
  "cd '$BACKEND_WIN_PATH'; .\\.venv-winbuild\\Scripts\\Activate.ps1; .\\packaging\\build_backend.ps1; exit \$LASTEXITCODE"

BACKEND_EXE="$ROOT/backend/packaging/dist/jira-tracker-backend/jira-tracker-backend.exe"
if [ ! -f "$BACKEND_EXE" ]; then
  echo "Backend exe not found at $BACKEND_EXE after build - aborting." >&2
  exit 1
fi

if [ ! -f "$ROOT/desktop/assets/icon.ico" ] || [ ! -f "$ROOT/desktop/assets/tray-icon.ico" ]; then
  echo "desktop/assets/icon.ico or tray-icon.ico missing - aborting." >&2
  exit 1
fi

# desktop/package.json's "dist" script sets CSC_IDENTITY_AUTO_DISCOVERY=false:
# without it, electron-builder tries to fetch/extract winCodeSign (macOS
# signing tooling) even for a Windows-only unsigned build, and extraction
# fails with "Cannot create symbolic link: A required privilege is not held
# by the client" unless Windows Developer Mode is on. We don't sign at all,
# so this just skips that irrelevant step entirely.
echo "==> [3/3] Building Electron installer (native Windows via PowerShell)..."
DESKTOP_WIN_PATH="$(wslpath -w "$ROOT/desktop")"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \
  "cd '$DESKTOP_WIN_PATH'; npm install; if (\$LASTEXITCODE -ne 0) { exit \$LASTEXITCODE }; npm run dist; exit \$LASTEXITCODE"

INSTALLER=$(find "$ROOT/desktop/release" -maxdepth 1 -iname "*.exe" 2>/dev/null | head -1)
if [ -z "$INSTALLER" ]; then
  echo "No installer .exe found under desktop/release/ - build did not actually succeed." >&2
  exit 1
fi

echo ""
echo "Done. Installer: $INSTALLER"
