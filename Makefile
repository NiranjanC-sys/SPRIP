.PHONY: setup migrate run test lint format reset-db services bootstrap train-models

VENV   := .venv/Scripts
PYTHON := $(VENV)/python
PIP    := $(VENV)/pip
ALEMBIC:= $(VENV)/alembic
RUFF   := $(VENV)/ruff

export MIGRATION_DATABASE_URL ?= postgresql+psycopg://app_migrator:app_migrator_pw@127.0.0.1:54329/speaker_roi

## ── Setup ──────────────────────────────────────────────────────────────────

setup:  ## Create venv and install in editable mode
	python -m venv .venv
	$(PIP) install -e ".[dev]"

## ── Database ───────────────────────────────────────────────────────────────

services:  ## Start PostgreSQL, Redis, MinIO (local dev tools)
	$(PYTHON) scripts/devtools/pg.py start
	$(PYTHON) scripts/devtools/services.py start

migrate:  ## Run Alembic migrations against speaker_roi
	$(ALEMBIC) upgrade head

reset-db:  ## Drop and recreate both databases, then migrate
	$(PYTHON) scripts/devtools/pg.py reset
	$(ALEMBIC) upgrade head
	MIGRATION_DATABASE_URL=postgresql+psycopg://app_migrator:app_migrator_pw@127.0.0.1:54329/speaker_roi_test \
		$(ALEMBIC) upgrade head

bootstrap:  ## Create a demo tenant and admin user
	$(PYTHON) -m speaker_roi_api.cli admin bootstrap \
		--tenant-code demo --tenant-name "Demo Pharma India" \
		--email admin@demo.example --display-name "Demo Admin" \
		--password "change-me-on-first-login"

## ── Run ────────────────────────────────────────────────────────────────────

run:  ## Start the API server
	$(PYTHON) -m uvicorn speaker_roi_api.main:create_app --factory \
		--host 0.0.0.0 --port 8000 --reload

## ── ML Pipeline ────────────────────────────────────────────────────────────

train-models:  ## Train ML models on synthetic data (M1 propensity, M2 causal, M3 forecast)
	$(PYTHON) -c "from speaker_roi_core.ml_pipeline import train_all_models; train_all_models()"

## ── Quality ────────────────────────────────────────────────────────────────

lint:  ## Run ruff linter
	$(RUFF) check --fix -q .
	$(RUFF) check .

format:  ## Run ruff formatter
	$(RUFF) format .

test:  ## Run the test suite (unit + integration if DB is available)
	$(PYTHON) -m pytest tests -x -q

test-unit:  ## Unit tests only
	$(PYTHON) -m pytest tests -x -q -m "not integration"

test-integration:  ## Integration tests only (needs PostgreSQL)
	$(PYTHON) -m pytest tests/integration -x -q

## ── Help ───────────────────────────────────────────────────────────────────

help:  ## Show this help
	@grep -E '^[a-z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
