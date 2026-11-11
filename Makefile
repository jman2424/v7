.PHONY: help install dev lint type test cov console run build up down snapshot restore seed clean

PY=python3
PIP=pip
APP=app:create_app()
PORT?=10000

help:
	@echo "Targets:"
	@echo "  install     - install deps"
	@echo "  dev         - install lint, type-check and test tools"
	@echo "  lint        - ruff lint"
	@echo "  type        - mypy type-check"
	@echo "  test        - pytest"
	@echo "  console     - check, test and build the owner console"
	@echo "  cov         - pytest with coverage"
	@echo "  run         - run the isolated local preview"
	@echo "  build       - docker build"
	@echo "  up / down   - docker compose up/down"
	@echo "  snapshot    - snapshot tenant data"
	@echo "  restore     - dry-run restore snapshot"
	@echo "  seed        - load example business data"
	@echo "  clean       - remove caches and pyc"

install:
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

dev: install
	$(PIP) install -r requirements-dev.txt

lint:
	ruff check .

type:
	mypy .

test:
	pytest

console:
	cd frontend && npm ci && npm run check && npm test && V7_CONSOLE_BASE_PATH=/console npm run build

cov:
	pytest -q --cov=. --cov-report=term-missing

run:
	$(PY) scripts/run_local.py

build:
	docker build -t ai-sales-assistant:latest .

up:
	docker compose up --build -d

down:
	docker compose down

snapshot:
	$(PY) scripts/snapshot_backup.py

restore:
	$(PY) scripts/restore_snapshot.py --dry-run

seed:
	$(PY) scripts/seed_example_data.py

clean:
	find . -name "__pycache__" -type d -exec rm -rf {} +
	find . -name ".mypy_cache" -type d -exec rm -rf {} +
	find . -name ".pytest_cache" -type d -exec rm -rf {} +
	find . -name ".ruff_cache" -type d -exec rm -rf {} +
	find . -name "*.pyc" -delete
