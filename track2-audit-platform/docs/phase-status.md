# Phase Status Log

## Phase P00: Repository and Development Environment

- **Status**: Completed
- **Date**: 2026-10-29
- **Implemented Scope**:
  1. Backend environment configured in `backend/pyproject.toml` (Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2, Psycopg 3, Alembic, pytest, ruff, mypy).
  2. Application settings configured via `pydantic-settings` in `backend/app/config.py`.
  3. Structured JSON logging and request ID tracking middleware (`X-Request-ID`) in `backend/app/core/logging.py` and `backend/app/main.py`.
  4. Standard API envelope (`ApiResponse`, `ApiErrorResponse`, `HealthStatus`) and error handlers in `backend/app/schemas/common.py` and `backend/app/core/errors.py`.
  5. `GET /api/v1/health` and root `/health` endpoints.
  6. Single heap-owner worker entrypoint in `backend/app/worker/main.py`.
  7. Frontend Next.js 15 App Router + React 19 + TypeScript + Tailwind CSS setup in `frontend/` with typed API client (`api.ts`), type definitions (`types.ts`), and unit test suite via Vitest.
  8. `docker-compose.yml` orchestrating `api`, ONE dedicated `worker` (future heap owner), `frontend`, and an optional `local-postgres` profile.
  9. `.env.example` with sanitized placeholders; verified `.gitignore` blocks `.env`.
  10. `Makefile` with targets (`install`, `lint`, `typecheck`, `test`, `config`, `up`, `up-local`, `down`).
  11. GitHub Actions CI workflow in `.github/workflows/ci.yml`.
  12. Updated `README.md` and `docs/architecture.md`.

### Changed Files

- `.github/workflows/ci.yml` (new)
- `track2-audit-platform/.env.example` (modified)
- `track2-audit-platform/.gitignore` (modified)
- `track2-audit-platform/Makefile` (modified)
- `track2-audit-platform/README.md` (modified)
- `track2-audit-platform/docker-compose.yml` (modified)
- `track2-audit-platform/backend/.dockerignore` (new)
- `track2-audit-platform/backend/Dockerfile` (new)
- `track2-audit-platform/backend/pyproject.toml` (modified)
- `track2-audit-platform/backend/app/config.py` (modified)
- `track2-audit-platform/backend/app/core/errors.py` (modified)
- `track2-audit-platform/backend/app/core/logging.py` (new)
- `track2-audit-platform/backend/app/main.py` (modified)
- `track2-audit-platform/backend/app/schemas/common.py` (modified)
- `track2-audit-platform/backend/app/worker/main.py` (modified)
- `track2-audit-platform/backend/tests/unit/test_health.py` (new)
- `track2-audit-platform/frontend/.dockerignore` (new)
- `track2-audit-platform/frontend/Dockerfile` (new)
- `track2-audit-platform/frontend/package.json` (modified)
- `track2-audit-platform/frontend/package-lock.json` (new)
- `track2-audit-platform/frontend/tsconfig.json` (modified)
- `track2-audit-platform/frontend/next.config.ts` (new)
- `track2-audit-platform/frontend/next-env.d.ts` (new)
- `track2-audit-platform/frontend/postcss.config.mjs` (new)
- `track2-audit-platform/frontend/tailwind.config.ts` (new)
- `track2-audit-platform/frontend/eslint.config.mjs` (new)
- `track2-audit-platform/frontend/vitest.config.ts` (new)
- `track2-audit-platform/frontend/public/.gitkeep` (new)
- `track2-audit-platform/frontend/src/app/globals.css` (new)
- `track2-audit-platform/frontend/src/app/layout.tsx` (new)
- `track2-audit-platform/frontend/src/app/page.tsx` (new)
- `track2-audit-platform/frontend/src/lib/api.ts` (modified)
- `track2-audit-platform/frontend/src/lib/types.ts` (modified)
- `track2-audit-platform/frontend/tests/health.test.ts` (new)
- `track2-audit-platform/infra/local-postgres/init.sql` (modified)
- `track2-audit-platform/docs/architecture.md` (modified)
- `track2-audit-platform/docs/phase-status.md` (new)

