.PHONY: run-backend run-frontend build test eval

VENV := .venv/bin

run-backend:
	$(VENV)/uvicorn app.main:app --app-dir backend --reload --port 8000

run-frontend:
	npm --prefix frontend run dev

build:
	npm --prefix frontend run build

test:
	$(VENV)/pytest

eval:
	@echo "not implemented"
