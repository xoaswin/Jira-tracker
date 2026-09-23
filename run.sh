#!/usr/bin/env bash
# Dev launcher: FastAPI on 8756 with reload, Vite on 5173 proxying /api to it.
# Ctrl-C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

if [ ! -d "$BACKEND/.venv" ]; then
  echo "No backend venv found. Create it with:"
  echo "  cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -e ."
  exit 1
fi

echo "Starting backend (FastAPI) on http://localhost:8756 ..."
(
  cd "$BACKEND"
  . .venv/bin/activate
  # Bind 0.0.0.0 so Windows can reach it across the WSL2 network boundary.
  exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8756 --reload
) &
BACKEND_PID=$!

echo "Starting frontend (Vite) on http://localhost:5173 ..."
(
  cd "$FRONTEND"
  exec npm run dev
) &
FRONTEND_PID=$!

cleanup() {
  echo "Shutting down..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo ""
echo "Open http://localhost:5173  (dev)"
echo "API at http://localhost:8756/api"
echo ""
wait