### API Contracts Implemented

- `GET /api/v1/health`
  - Success Response Envelope:
    ```json
    {
      "data": {
        "status": "ok",
        "app": "AuditForge",
        "version": "0.1.0",
        "timestamp": "2026-10-29T18:04:12.928228+00:00",
        "db_backend": "supabase"
      },
      "meta": {},
      "request_id": "cc34c3e29ae2445ba47a4b76a553cdcb"
    }
    ```
- `GET /health` (lightweight probe returning `{"status": "ok"}`)

### Migrations

- None in P00. (Database schema & Alembic models start in P01).

### Decisions & Assumptions (ADRs)

- `docs/adr/0001-single-heap-owner.md`: Dedicated single worker process holds the heap in memory; cross-process durability relies on PostgreSQL outbox & conditional updates.

### Commits

- `a1a5b74`: feat(backend): configure Python 3.12, FastAPI, logging, health check, and worker
- `3907415`: feat(frontend): setup Next.js 15, TypeScript, Tailwind, API client, and Vitest
- `265cb8d`: feat(infra): configure docker-compose, local-postgres, CI workflow, Makefile, and docs

---

## Phase P01: Shared Contracts and Interface Specification

- **Status**: Completed
- **Date**: 2026-10-29
- **Implemented Scope**:
  1. Completed all 8 frozen Pydantic v2 schema modules:
     - `common.py`: UserRole, OutboxStatus, UtcDatetime, MoneyMinor, CurrencyCode, deterministic SHA-256 fingerprints, ApiResponse, PaginatedResponse, ApiErrorResponse, OutboxEvent.
     - `transactions.py`: SourceRecord, CanonicalTransaction, JournalLine, Journal, SourceRecordTransactionLink with amount > 0 and journal line side validation.
     - `detectors.py`: FindingFacts (11 frozen fact names per PRD), DuplicateEvidence, ReconciliationEvidence, CircularFlowEvidence, SplittingEvidence, UnbalancedJournalEvidence, FindingDraft, Finding.
     - `cases.py`: AuditCase (priority 0–100, row_version ≥ 1), WorkflowTask, CaseTransitionRequest, CaseClaimRequest.
     - `ingestion.py`: IngestionJob lifecycle, IngestionJobCounts, IngestionRowError, SourceRecordEvent, CanonicalTransferEvent (PRD section 10 contracts).
     - `reconciliation.py`: ReconciliationRun, ReconciliationResult (MATCHED/MISSING/MISMATCH/AMBIGUOUS/WITHIN_TOLERANCE), ReconciliationPolicy, ReconciliationSummary with cutoff_at > start_at validation.
     - `rules.py`: Token, AstNode, Rule (DRAFT/ACTIVE/DEPRECATED), RuleValidationResult with typed RuleDiagnostic, RuleEvaluationResult with ExplanationNode tree (PRD section 10).
     - `workflows.py`: WorkflowTemplate (versioned, immutable-after-activation), WorkflowEdge (self-edge rejection), DagValidationResult, CaseWorkflow runtime snapshot, TaskCompleteRequest.
  2. `frontend/src/lib/types.ts` fully mirrored with TypeScript readonly interfaces for all schemas.
  3. 14 contract unit tests covering: fingerprint determinism, UTC datetime validation, float money rejection, journal balance, detector serialization, case priority bounds, task stable key, frozen models.

### Test Results
- `tests/unit/test_contracts.py`: 14/14 PASSED
- `tests/unit/test_health.py`: 3/3 PASSED
- Frontend `tsc --noEmit`: 0 errors
- Frontend `vitest`: 7/7 PASSED (`tests/contracts.test.ts` + `tests/health.test.ts`)

---

## Phase P02: Identity Engine (Duplicate Detection)

