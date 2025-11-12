.PHONY: help install dev fmt lint type test unit cov run build up down logs snapshot restore seed clean

PY=python3
PIP=pip
APP=app:create_app()
PORT?=10000

help:
	@echo "Targets:"
	@echo "  install     - install deps"
	@echo "  dev         - install dev tools (pre-commit)"
	@echo "  fmt         - format (black + isort)"
	@echo "  lint        - ruff lint"
	@echo "  type        - mypy type-check"
	@echo "  test        - pytest (unit + integration)"
	@echo "  unit        - pytest unit only"
	@echo "  cov         - pytest with coverage"
	@echo "  run         - run dev server (Flask)"
	@echo "  build       - docker build"
	@echo "  up / down   - docker compose up/down"
	@echo "  logs        - tail app logs"
	@echo "  snapshot    - snapshot tenant data"
	@echo "  restore     - dry-run restore snapshot"
	@echo "  seed        - load example business data"
	@echo "  clean       - remove caches and pyc"

install:
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

dev: install
	pre-commit install

fmt:
	black .
	isort .

lint:
	ruff check .

type:
	mypy .

test:
	pytest -v

unit:
	pytest -v -k "not acceptance"

cov:
	pytest -q --cov=. --cov-report=term-missing

run:
	export FLASK_APP=$(APP) && flask run --port=$(PORT)

build:
	docker build -t ai-sales-assistant:latest .

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	tail -n 200 -f logs/chatbot.log

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
