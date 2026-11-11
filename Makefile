.PHONY: help install test lint build-web up down logs seed

help:
	@echo "install   - create venv and install backend deps"
	@echo "test      - run pytest"
	@echo "lint      - run ruff"
	@echo "build-web - build the React app"
	@echo "up        - docker compose up --build -d"
	@echo "down      - docker compose down"
	@echo "logs      - follow compose logs"
	@echo "seed      - import demo titles through the API"

install:
	python -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e packages/manga_common
	.venv/bin/pip install -r services/parser/requirements.txt
	.venv/bin/pip install -r services/catalog/requirements.txt
	.venv/bin/pip install -r services/library/requirements.txt
	.venv/bin/pip install -r services/media/requirements.txt
	.venv/bin/pip install -r services/control/requirements.txt
	.venv/bin/pip install -r services/gateway/requirements.txt
	.venv/bin/pip install -r services/scheduler/requirements.txt
	.venv/bin/pip install -r services/notifier/requirements.txt
	.venv/bin/pip install pytest pytest-asyncio pytest-cov respx ruff

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check .

build-web:
	cd apps/web && npm ci && npm run build

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

seed:
	.venv/bin/python scripts/seed_demo.py
