# Phase 20 verification report

Run date: 30 October 2026  
Release status: **not ready for final production release**

## Verified results

| Check | Result |
|---|---|
| Backend unit/integration/stress suite | 221 passed |
| Backend warning | 1 dependency deprecation warning from FastAPI TestClient |
| Ruff | Passed across app, tests, scripts and migrations |
| Strict mypy | Passed across 98 app/script source files |
| Frontend TypeScript | Passed |
| Frontend production export | Passed; 15 application routes plus root/not-found |
| Adversarial re-import | 24 simultaneous imports retained 250 unique source identities |
| Frozen expected evidence | 3 unique findings: 1 circular, 2 splitting |
| Secret hygiene scan | `.env` ignored; no credential-shaped source values found |
| Supabase connectivity | Passed, PostgreSQL 17.11 |
| Supabase migration | `0002_ingestion (head)` |
| Supabase server connection limit | 60 |
| Algorithm benchmark | Eight workloads available, including reconciliation |

Benchmark details are in `benchmark-results.json`; assumptions and complexity
claims are in `algorithm-complexity.md`.

## Adversarial coverage

- Fifty-way case-claim races produce one winner.
- Two worker heaps racing the same durable case produce one winner.
- Twenty-five producers and twenty-five consumers lose or duplicate no work.
- Concurrent priority updates preserve heap and position-map invariants.
- Concurrent splitting retries commit one logical run/finding.
- Concurrent prerequisite completions unlock a dependent workflow task once.
- Workflow cycles, late events, source conflicts, stale versions, unauthorized
  actions and activity mutation are rejected by existing tests.
- P20 simultaneous re-import coverage preserves source identity uniqueness.

## Measured environment

- Windows 11 (`10.0.26200`)
- CPython 3.13.9 for verification; project target remains Python 3.12
- Next.js 16.4.3 static export
- Supabase PostgreSQL 17.11 through the configured pooler

These results are local development evidence and do not assert production
latency or capacity. Backup state and point-in-time recovery cannot be confirmed
from the database URL; verify them in the Supabase dashboard before release.

## Release blockers and known limitations

1. Several services still use in-memory/reference repositories instead of the
   Supabase transactional adapters required for restart durability.
2. Detector and reconciliation runtime loaders still require Supabase-backed
   canonical snapshots, although every API router is now composed.
3. Docker is not installed, so Compose validation and containers were not run.
4. Supabase backup/PITR settings require dashboard verification.
5. Private Sites source/deployment was not authorized.
6. Verification used Python 3.13.9 locally; the Dockerfile pins Python 3.12.

## Acceptance decision

Available algorithms, concurrency controls, reconciliation, Supabase schema,
frontend build and synthetic evidence pass their gates. Phase 20 is **partially
implemented and verified**, with its final gate blocked by the production
persistence, live frontend and deployment connections listed above.
