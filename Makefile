PYTHON ?= python3

.PHONY: install dev test lint typecheck check build previews

install:
	$(PYTHON) -m pip install .

dev:
	$(PYTHON) -m pip install -e '.[dev]'

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check src tests docs/generate_previews.py

typecheck:
	$(PYTHON) -m mypy src docs/generate_previews.py

check: test lint typecheck

build:
	$(PYTHON) -m build

previews:
	$(PYTHON) docs/generate_previews.py
