.PHONY: install run test lint backup help

help:
	@echo "install, run, test, lint, backup"

install:
	poetry install --with dev

run:
	poetry run python run.py

test:
	poetry run python -m pytest tests -q

lint:
	poetry run ruff check src tests run.py

backup:
	poetry run screener-ops backup-sqlite instance/operations.db backups/operations.db
