.PHONY: install run test lint type security backup restore worker help

help:
	@echo "install, run, test, lint, type, security, backup, restore, worker"

install:
	poetry install --with dev

run:
	poetry run python run.py

test:
	poetry run python -m pytest tests -q

lint:
	poetry run ruff format --check src tests run.py
	poetry run ruff check src tests run.py

type:
	poetry run mypy src run.py

security:
	poetry run bandit -q -r src run.py

backup:
	poetry run screener-ops backup-sqlite instance/system.db backups/system.db

restore:
	poetry run screener-ops restore-sqlite backups/system.db instance/restored-system.db

worker:
	poetry run screener-ops work-once instance
