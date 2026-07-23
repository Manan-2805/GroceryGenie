SHELL := powershell.exe
.SHELLFLAGS := -NoProfile -Command

.PHONY: install setup lint format security test test-e2e playwright-install check check-backend migrate dev prod up down backend-logs frontend-logs setup-git-hooks

setup:
	if (!(Test-Path .env.dev)) { Copy-Item .env.example .env.dev }
	docker compose -f docker-compose.infra.yml up -d
	if (!(Test-Path scripts)) { New-Item -ItemType Directory -Path scripts }
	Copy-Item -Path scripts/pre-commit -Destination .git/hooks/pre-commit -Force
	Write-Host "GroceryGenie setup complete! Infrastructure containers are starting."

install: setup

setup-git-hooks:
	if (!(Test-Path scripts)) { New-Item -ItemType Directory -Path scripts }
	Copy-Item -Path scripts/pre-commit -Destination .git/hooks/pre-commit -Force
	Write-Host "Git hooks installed successfully."

lint:
	cd backend; uv run ruff check app tests --fix
	cd backend; uv run mypy --strict --explicit-package-bases app
	cd frontend; if (!(Test-Path node_modules\.bin)) { npm install }; npm run check

format:
	cd backend; uv run ruff format app tests
	cd frontend; if (!(Test-Path node_modules\.bin)) { npm install }; npx prettier --write "src/**/*.{ts,tsx,css,html}"

security:
	cd backend; uv run bandit -c pyproject.toml -r app
	cd backend; uv run pip-audit

test:
	cd backend;$$env:RUN_E2E="1"; $$env:PLAYWRIGHT_HEADLESS="0"; $$env:PLAYWRIGHT_SLOW_MO="50"; uv run python -m pytest -v

test-e2e:
	cd backend; $$env:RUN_E2E="1"; $$env:PLAYWRIGHT_HEADLESS="0"; $$env:PLAYWRIGHT_SLOW_MO="50"; uv run python -m pytest -v -m e2e tests/test_e2e.py

playwright-install:
	cd backend; uv run python -m playwright install chromium

check-backend:
	cd backend; uv run ruff check app tests
	cd backend; uv run mypy --strict --explicit-package-bases app
	cd backend; uv run bandit -c pyproject.toml -r app
	cd backend; uv run pip-audit
	cd backend; uv run python -m pytest -v -m "not e2e"

check: lint format security test
	Write-Host "All pre-commit checks passed successfully on local machine!"

migrate:
	cd backend; uv run alembic upgrade head

db-reset:
	docker exec grocergenie-redis redis-cli FLUSHALL
	docker exec grocergenie-neo4j cypher-shell -u neo4j -p grocergeniepass "MATCH (n) DETACH DELETE n;"
	cd backend; uv run python -B -m app.db.reset
	cd backend; uv run alembic upgrade head
	cd backend; uv run python -B -m app.db.seed

up:
	docker compose -f docker-compose.infra.yml up -d

down:
	docker compose -f docker-compose.infra.yml down

prod:
	docker compose -f docker-compose.prod.yml up --build -d

backend-logs:
	docker compose -f docker-compose.prod.yml logs -f backend

frontend-logs:
	docker compose -f docker-compose.prod.yml logs -f frontend
