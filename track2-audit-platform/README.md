# AuditForge — Track 2 Banking Audit, Record Resolution & Rule-Driven Workflow Platform

AuditForge is a deterministic, multi-branch banking audit platform built for high-concurrency fraud pattern detection, automated ledger reconciliation, custom in-memory duplicate resolution, runtime AST rule compilation, and strict DAG workflow governance.

## Technology Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2, Psycopg 3, Alembic, Pytest
- **Frontend**: Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS, Vitest
- **Database**: Supabase PostgreSQL (Managed Primary RDBMS with 3NF schema, outbox, and strict RBAC)
- **Containerization**: Docker Compose (`api`, single heap-owner `worker`, `frontend`, optional `local-postgres` profile)

## Architecture Overview

```text
CSV / Feeds ---> [FastAPI Ingestion] ---> [Supabase PostgreSQL (Raw Records + Canonical Txns)]
                        |
                        +---> [Durable Outbox]
                                    |
                                    v
       [Single Heap-Owner Worker Process (RAM Index + Heaps + DAGs)]
                                    |
       [Next.js Frontend] <--- [REST API /api/v1 (Typed Envelopes + RBAC)]
```

- **Algorithms**: Inverted index, Soundex, Levenshtein, Graph/DFS temporal cycles, sliding windows, AST lexer/parser, binary heap, and DAG topological sort are hand-written in `backend/app/engines/` without library black-boxes or SQL substitutes.
- **Data Integrity**: Financial money stored in integer minor units (paise); timestamps persisted in UTC `timestamptz`; currency formatted as ISO 4217.

## Quickstart

### 1. Prerequisites

- Python 3.12+
- Node.js 20+ and npm 10+
- Docker and Docker Compose (v2+)

### 2. Environment Configuration

Copy the example configuration to `.env`:

```bash
cp .env.example .env
```

Ensure placeholders are set for your database connection (`DATABASE_URL`). `.env` is blocked by `.gitignore` and must never be committed.

### 3. Local Development (Native)

```bash
# Install dependencies
make install

# Run code quality gates
make lint
make typecheck
make test

# Start backend locally
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000

# Start frontend locally
cd frontend
npm run dev
```

### 4. Docker Compose Deployment

```bash
# Validate compose configuration
make config

# Start full stack (api, worker, frontend) with primary Supabase DB
make up

# Alternatively start with optional local PostgreSQL container
make up-local

# Check API health
curl http://localhost:8000/api/v1/health

# Stop containers
make down
```

## API Convention & Health Check

All API responses follow the standard JSON envelope:

```json
{
  "data": {
    "status": "ok",
    "app": "AuditForge",
    "version": "0.1.0",
    "timestamp": "2026-10-29T17:40:00.000000Z",
    "db_backend": "supabase"
  },
  "meta": {},
  "request_id": "7f7bc86e11894d0c9a410319520cb955"
}
```

Error responses:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request input validation failed",
    "details": []
  },
  "request_id": "7f7bc86e11894d0c9a410319520cb955"
}
```

## Repository Structure

```text
track2-audit-platform/
├── docs/                 # Architecture, API contract, ADRs, phase status
├── backend/              # FastAPI application, engines, models, worker, tests
│   ├── app/
│   │   ├── engines/      # Pure in-memory deterministic algorithms
│   │   ├── core/         # RBAC, logging, request-ID, errors, idempotency
│   │   ├── db/           # SQLAlchemy 2 models & session management
│   │   ├── api/v1/       # REST API endpoints
│   │   └── worker/       # Dedicated single-heap-owner worker process
├── frontend/             # Next.js 15 App Router interface & Tailwind styles
├── infra/                # Supabase bootstrap & local PostgreSQL fallback
├── fixtures/             # Deterministic synthetic banking datasets
└── docker-compose.yml    # Container orchestration
```
