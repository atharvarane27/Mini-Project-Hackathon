# Track 2 Banking Audit Platform

Project structure follows section 8 of the supplied PRD. Working name: AuditForge.

**Status: structure only.** Modules, tests, frontend directories, fixtures and infrastructure files are placeholders. No application logic, dependencies, database connections, migrations or executable test cases have been implemented. The project is not runnable yet.

## Layout

- backend/app/api/v1/: HTTP routes.
- backend/app/db/: persistence session and relational models.
- backend/app/schemas/: request and response contracts.
- backend/app/core/: authentication, RBAC, errors, idempotency and audit writing.
- backend/app/ingestion/: streaming import, normalization and canonicalization.
- backend/app/engines/: identity, reconciliation, circular flows, splitting, rules, queue and workflow.
- backend/app/services/: finding, case and outbox orchestration.
- backend/app/worker/: worker entry point.
- backend/tests/: unit, integration and concurrency stress placeholders.
- backend/scripts/: seeding, fixture generation and benchmarking.
- frontend/src/app/: Next.js App Router feature directories.
- frontend/src/components/: reusable UI directories.
- frontend/src/lib/: API client and types.
- infra/: Supabase and optional local PostgreSQL setup.
- fixtures/: synthetic data placeholders.
- docs/: architecture, API, schema, complexity, demo and decisions.
- docs/dataset.md: augmented dataset fields, scenarios and usage constraints.
- PRD.md: paragraph-text extraction of the Word document; original table formatting is not preserved.

Planned stack: Next.js/TypeScript, FastAPI/Python 3.12, SQLAlchemy/Alembic and Supabase PostgreSQL. Financial audit decisions belong in the backend. Implement incrementally through PRD phases P0 to P8.

.gitkeep files preserve empty directories; __init__.py files establish Python packages. Dependencies and runnable commands will be added in P0.
