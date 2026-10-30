.PHONY: run-backend run-frontend build test web-test data eval


VENV := .venv/bin

run-backend:
	$(VENV)/uvicorn app.main:app --app-dir backend --reload --port 8000

run-frontend:
	npm --prefix frontend run dev

build:
	npm --prefix frontend run build

test:
	$(VENV)/pytest

web-test:
	npm --prefix frontend test

data:
	$(VENV)/python -m data.generator --all

eval:
	PYTHONPATH=.:backend $(VENV)/python -m evals.harness


