# Finstack — Track 2 Banking Audit Platform

Project structure follows section 8 of the supplied PRD.

**Status:** Phases P00–P19 have implementations, including P07 reconciliation.
The composed API exposes every phase route, the frontend uses the live API for
all operational screens, and 221 backend tests pass. P20 remains partial until
production Supabase persistence adapters, Docker runtime verification, backup
confirmation and final deployment are complete;
see `docs/test-report.md`.

## Development

1. Copy `.env.example` to `.env` and replace database placeholders.
2. Run `make install`.
3. Run `make api` and open `http://localhost:8000/api/v1/health`.
4. In another terminal, run `cd frontend && npm run dev`, then open
   `http://localhost:3000/login/`. The default development account is `admin`
   with the password configured by `DEMO_ADMIN_PASSWORD`.
5. Run `make verify` before committing.
6. Run `make release-check` for the frontend build, frozen-fixture validation,
   backend suite, and algorithm benchmarks.

`docker compose config --quiet` validates containers. `docker compose up
--build api worker` starts backend services; add `--profile local-db` only when
using local PostgreSQL instead of Supabase.

## Layout

- backend/app/api/v1/: HTTP routes.
- backend/app/db/: persistence session and relational models.
- backend/app/schemas/: request and response contracts.
- backend/app/core/: authentication, RBAC, errors, idempotency and audit writing.
- backend/app/ingestion/: streaming import, normalization and canonicalization.
- backend/app/engines/: identity, reconciliation, circular flows, splitting, rules, queue and workflow.
- backend/app/services/: finding, case and outbox orchestration.
- backend/app/worker/: worker entry point.
- backend/tests/: unit, integration and adversarial concurrency coverage.
- backend/scripts/: seeding, fixture generation and benchmarking.
- frontend/src/app/: Next.js App Router feature directories.
- frontend/src/components/: reusable UI directories.
- frontend/src/lib/: API client and types.
- infra/: Supabase and optional local PostgreSQL setup.
- fixtures/: frozen synthetic evidence and expected detector outcomes.
- docs/: architecture, API, schema, complexity, demo and decisions.
- docs/dataset.md: augmented dataset fields, scenarios and usage constraints.
- docs/integration-connections.md: authoritative live/pending connection map.
- PRD.md: paragraph-text extraction of the Word document; original table formatting is not preserved.

Stack: Next.js/TypeScript, FastAPI/Python 3.12, SQLAlchemy/Alembic and Supabase PostgreSQL. Financial audit decisions belong in the backend.

The connected demo flow is: import two CSV ledgers with distinct source-system
names, inspect canonical transactions and duplicates, run reconciliation and
both pattern detectors, create a case from a finding, claim it, and inspect the
authenticated activity ledger. CSV imports require `external_id`,
`transaction_reference`, `sender_account_id`, `receiver_account_id`, `amount`,
`currency`, and timezone-aware `occurred_at` columns.

.gitkeep files preserve empty directories; `__init__.py` files establish Python packages.