- **Status**: Completed
- **Date**: 2026-10-29
- **Implemented Scope**:
  1. `engines/identity/soundex.py`: Hand-written American Soundex (O(n), pure Python). Supports H/W adjacency transparency, vowel reset, non-ASCII stripping, 4-char padding.
  2. `engines/identity/levenshtein.py`: Wagner-Fischer DP with single-row O(min(n,m)) space optimisation. Normalised similarity ratio in [0.0, 1.0].
  3. `engines/identity/inverted_index.py`: Field-level InvertedIndex with O(t) insert, O(t·k) candidate retrieval. Avoids O(n²) all-pairs scan. Includes `partition_sizes()` for benchmark metrics.
  4. `engines/identity/blocking.py`: Two-stage BlockingEngine — inverted-index token overlap (stage 1) + Soundex phonetic filter (stage 2). Returns deterministic sorted BlockingPair list.
  5. `engines/identity/resolver.py`: End-to-end DuplicateResolver — blocking → Levenshtein scoring → threshold filter → sorted DuplicateCandidate list. Includes `partition_sizes()` and `total_records()` observability.

### Test Results
- `tests/unit/test_soundex.py`: 20/20 PASSED
- `tests/unit/test_levenshtein.py`: 21/21 PASSED
- `tests/unit/test_index.py`: 23/23 PASSED
- **Total: 81/81 unit tests PASSED**

### Algorithm Complexity (per PRD algorithm-complexity.md)
| Algorithm | Time | Space |
|-----------|------|-------|
| Soundex | O(n) | O(1) |
| Levenshtein | O(n·m) | O(min(n,m)) |
| InvertedIndex insert | O(t) | O(t) |
| InvertedIndex candidates | O(t·k) | O(k) |
| BlockingEngine (2-stage) | O(t + k·1) | O(k) |

---

## Phase P02: Supabase Schema, Migrations and Integrity

