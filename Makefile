# Stock Screener V3 - Makefile
# Easy commands for development and deployment

.PHONY: install run dev test clean db-init db-migrate db-upgrade format lint help

# Python and Poetry
PYTHON = poetry run python
# Use 'python -m flask' instead of 'flask' to avoid Windows launcher issues
FLASK = poetry run python -m flask

# Default target
help:
	@echo "Stock Screener V3 - Available Commands"
	@echo "======================================="
	@echo ""
	@echo "Setup:"
	@echo "  make install       Install all dependencies"
	@echo "  make install-dev   Install with dev dependencies"
	@echo ""
	@echo "Database:"
	@echo "  make db-init       Initialize migrations folder"
	@echo "  make db-migrate    Create new migration"
	@echo "  make db-upgrade    Apply pending migrations"
	@echo "  make db-reset      Delete and recreate database"
	@echo ""
	@echo "Run:"
	@echo "  make run           Start Flask server"
	@echo "  make dev           Start with auto-reload"
	@echo ""
	@echo "Dev:"
	@echo "  make test          Run tests"
	@echo "  make format        Format code with black"
	@echo "  make lint          Lint with flake8"
	@echo "  make clean         Remove cache files"
	@echo ""

# ==================== SETUP ====================

install:
	poetry install

install-dev:
	poetry install --with dev

# ==================== DATABASE ====================

# Note: FLASK_APP must be set for flask-migrate commands
export FLASK_APP=run.py

db-init:
	$(FLASK) db init

db-migrate:
	$(FLASK) db migrate -m "Auto migration"

db-upgrade:
	$(FLASK) db upgrade

db-reset:
	rm -rf instance migrations
	$(FLASK) db init
	$(FLASK) db migrate -m "Initial"
	$(FLASK) db upgrade

# ==================== RUN ====================

run:
	$(PYTHON) run.py

dev:
	FLASK_DEBUG=1 $(FLASK) run --reload

# ==================== DEVELOPMENT ====================

test:
	$(PYTHON) -m pytest tests/ -v --cov=services --cov=utils --cov=models --cov=config --cov=router --cov-report=term-missing

format:
	poetry run black .
	poetry run isort .

lint:
	poetry run flake8 .

# ==================== CLEANUP ====================

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name ".DS_Store" -delete 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov

# ==================== SHORTCUTS ====================

# Quick start for new developers
setup: install db-init db-migrate db-upgrade
	@echo "Setup complete! Run 'make run' to start."

# Daily workflow
daily: db-upgrade run
