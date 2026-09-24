# Builds the standalone Windows backend executable for the desktop app.
#
# Must run on native Windows (PyInstaller does not cross-compile from WSL),
# against a dedicated Python 3.11/3.12 build venv - NOT backend/.venv, which
# tracks whatever the dev machine's default Python is (3.14 here, too new for
# reliable PyInstaller/keyring/pywin32 support).
#
# One-time setup, from backend/:
#   py -3.12 -m venv .venv-winbuild
#   .\.venv-winbuild\Scripts\Activate.ps1
#   pip install -e .                       # NOT ".[embeddings]" - keeps torch out
#   pip install pyinstaller pyinstaller-hooks-contrib
#
# Then run this script from backend/ with .venv-winbuild activated.

$ErrorActionPreference = "Stop"

# Absolute paths throughout: --specpath packaging changes where PyInstaller
# resolves *relative* --add-data source paths (it uses the spec file's own
# directory, not the invocation CWD, once the spec is generated/re-read) -
# bare relative paths like "alembic.ini" resolve to packaging\alembic.ini and
# fail. Absolute paths sidestep that entirely.
$BackendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$AlembicIni = Join-Path $BackendRoot "alembic.ini"
$AlembicDir = Join-Path $BackendRoot "alembic"
$MainPy = Join-Path $BackendRoot "app\main.py"
$FrontendDist = Resolve-Path (Join-Path $BackendRoot "..\frontend\dist") -ErrorAction SilentlyContinue
if (-not $FrontendDist) {
    Write-Error "frontend/dist not found - run 'npm run build' in frontend/ first."
    exit 1
}

Push-Location $BackendRoot
try {
    pyinstaller `
        --name jira-tracker-backend `
        --onedir `
        --noconsole `
        --distpath packaging\dist `
        --workpath packaging\build `
        --specpath packaging `
        --add-data "${AlembicIni};backend" `
        --add-data "${AlembicDir};backend\alembic" `
        --add-data "${FrontendDist};frontend\dist" `
        --hidden-import keyring.backends.Windows `
        --collect-all win32ctypes `
        --copy-metadata keyring `
        --exclude-module torch `
        --exclude-module sentence_transformers `
        --exclude-module pytest `
        --exclude-module respx `
        --exclude-module pytest_asyncio `
        $MainPy

    Write-Host ""
    Write-Host "Built: backend\packaging\dist\jira-tracker-backend\jira-tracker-backend.exe"
    Write-Host "Verify (Phase 1 of the desktop plan) before wiring into Electron:"
    Write-Host "  1. cd packaging\dist\jira-tracker-backend"
    Write-Host "  2. `$env:DATABASE_URL = 'sqlite:///C:/temp/jira-tracker-test/tracker.db'"
    Write-Host "  3. `$env:LOG_DIR = 'C:/temp/jira-tracker-test/logs'"
    Write-Host "  4. .\jira-tracker-backend.exe"
    Write-Host "  5. In another shell: Invoke-RestMethod http://127.0.0.1:8756/api/health"
    Write-Host "  6. Open http://127.0.0.1:8756/ in a browser - should show the app UI"
    Write-Host "  7. Check the log file for 'Using OS keyring backend' vs the file-fallback warning"
} finally {
    Pop-Location
}
