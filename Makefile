PYTHON ?= python3

.PHONY: install dev test lint typecheck check build

install:
	$(PYTHON) -m pip install .

dev:
	$(PYTHON) -m pip install -e '.[dev]'

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check src tests

typecheck:
	$(PYTHON) -m mypy src

check: test lint typecheck

build:
	$(PYTHON) -m build