- **Status**: Completed
- **Date**: 2026-10-30
- **Implemented Scope**:
  1. 3NF SQLAlchemy 2 Declarative Models (`backend/app/db/models/*.py`):
     - `base.py`: Base with UTC `DateTime(timezone=True)` type annotation mapping.
     - `accounts.py`: `Branch`, `Account` with `UNIQUE(branch_id, masked_label)`.
     - `ingestion.py`: `SourceSystem`, `IngestionJob`, `SourceRecord`, `SourceRecordTransaction` with `UNIQUE(source_system_id, external_ref, source_revision)`.
     - `transactions.py`: `Transaction` with `CHECK(amount_minor > 0)` and indexes on `(occurred_at, sender_account_id)` and `(receiver_account_id, occurred_at)`.
     - `journals.py`: `Journal`, `JournalLine` with `CHECK(debit >= 0 AND credit >= 0 AND ((debit > 0 AND credit == 0) OR (debit == 0 AND credit > 0)))`.
     - `reconciliation.py`: `ReconciliationRun` with `CHECK(cutoff_at > start_at)`, `ReconciliationResult` with `UNIQUE(run_id, left_record_id, right_record_id)`.
     - `findings.py`: `DetectorConfig` with `UNIQUE(detector_type, version)`, `Finding` with `UNIQUE(fingerprint)`, `FindingTransaction`.
     - `rules.py`: `Rule` with `UNIQUE(name, version)`.
     - `cases.py`: `AuditCase` with `CHECK(0 <= priority AND priority <= 100)` and index `(state, priority)`, `CaseFinding`, `CaseTask` with index `(case_id, state)`.
     - `workflow.py`: `WorkflowTemplate` with `UNIQUE(name, version)`, `WorkflowTaskTemplate` with `UNIQUE(template_id, stable_key)`, `WorkflowEdge` with `CHECK(predecessor != successor)`.
     - `auth.py`: `User`, `Role`, `UserRole`.
     - `audit.py`: `ActivityLog` with index `(entity_type, entity_id, occurred_at)`.
     - `outbox.py`: `OutboxEvent` with `UNIQUE(event_type, entity_id, payload_hash)` and index `(status, created_at)`.
     - `__init__.py`: Full model registry exported.
  2. Database Session Management (`backend/app/db/session.py`):
     - Transaction-scoped session context manager `get_db_context()`.
     - FastAPI dependency `get_db()`.
     - Supabase connection pooling (`DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `DATABASE_POOL_TIMEOUT`, `DATABASE_POOL_RECYCLE`, `pool_pre_ping`).
     - Supabase SSL configuration (`sslmode=require` enforcement).
     - SQLite hermetic testing support with `PRAGMA foreign_keys=ON`.
  3. Alembic Migrations:
     - `backend/alembic/env.py`: Targets `Base.metadata`, supports offline `--sql` and online modes.
     - `backend/alembic/script.py.mako`: Migration template.
     - `backend/alembic.ini`: Configured with logging sections and script location.
     - `backend/alembic/versions/0001_initial_schema.py`: Complete 26-table initial schema with `upgrade()` and clean reverse-order `downgrade()`.
  4. SQL Infrastructure Scripts:
     - `infra/supabase/bootstrap.sql`: Extensions (`uuid-ossp`, `pgcrypto`), `prevent_activity_log_tampering` trigger function, permission revocation.
     - `infra/supabase/README.md`: Step-by-step project creation, connection strings, pooling, SSL, and migration runbook.
     - `infra/local-postgres/init.sql`: Local fallback script with extensions and append-only trigger.
  5. Idempotent Seed Data (`backend/app/db/seed.py`):
     - 5 RBAC roles (`ADMIN`, `AUDITOR`, `REVIEWER`, `VIEWER`, `SYSTEM_WORKER`).
     - 5 Demo users with Argon2 password hashes.
     - 3 Source systems, 3 branches, 5 sample accounts.
     - 4 Core detector configs (v1).
     - Track 2 Dual Prerequisite Workflow Template (`Branch_Ledge_Clearance` + `External_Whistleblower_Audit` $\to$ `Escalation_Status`).
     - Initial audit AST evaluation rule.
  6. Documentation:
     - `docs/schema-erd.md`: Mermaid ER diagram, 3NF normalization rules, constraint catalog, and PRD index mapping.

### Test Results
- `tests/integration/test_db_schema.py`: **11/11 PASSED**
  - `test_migration_upgrade_and_downgrade_repeatability`: PASSED
  - `test_reject_transaction_non_positive_amount`: PASSED (IntegrityError)
  - `test_reject_journal_line_both_sides_positive`: PASSED (IntegrityError)
  - `test_reject_audit_case_priority_out_of_bounds`: PASSED (IntegrityError)
  - `test_reject_reconciliation_cutoff_before_start`: PASSED (IntegrityError)
  - `test_reject_workflow_edge_self_loop`: PASSED (IntegrityError)
  - `test_branch_delete_blocked_when_accounts_exist`: PASSED (RESTRICT)
  - `test_account_delete_blocked_when_transactions_exist`: PASSED (RESTRICT)
  - `test_source_records_idempotency_uniqueness`: PASSED (IntegrityError)
  - `test_outbox_events_dedup_uniqueness`: PASSED (IntegrityError)
  - `test_seed_database_repeatability`: PASSED (Idempotent 0 duplicates)
- **Total Backend Tests: 92/92 PASSED**
- **Total Frontend Tests: 7/7 PASSED** (Vitest), `tsc --noEmit` 0 errors.

---

## Phase P03: Bounded Streaming Ingestion and Validation

- **Status**: Completed
- **Date**: 2026-10-30
- **Implemented Scope**:
  1. `backend/app/ingestion/csv_reader.py`:
     - `BoundedCSVReader`: Stream rows line-by-line in bounded chunks of 500 records (`batch_size=500`).
     - Memory invariant: Never loads the full CSV file into memory; supports TextIO, file path, and binary UploadFile streams.
     - `compute_payload_hash`: SHA-256 deterministic payload digest over canonical sorted JSON.
     - BOM handling: Supports UTF-8 with BOM (`utf-8-sig`).
  2. `backend/app/ingestion/normalizer.py`:
     - `RowNormalizer`: Type parsing, timestamp normalization to timezone-aware UTC, decimal currency amounts converted to integer minor units (paise).
     - Strict validation taxonomy with stable diagnostic codes:
       - `MISSING_EXTERNAL_REF`: Empty or missing external reference identifier.
       - `INVALID_AMOUNT`: Non-positive, zero, or non-decimal amounts.
       - `INVALID_TIMESTAMP`: Malformed date/time strings or unparseable formats.
       - `INVALID_CURRENCY`: Currency code not conforming to ISO 4217 (or non-INR in demo).
       - `INVALID_DIRECTION`: Entry direction not DEBIT or CREDIT.
       - `MISSING_COUNTERPARTY`: Missing sender/source or receiver/destination.
       - `IDENTICAL_COUNTERPARTY`: Source account equals destination account.
  3. `backend/app/ingestion/canonicalizer.py`:
     - `Canonicalizer`: Converts valid normalized rows into `SourceRecord`, `Transaction`, and `SourceRecordTransaction` link models.
     - Automatically ensures branch and account entities exist in the session to avoid foreign key violation on RESTRICT constraints.
  4. `backend/app/ingestion/service.py`:
     - `IngestionService`: Orchestrates reading, normalizing, canonicalizing, and committing bounded transactional batches.
     - Job lifecycle management: `PENDING` -> `RUNNING` -> `COMPLETED` / `PARTIAL` / `FAILED`.
     - Idempotency-Key support: Re-running with identical key returns cached job state.
     - Row deduplication vs conflict resolution:
       - Exact duplicate payload for `(source_system_id, external_ref, source_revision)` increments duplicate count without double-inserting records or transactions.
       - Altered payload with same `(source_system_id, external_ref, source_revision)` flags an `EXTERNAL_REF_REVISION_CONFLICT` row error quarantined for audit review.
     - Outbox pattern: Atomic staging of `SOURCE_RECORD_ACCEPTED` events in `outbox_events` within the same database transaction.
     - SQLite hermetic compatibility: Ensures UTC timezone awareness on read-back datetimes.
  5. `backend/app/api/v1/ingestion.py`:
     - `POST /api/v1/ingestion/jobs`: Multipart form upload accepting CSV file, `source_system_id`, optional `branch_id`, and optional `Idempotency-Key` header.
     - `GET /api/v1/ingestion/jobs/{id}`: Returns ingestion job status and counts envelope (`total_rows`, `accepted`, `rejected`, `duplicate`, `errors`).
  6. `backend/app/schemas/ingestion.py` & `frontend/src/lib/types.ts`:
     - Synchronized models including `duplicate` counter on `IngestionJobCounts`.
  7. Synthetic Fixtures (`backend/scripts/generate_fixture.py` & `fixtures/`):
     - Deterministic seeded generator (`--seed 42`).
     - Standard test fixtures generated: `ledger_internal.csv`, `ledger_counterpart.csv`, `malformed_records.csv`, `circular_transfers.csv`, `splitting_transfers.csv`.
  8. Test Suite (`backend/tests/integration/test_ingestion.py`):
     - 52 integration and unit tests covering normalizer codes, chunked streaming, idempotency, revision conflicts, 10,000-row bounded memory profile (`tracemalloc` peak < 30 MB), and FastAPI endpoints.

### Test Results
- `tests/integration/test_ingestion.py`: **52/52 PASSED**
- **Total Backend Tests: 144/144 PASSED** (exit code 0 in 30.03s)
- **Ruff linter**: All checks passed (0 errors)
- **Mypy typechecker**: Success (0 issues across 97 source files)
- **Frontend linter, typecheck & Vitest**: All checks passed (7/7 tests passed, 0 errors)

