.PHONY: install lint format security test check migrate dev prod logs shell

install:
	uv sync
	cd frontend && npm install

lint:
	cd backend && uv run ruff check app tests
	cd backend && uv run mypy --strict app
	cd frontend && npm run lint

format:
	cd backend && uv run ruff format app tests
	cd frontend && npm run format || echo "No format script in frontend, skipping"

security:
	cd backend && uv run bandit -c pyproject.toml -r app
	cd backend && uv run pip-audit

test:
	cd backend && uv run pytest -v

check: lint security test
	@echo "All pre-commit checks passed successfully!"

migrate:
	cd backend && uv run alembic upgrade head

dev:
	docker compose -f docker-compose.dev.yml up --build

prod:
	docker compose -f docker-compose.prod.yml up --build

logs:
	docker compose -f docker-compose.dev.yml logs -f backend

shell:
	docker compose -f docker-compose.dev.yml exec backend bash
