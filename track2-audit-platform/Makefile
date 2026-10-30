.PHONY: install api worker test lint typecheck verify frontend-check benchmark demo-fixtures release-check compose-config migrate migration

install:
	cd backend && python -m pip install -e ".[dev]"

api:
	cd backend && python -m uvicorn app.main:app --reload

worker:
	cd backend && python -m app.worker.main

test:
	cd backend && python -m pytest -q -p no:cacheprovider

lint:
	cd backend && python -m ruff check app tests

typecheck:
	cd backend && python -m mypy --strict app

verify: lint typecheck test

frontend-check:
	cd frontend && npm run typecheck && npm run build

benchmark:
	cd backend && python scripts/benchmark_algorithms.py --repeats 3 --output ../docs/benchmark-results.json

demo-fixtures:
	cd backend && python scripts/seed_demo.py

release-check: verify frontend-check demo-fixtures benchmark

compose-config:
	docker compose config --quiet

migrate:
	cd backend && python -m alembic upgrade head

migration:
	cd backend && python -m alembic revision --autogenerate -m "$(NAME)"
