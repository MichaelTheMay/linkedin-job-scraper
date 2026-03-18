.PHONY: install test test-ci lint format typecheck setup validate scrape

install:
	pip install -e ".[dev]" && playwright install chromium

test:
	pytest tests/ -v

test-ci:
	pytest tests/ -v --ignore=tests/test_integration.py

lint:
	ruff check . && ruff format --check .

format:
	ruff check --fix . && ruff format .

typecheck:
	mypy --ignore-missing-imports .

setup:
	python main.py --login

validate:
	python main.py --validate

scrape:
	python main.py
