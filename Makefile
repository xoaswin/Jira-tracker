.PHONY: dev backend frontend install migrate test test-backend test-frontend build clean

# Run both dev servers (FastAPI 8756 + Vite 5173).
dev:
	./run.sh

# Backend only, with reload. Binds 0.0.0.0 so Windows can reach it across the
# WSL2 network boundary (127.0.0.1 inside the VM is not visible from Windows).
backend:
	cd backend && . .venv/bin/activate && python -m uvicorn app.main:app --host 0.0.0.0 --port 8756 --reload

# Frontend dev server only.
frontend:
	cd frontend && npm run dev

# One-time setup.
install:
	cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[test]"
	cd frontend && npm install

# Apply DB migrations.
migrate:
	cd backend && . .venv/bin/activate && alembic upgrade head

# Tests.
test: test-backend test-frontend

test-backend:
	cd backend && . .venv/bin/activate && python -m pytest -q

test-frontend:
	cd frontend && npm run test

# Production build: emit the frontend so FastAPI can serve it as static files.
build:
	cd frontend && npm run build

clean:
	rm -rf backend/data/*.db frontend/dist
