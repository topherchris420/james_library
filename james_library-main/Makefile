# Vers3Dynamics R.A.I.N. Lab — Unified Development Commands
# Usage: make <target>
#
# Run `make help` for a full list of targets.

PYTHON ?= python
CARGO  ?= cargo

.PHONY: help install install-all install-dev lint lint-py lint-rs test test-py test-rs build run preflight health check fmt clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Install ──────────────────────────────────────────────────

install: ## Install core Python dependencies
	$(PYTHON) -m pip install -r requirements.txt

install-all: ## Install all Python dependencies (core + optional extras)
	$(PYTHON) -m pip install -e ".[all]"

install-dev: ## Install dev dependencies (pytest, ruff, coverage)
	$(PYTHON) -m pip install -e ".[dev,all]"

# ── Lint ─────────────────────────────────────────────────────

lint: lint-py lint-rs ## Run all linters

lint-py: ## Lint Python with ruff
	$(PYTHON) -m ruff check .

lint-rs: ## Lint Rust with clippy
	$(CARGO) clippy --all-targets -- -D warnings

# ── Format ───────────────────────────────────────────────────

fmt: ## Format all code (ruff + cargo fmt)
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .
	$(CARGO) fmt --all

# ── Test ─────────────────────────────────────────────────────

test: test-py test-rs ## Run all tests

test-py: ## Run Python tests
	$(PYTHON) -m pytest tests/ -q

test-rs: ## Run Rust tests
	$(CARGO) test

# ── Build ────────────────────────────────────────────────────

build: ## Build Rust binary (release)
	$(CARGO) build --release

# ── Run ──────────────────────────────────────────────────────

run: ## Launch R.A.I.N. Lab chat mode (interactive topic prompt)
	$(PYTHON) rain_lab.py --mode chat

preflight: ## Run environment preflight checks
	$(PYTHON) rain_lab.py --mode preflight

health: ## Run local health check
	$(PYTHON) rain_health_check.py

first-run: ## Run guided first-run onboarding
	$(PYTHON) rain_lab.py --mode first-run

# ── Quality Gates ────────────────────────────────────────────

check: lint test ## Full quality gate (lint + test)

# ── Clean ────────────────────────────────────────────────────

clean: ## Remove build artifacts and caches
	$(CARGO) clean
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
