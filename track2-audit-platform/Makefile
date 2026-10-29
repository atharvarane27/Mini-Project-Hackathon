.PHONY: help install lint lint-backend lint-frontend typecheck typecheck-backend typecheck-frontend test test-backend test-frontend up up-local down config clean

help:
	@echo "AuditForge Track 2 Platform Commands:"
	@echo "  make install            - Install local dependencies for backend and frontend"
	@echo "  make lint               - Run code quality linters (ruff, eslint)"
	@echo "  make typecheck          - Run typecheckers (mypy, tsc)"
	@echo "  make test               - Run test suites (pytest, vitest)"
	@echo "  make up                 - Start api, worker, and frontend services in Docker"
	@echo "  make up-local           - Start with optional local-postgres profile"
	@echo "  make down               - Stop and remove running containers"
	@echo "  make config             - Validate docker-compose configuration"

install:
	cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd frontend && npm install

lint-backend:
	cd backend && .venv/bin/ruff check app tests

lint-frontend:
	cd frontend && npm run lint

lint: lint-backend lint-frontend

typecheck-backend:
	cd backend && .venv/bin/mypy app tests/unit/test_health.py

typecheck-frontend:
	cd frontend && npm run typecheck

typecheck: typecheck-backend typecheck-frontend

test-backend:
	cd backend && .venv/bin/pytest

test-frontend:
	cd frontend && npm run test

test: test-backend test-frontend

config:
	docker compose config

up:
	docker compose up --build -d api worker frontend

up-local:
	docker compose --profile local-postgres up --build -d

down:
	docker compose --profile local-postgres down

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
