.PHONY: install lint format fix security test test-e2e coverage check check-backend migrate seed

install:
	cd backend && uv sync --locked
	cd frontend && npm ci

lint:
	cd backend && uv run --locked ruff check app tests
	cd backend && uv run --locked mypy --strict --explicit-package-bases app
	cd backend && uv run --locked ruff check --config pyproject.toml ../scripts
	cd frontend && npm run check

format:
	cd backend && uv run --locked ruff format --check app tests ../scripts
	cd frontend && npm exec -- prettier --check 'src/**/*.{ts,tsx,css}'

fix:
	cd backend && uv run --locked ruff check --fix app tests
	cd backend && uv run --locked ruff format app tests ../scripts
	cd frontend && npm exec -- prettier --write 'src/**/*.{ts,tsx,css}'

security:
	cd backend && uv run --locked bandit -c pyproject.toml -r app
	cd backend && uv run --locked pip-audit
	cd frontend && npm audit

test:
	cd backend && uv run --locked python -m pytest -m 'not e2e'

coverage:
	cd backend && uv run --locked python -m pytest -m 'not e2e' --cov=app --cov-report=term-missing --cov-fail-under=80

test-e2e:
	cd backend && RUN_E2E=1 uv run --locked python -m pytest -o addopts= tests/e2e

check: lint format test
	cd frontend && npm run build

check-backend:
	cd backend && uv run --locked ruff check app tests
	cd backend && uv run --locked ruff format --check app tests
	cd backend && uv run --locked mypy --strict --explicit-package-bases app
	cd backend && uv run --locked python -m pytest -m 'not e2e'

migrate:
	cd backend && uv run --locked alembic upgrade head

seed:
	cd backend && uv run --locked python -m app.db.seed
