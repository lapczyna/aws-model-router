.PHONY: help venv install install-dev install-infra lint format format-check typecheck \
        test test-infra test-cov precommit-install precommit-run cdk-synth cdk-diff \
        clean ci

PYTHON ?= python
VENV_DIR ?= .venv

help:
	@echo "Available targets:"
	@echo "  install           Install runtime dependencies"
	@echo "  install-dev       Install runtime + development dependencies"
	@echo "  install-infra     Also install AWS CDK (needed for infrastructure/ work)"
	@echo "  lint              Run Ruff lint checks"
	@echo "  format            Apply Black formatting"
	@echo "  format-check      Check formatting without modifying files"
	@echo "  typecheck         Run mypy static type checks"
	@echo "  test              Run unit and contract tests (excludes CDK assertion tests)"
	@echo "  test-infra        Run CDK assertion tests (real cdk synth — slower, opt-in)"
	@echo "  test-cov          Run tests with coverage report"
	@echo "  precommit-install Install git pre-commit hooks"
	@echo "  precommit-run     Run all pre-commit hooks against all files"
	@echo "  cdk-synth         Synthesize CDK app"
	@echo "  cdk-diff          Diff CDK app against deployed stacks"
	@echo "  clean             Remove caches and build artifacts"
	@echo "  ci                Run the full local verification suite"

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e .

install-dev:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

install-infra:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev,infra]"

lint:
	ruff check .

format:
	black .

format-check:
	black --check .

typecheck:
	mypy

test:
	pytest

test-infra:
	pytest -m infra

test-cov:
	pytest --cov --cov-report=term-missing

precommit-install:
	pre-commit install

precommit-run:
	pre-commit run --all-files

cdk-synth:
	cd infrastructure && cdk synth

cdk-diff:
	cd infrastructure && cdk diff

clean:
	$(PYTHON) - <<'PYCLEAN'
import pathlib
import shutil

patterns = [".pytest_cache", ".mypy_cache", ".ruff_cache", "__pycache__", "*.egg-info", "htmlcov"]
root = pathlib.Path(".")
for pattern in patterns:
    for path in root.rglob(pattern):
        shutil.rmtree(path, ignore_errors=True)
PYCLEAN

ci: format-check lint typecheck test
