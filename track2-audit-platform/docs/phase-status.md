# Phase status

## P00 — Repository and development environment

Status: Implemented on 30 October 2026; Docker runtime verification is pending
because Docker is not installed on this workstation.

### Delivered

- Python 3.12 FastAPI/SQLAlchemy/Psycopg/Alembic dependency configuration.
- Runnable FastAPI application factory and `/api/v1/health` endpoint.
- Request IDs, structured JSON request logs and controlled internal errors.
- Environment-only settings with safe non-secret defaults.
- Dedicated single-owner worker process entrypoint and graceful signal shutdown.
- API, worker and optional local PostgreSQL Docker Compose services.
- Backend Dockerfile, Make targets and GitHub Actions verification workflow.
- Updated architecture, environment template and development instructions.
- Health and request-ID integration test.

### Acceptance evidence

- Health test — 1 passed.
- Full backend suite — 167 passed with one dependency deprecation warning.
- Ruff passed across app/tests; strict mypy passed across 91 source files.
- Compose YAML parsed and required `api`, `worker`, `postgres` services exist.
- `docker compose config` and container startup could not run because the Docker
  CLI is unavailable locally; run `make compose-config` after installing Docker.

Frontend runtime/UI setup remains deferred under the user's explicit instruction
to wait for their Phase 19 design. No secrets or database migration were added.
Commit hash: pending team commit.

## P01 — Shared contracts, event identity and interface specification

Status: Implemented and locally verified on 30 October 2026.

### Delivered

- Frozen SourceRecord, CanonicalTransaction, JournalLine, Finding, AuditCase,
  OutboxEvent and WorkflowTask Python contracts.
- Matching readonly TypeScript interfaces and branded money/timestamp helpers.
- Strict integer minor units, ISO currency and timezone-aware UTC validation.
- Stable namespace-aware SHA-256 fingerprints that reject floating point.
- Shared success/error envelopes, pagination and idempotency-key rules.
- Fixed finding fact registry, role matrix and outbox lifecycle.
- Documented authoritative flow, duplicate-copy semantics and graph distinction.

### Acceptance evidence

- Focused contract suite — 8 passed.
- Full backend suite — 175 passed with one dependency deprecation warning.
- TypeScript contracts compile with `tsc --noEmit`.
- Missing IDs, floating-point money, malformed timestamps, unknown facts and
  unsafe fingerprint values are rejected.
- Reconciliation, circular and splitting examples use one Finding contract.

No database migration was added. Commit hash: pending team commit.

## P02 — Supabase schema, migrations and integrity

Status: Implemented and locally verified on 30 October 2026.

### Delivered

- 26-table normalized SQLAlchemy schema covering reference, financial,
  detection, case/workflow, security, audit and outbox domains.
- Restrictive foreign keys preserving financial and audit evidence.
- Uniqueness, CHECK constraints and operational indexes.
- Transaction-scoped session factory with Supabase pool/SSL URL support.
- Initial Alembic migration with ADMIN/AUDITOR/REVIEWER/VIEWER seed roles.
- Matching local PostgreSQL migration path.
- Supabase append-only activity grants and mutation-rejection trigger.

### Acceptance evidence

- Focused schema/session suite — 4 passed.
- Full backend suite — 204 passed with one dependency deprecation warning.
- Alembic upgrade and downgrade executed successfully; four roles were seeded.
- Ruff passed for app/tests/migrations; strict mypy passed across 92 sources.
- Restrictive provenance and outbox/source uniqueness constraints were tested.

Live Supabase execution remains environment-dependent because no credentials
were supplied; the verified migration is identical for Supabase PostgreSQL and
the local fallback. Commit hash: pending team commit.

## P03 — Bounded CSV ingestion, validation and quarantine

Status: Implemented and locally verified on 30 October 2026.

### Delivered

- Streaming CSV reader with configurable bounded batches and field limits.
- Normalization to UTC timestamps and integer minor-unit money.
- Stable validation diagnostics and row-level quarantine without batch loss.
- File, row, payload-hash and source-revision provenance.
- Idempotent imports, source identity uniqueness and interrupted-job restart.
- Upload and job-status API contracts plus four ingestion persistence tables.
- Deterministic fixture generator for large test files.

### Acceptance evidence

- Focused P03/P04 suite — 13 passed.
- Full backend suite — 211 passed with one dependency deprecation warning.
- A 10,005-row fixture completed in batches of at most 250 rows.
- Repeat imports created no duplicate source identities; malformed rows were
  quarantined with stable codes and their jobs remained queryable.
- Alembic upgrade/downgrade through `0002_ingestion` completed successfully.
- Ruff and strict mypy passed for all Phase 3 files.

Live Supabase credentials are not required for local verification. The
production deployment will use the same PostgreSQL migration and requires a
Supabase database URL when it is connected. Commit hash: pending team commit.

## P04 — Canonical financial events and double-entry journal integrity

Status: Implemented against the P03 accepted-record boundary and locally
verified on 30 October 2026.

### Delivered

- Immutable accepted-source, canonical-transfer and journal-posting contracts.
- Deterministic canonical/source/economic fingerprints and stable IDs.
- Source-record provenance links with exact replay idempotency.
- Changed-payload source-revision conflict detection.
- Ambiguous economic copies retained and marked for review.
- Reversible corrections linked to originals without mutation.
- Balanced debit/credit journal validation with integer minor units.
- Unique downstream snapshot and paginated transaction search API.

### Acceptance evidence

- Focused P04–P06 integration suite — 16 passed.
- Full backend suite — 200 passed with one dependency deprecation warning.
- Repeated transport copies produce one canonical downstream event.
- Unbalanced journals are rejected while original postings remain traceable.
- Ruff and strict mypy passed across all backend source files.

P02 models and the P03 accepted-record boundary are now implemented. Phase 4
uses a transactionally faithful reference repository pending the production
Supabase adapter. No P04 migration was added. Commit hash: pending team commit.

## P05 — Custom low-memory inverted index and phonetic blocking

Status: Implemented and locally verified on 30 October 2026.

### Delivered

- Application-owned blocking-key to record-ID posting lists.
- Exact reference/account/date/amount-band/currency keys.
- Custom Unicode-aware Soundex partitions for party names.
- Incremental insert, update, removal and atomic rebuild.
- Explicit locking for concurrent inserts and searches.
- Bucket skew limits, posting-visit counts, memory estimates and latency metrics.
- Direct Phase 6 `CandidateProvider` compatibility.

### Acceptance evidence

- Focused P05/P06 integration suite — 12 passed.
- Full backend suite — 194 passed with one dependency deprecation warning.
- Incremental and rebuilt snapshots match.
- 20 concurrent workers insert/search 2,000 records without posting corruption.
- Lookup visits posting lists only; no all-record pair generation exists.
- Ruff and strict mypy passed across all identity engine modules.

P04 durable record loading remains pending; `rebuild()` accepts its future
immutable record stream. No migration or API change was added.
Commit hash: pending team commit.

## P06 — Edit-distance duplicate classification and evidence

Status: Implemented against the P05 candidate-provider boundary and locally
verified on 30 October 2026.

### Delivered

- Unicode/case/separator normalization and custom bounded Levenshtein distance.
- Deterministic EXACT, CANDIDATE, AMBIGUOUS and NON_MATCH rules.
- Explicit reversal, inverted-side and recurring-transaction false-match guards.
- Auditable evidence with record links, attributes, distances, score reasons
  and algorithm version.
- Candidate-provider protocol enforcing blocked comparisons and bucket bounds.
- Thread-safe evidence repository and filtered `GET /duplicates` route.
- Typo, reversal, ambiguity, skew and balanced-performance tests.

### Acceptance evidence

- Focused P06 suite — 13 passed.
- Full backend suite — 188 passed with one dependency deprecation warning.
- Ruff and strict mypy passed across all 91 backend source files.
- The 1,000-record balanced fixture performs 1,000 comparisons, far below N².
- Ambiguous candidates preserve all source links; no record is merged/deleted.

P06 consumes the implemented P05 `CandidateProvider` boundary without coupling
the resolver to a persistence implementation. No database migration was added.

## P07 — Automated ledger reconciliation

Status: Implemented and locally verified on 30 October 2026.

### Delivered

- Deterministic reference-first matching with a bounded composite-key fallback.
- Strict one-to-one consumption and explicit ambiguous many-to-one evidence.
- MATCHED, AMOUNT_MISMATCH, FIELD_MISMATCH, INTERNAL_ONLY,
  COUNTERPART_ONLY, PENDING_LATE, AMBIGUOUS and UNBALANCED_JOURNAL results.
- Currency-aware double-entry journal balance validation.
- Stable run keys, input digests, retry idempotency and conflict detection.
- POST run and paginated GET result endpoints with validated contracts.
- Non-empty internal and counterpart ledger fixtures.

### Acceptance evidence

- Focused reconciliation suite — 5 passed.
- Full backend suite — 221 passed with one dependency deprecation warning.
- INR 25,000 versus INR 24,500 produces a 50,000 minor-unit variance.
- Duplicate references remain AMBIGUOUS and never silently multi-match.
- Same checkpoint/input replays one logical run; changed input conflicts.
- Ruff and strict mypy pass for the P07 implementation.

The composed runtime exposes the reconciliation endpoints. Loading canonical
ledger snapshots from Supabase belongs to the production persistence connection.

## P08 — Circular transfer graph construction and cycle search

Status: Implemented and locally verified on 30 October 2026.

### Delivered

- Custom directed transfer multigraph with distinct parallel edges.
- Posted-transfer filtering and canonical transaction conflict detection.
- Bounded DFS recursion-stack simple-cycle search.
- Maximum-hop, maximum-window and maximum-candidate limits.
- Candidate deduplication using canonical transaction IDs.
- Traversal statistics covering examined edges, pruning and depth.
- Self-loop, parallel-edge, acyclic, true-cycle, invalid-time and 2,000-edge
  sparse-graph tests.
- Deterministic circular-transfer fixture.

### Acceptance evidence

- Focused P08 suite — 7 passed; combined P08/P09 suite — 16 passed.
- Full backend suite — 166 passed with one dependency deprecation warning.
- Ruff and strict mypy passed across five circular engine modules.
- `A -> B -> C -> A` yields one candidate; `A -> B -> C -> D` yields none.
- Parallel transfers remain distinct and hop/window limits are enforced.

No database migration or API change was required. P08 emits the immutable
candidate contract consumed by P09. Commit hash: pending team commit.

## P09 — Circular-flow temporal validation and audit findings

Status: Implemented against the P08 candidate boundary and locally verified on
29 October 2026.

### Delivered

- Immutable circular transfer, candidate and versioned policy contracts.
- Strict chronological, window, currency, path, initial-amount and amount-
  variation validation.
- Rejection of static cycles that cannot represent chronological fund flow.
- Immutable `CIRCULAR_FLOW` findings with ordered evidence and stable SHA-256
  fingerprints.
- Stable checkpoint runs, changed-input conflict detection and retry
  idempotency.
- Circular run and type-filtered findings API routes.
- Repository protocol plus concurrency-safe in-memory transaction adapter.

### Acceptance evidence

- Focused P09 suite — 9 passed.
- Full backend suite — 159 passed with one dependency deprecation warning.
- Ruff and strict mypy passed across four P09 source modules.
- Valid chronological cycle creates one finding; invalid timing, window,
  currency, amount variation and initial amount create none.

P09 consumes the P08 immutable cycle-candidate boundary directly. Database
persistence remains behind the P02 repository adapter. No migration was added.
Commit hash: pending team commit.

## P10 — Transaction splitting partitioning and sliding windows

Status: Implemented and locally verified on 29 October 2026.

### Delivered

- Immutable, versioned splitting policy using integer minor units.
- Currency-safe sender, sender/receiver, and sender/receiver/type partitions.
- Explicit filters for status, individual amount, transaction type, fees, cash,
  internal movements, and reversals.
- Exact canonical replay suppression and conflicting-ID rejection.
- Deterministic historical sorting by UTC timestamp and transaction ID.
- Inclusive sliding-window boundary, two-pointer deque scan, and running sum.
- Controlled late-event and maximum-window-capacity errors.
- Positive and negative deterministic CSV fixtures.
- Complexity and bounded-memory documentation.

P11 responsibilities are intentionally excluded: finding fingerprints,
overlap suppression, persistence, detector run checkpoints, APIs, and stress
orchestration.

### Files changed

- `backend/app/engines/splitting/partition.py`
- `backend/app/engines/splitting/window.py`
- `backend/tests/unit/test_splitting.py`
- `fixtures/splitting_transfers.csv`
- `docs/algorithm-complexity.md`
- `docs/phase-status.md`

### Validation

- `python -m pytest tests/unit/test_splitting.py -q -p no:cacheprovider` — 19 passed.
- `python -m compileall -q app/engines/splitting tests/unit/test_splitting.py` — passed.
- `python -m ruff check ...` for P10 source and tests — passed.
- `python -m mypy app/engines/splitting/partition.py app/engines/splitting/window.py` — passed with strict project configuration.

### Integration handoff

P10 exposes a small immutable `TransferEvent` engine-boundary view. During
production persistence integration, map the P04 canonical transaction to:
canonical transaction ID, sender, receiver, integer amount, ISO currency, UTC
timestamp, type, status, and explicit reversal/category flags.

Database migrations: none. API changes: none. Commit hash: pending team commit.

## P11 — Splitting detector findings and run orchestration

Status: Implemented and locally verified on 29 October 2026.

### Delivered

- Transitive overlap suppression using canonical transaction IDs.
- Stable SHA-256 finding fingerprints tied to algorithm/policy versions,
  partition key, and complete contributing transaction set.
- Canonical `SPLITTING_PATTERN` facts and reproducible transaction evidence.
- Idempotent run identity plus normalized input digest conflict detection.
- Atomic repository port for run, findings, and run/finding associations.
- Thread-safe in-memory adapter for retry and contention verification.
- Composable HTTP 202 run endpoint and paginated finding retrieval route.
- Integration tests for retries, changed-input conflict, empty runs, policy
  versions, evidence, HTTP validation, and envelopes.
- Stress tests covering 2,000 partitions and 50 concurrent retries.

### Files changed

- `backend/app/engines/splitting/service.py`
- `backend/app/services/finding_service.py`
- `backend/app/schemas/detectors.py`
- `backend/app/api/v1/detectors.py`
- `backend/tests/integration/test_splitting_runs.py`
- `backend/tests/stress/test_splitting_stream.py`
- `docs/api-contract.md`
- `docs/algorithm-complexity.md`
- `docs/phase-status.md`

### Validation

- Focused P10/P11 unit, integration, and stress suite — 28 passed.
- Ruff on P10/P11 source and tests — passed.
- Strict mypy on seven P10/P11 source modules — passed.

### Integration handoff

The production Supabase repository and canonical snapshot/policy loaders cannot
be wired in this checkout because its P00–P09 models and session code are still
placeholders. The repository port requires one transaction for the detector
run, unique findings, and associations; the P02 adapter must also enforce unique
run keys and finding fingerprints. The composable router is ready to be
included by the merged P00 application. No database migration was invented in
P11, and no P12 rule-language work was started.

Commit hash: pending team commit.

## P12 — Custom rule language lexer and grammar

Status: Implemented and locally verified on 29 October 2026.

### Delivered

- Custom single-pass character lexer with no parser-generator dependency.
- Immutable typed tokens with exact offsets and multiline line/column data.
- Exact `int` and `Decimal` numeric literals and Boolean literals.
- Case-insensitive logical keywords with preserved field identifiers.
- All six comparison operators and parenthesis tokens.
- Stable diagnostics for invalid characters, numbers, operators, length,
  nesting, and unmatched parentheses.
- Configurable 4,096-character and 64-level default safety limits.
- Required Track 2 numeric/Boolean field type registry.
- Fixture-driven valid and invalid tokenization corpus.
- Grammar, lexical, diagnostic, and P12/P13 boundary documentation.

### Files changed

- `backend/app/engines/rules/tokens.py`
- `backend/app/engines/rules/lexer.py`
- `backend/app/engines/rules/types.py`
- `backend/tests/unit/test_lexer.py`
- `fixtures/rule_lexer_cases.json`
- `docs/rule-language.md`
- `docs/algorithm-complexity.md`
- `docs/phase-status.md`

### Acceptance evidence

- Full available backend suite — 57 passed.
- Lexer unit suite — 29 focused tests passed.
- Ruff and strict mypy checks for all three P12 source modules — passed.
- Valid examples tokenize with exact typed values and source positions.
- Unknown symbols, malformed numbers/operators, oversize input, excessive
  nesting, unbalanced parentheses, and injection syntax are rejected with
  stable codes.
- Source inspection test confirms no `eval` or `exec` call.
- P13 parser, AST, precedence, field validation, and `/rules/validate` endpoint
  were not started.

Database migrations: none. API changes: none. Commit hash: pending team commit.

## P13 — Custom parser, AST builder and static validation

Status: Implemented and locally verified on 29 October 2026.

### Delivered

- Recursive-descent parser honoring parentheses, `NOT`, comparisons, `AND`,
  and `OR` precedence.
- Immutable typed AST nodes with source spans and exact decimal serialization.
- Case-sensitive field registry resolution and unknown-field rejection.
- Boolean logical checks, matching comparison types, and Boolean comparison
  restrictions.
- Stable diagnostics for empty, incomplete, malformed, trailing, unknown,
  incompatible, over-token, and over-depth rules.
- Iterative AST depth measurement and configurable parser safety bounds.
- `POST /api/v1/rules/validate` with tokens, typed AST, and structured HTTP 422
  lexer/parser diagnostics.

### Files changed

- `backend/app/engines/rules/ast_nodes.py`
- `backend/app/engines/rules/parser.py`
- `backend/app/schemas/rules.py`
- `backend/app/api/v1/rules.py`
- `backend/tests/unit/test_parser.py`
- `docs/rule-language.md`
- `docs/api-contract.md`
- `docs/algorithm-complexity.md`
- `docs/phase-status.md`

### Acceptance evidence

- Full available backend suite — 84 passed.
- Focused parser/API suite — 27 passed.
- Ruff and strict mypy checks for all seven P12/P13 source modules — passed.
- `A OR B AND C` produces an OR root with an AND right branch.
- Parentheses override precedence and `NOT` binds before comparison.
- Unknown and type-invalid rules return location-specific diagnostics.
- Malformed operators, unexpected end, chained/trailing tokens, token limits,
  and deep ASTs are rejected deterministically.
- Strict mypy passes for all seven P12/P13 source modules.

P14 evaluation, explanation traces, rule persistence/versioning, activation,
authorization, and prioritization were not started. Database migrations: none.
Commit hash: pending team commit.

## P14 — Rule evaluation, versioning and deterministic priority

Status: Implemented and locally verified on 29 October 2026.

### Delivered

- Pure typed-AST evaluator with deterministic short-circuit explanation trees.
- Explicit missing-metric `ERROR` and three-valued `NO_MATCH` behavior.
- Strict runtime Boolean/integer/Decimal validation with no float coercion.
- Shared evaluation across reconciliation, circular-flow, and splitting facts.
- Configurable, versioned, bounded deterministic priority calculation.
- Immutable `DRAFT`, `ACTIVE`, and `RETIRED` rule versions.
- ADMIN-gated creation/activation and atomic prior-version retirement.
- Idempotent draft creation and payload-conflict detection.
- Evaluation records preserving rule-version ID, facts, matched facts,
  explanation, priority policy, and UTC timestamp.
- `POST /rules` and `POST /rules/{id}/activate` lifecycle routes.
- Repository port plus thread-safe in-memory transactional test adapter.

### Files changed

- `backend/app/engines/rules/evaluator.py`
- `backend/app/engines/rules/service.py`
- `backend/app/schemas/rules.py`
- `backend/app/api/v1/rules.py`
- `backend/tests/integration/test_rules.py`
- `docs/rule-language.md`
- `docs/api-contract.md`
- `docs/algorithm-complexity.md`
- `docs/phase-status.md`

### Acceptance evidence

- Full available backend suite — 99 passed.
- Focused evaluator/lifecycle/API suite — 15 passed.
- The same AST engine matches seeded reconciliation, circular, and splitting contexts.
- Activating changed text changes new results without modifying source code.
- Earlier evaluation evidence retains the earlier rule-version ID.
- Unauthorized create/activate operations fail; activated versions are immutable.
- Ruff and strict mypy pass across ten P12–P14 source modules.

The production Supabase rule/evaluation repository cannot be wired until the
P00–P09 database branch is merged. Its adapter must implement draft version
allocation, activation/retirement, idempotency, and evaluation writes with
database transactions and unique constraints. P18 must replace the temporary
actor-header adapter with authenticated session RBAC. No P15 heap work started.

Database migrations: none in this branch. Commit hash: pending team commit.

## P15 — Custom binary heap and synchronized queue

Status: Implemented and locally verified on 29 October 2026.

### Delivered

- Custom indexed binary max heap without `heapq` or library priority queues.
- O(log N) push/pop/remove/versioned-priority-update operations.
- Deterministic highest-priority then oldest-enqueue ordering.
- Unique case IDs and strictly increasing case-version replacement.
- Position-map and heap-order invariant validation.
- One explicit `Lock` protecting every heap read and mutation.
- `Condition` blocking pop with spurious-wakeup loop and timeout.
- Graceful shutdown that rejects producers, wakes consumers, and drains work.
- Thread-safe counters for throughput, rejection, waiting, timeout, contention,
  maximum depth, and current depth.
- Unit, randomized-reference, blocking, shutdown, and contention tests.

### Files changed

- `backend/app/engines/queue/binary_heap.py`
- `backend/app/engines/queue/synchronized_queue.py`
- `backend/tests/unit/test_heap.py`
- `backend/tests/stress/test_queue_contention.py`
- `docs/adr/0001-single-heap-owner.md`
- `docs/algorithm-complexity.md`
- `docs/phase-status.md`

### Acceptance evidence

- Focused heap/queue suite — 21 passed.
- Full available backend suite — 120 passed with one dependency deprecation warning.
- 25 producers and 25 consumers process 5,000 unique cases with no loss or duplicate.
- 20 threads replace priorities for 1,000 cases without invariant failure.
- Equal priorities pop by oldest enqueue sequence deterministically.
- Blocked consumers wake on work and shutdown; timeout is controlled.
- Source inspection confirms custom heap plus explicit `Lock`/`Condition`.
- Ruff and strict mypy pass for both P15 source modules.

P16 durable outbox consumption, database compare-and-swap claims, leases,
restart recovery, dead-letter handling, and case transitions were not started.
Database migrations: none. API changes: none. Commit hash: pending team commit.

## P16 — Durable outbox, case lifecycle and atomic work claims

Status: Implemented against the P02 repository boundary and locally verified on
29 October 2026.

### Delivered

- Stable case keys over normalized finding IDs and immutable rule-version ID.
- Atomic case + versioned outbox event + audit-intent repository operation.
- Idempotent case creation and outbox-to-heap projection.
- Persistent row-version compare-and-swap claims with bounded leases.
- Legal versioned case transitions and explicit conflict errors.
- Expired case-lease recovery with a new versioned outbox event.
- Outbox worker leases, abandoned-event replay, retry delay and dead-lettering.
- Worker restart rebuild from durable `QUEUED` cases.
- Composable case list, claim, and transition API routes.
- PostgreSQL CAS, `SKIP LOCKED`, uniqueness, and transaction adapter contract.

### Files changed

- `backend/app/services/case_service.py`
- `backend/app/services/outbox_service.py`
- `backend/app/engines/queue/claim_service.py`
- `backend/app/worker/main.py`
- `backend/app/api/v1/cases.py`
- `backend/app/schemas/cases.py`
- `backend/tests/integration/test_cases.py`
- `backend/tests/integration/test_outbox.py`
- `backend/tests/stress/test_concurrent_claim.py`
- `docs/api-contract.md`
- `docs/algorithm-complexity.md`
- `docs/phase-status.md`

### Acceptance evidence

- Focused P16 suite — 13 passed.
- Full available backend suite — 133 passed with one dependency deprecation warning.
- Simulated transaction failure leaves no case, outbox event, or audit intent.
- Crash after heap projection replays the abandoned event without duplication.
- A fresh worker rebuilds its lost heap from durable database truth.
- Fifty simultaneous claims yield exactly one winner.
- Two independent worker heaps racing one case yield exactly one database claim.
- Failed delivery reaches dead-letter state at the configured attempt bound.
- Ruff and strict mypy pass across all six P16 source modules.

The production Supabase adapter and migrations remain owned by the unmerged P02
branch. This phase supplies a typed repository protocol, a concurrency-faithful
in-memory adapter, and the exact PostgreSQL transaction/CAS contract so merge
integration does not couple orchestration to placeholder models.

P17 workflow DAG work was not started. Commit hash: pending team commit.

## P17 — Workflow DAG, topology and dependency unlock

Status: Implemented and locally verified on 29 October 2026.

### Delivered

- Custom adjacency-list workflow graph with strict node/edge validation.
- DFS color cycle detection with readable cycle paths.
- Deterministic Kahn topological ordering.
- Versioned draft/active/retired workflow templates.
- Atomic activation that preserves the prior active template on validation failure.
- Case workflow instances with versioned task states.
- All-prerequisites dependency unlocking, including the Track 2 ledger and
  whistleblower example.
- Validation, template creation, and case-workflow API routes.
- Concurrent prerequisite-completion coverage.

### Acceptance evidence

- Focused P17 suite — 10 passed.
- Full backend suite — 143 passed with one dependency deprecation warning.
- Ruff passed; strict mypy passed across seven P17 source modules.
- Injected `A -> B -> C -> A`-style cycles are rejected without changing the
  active workflow.
- Fifty simultaneous prerequisite completions unlock the dependent task once.

Database persistence remains behind the P02 integration boundary. No migration
was added in this branch. P18 authentication/RBAC/activity-ledger work was not
started. Commit hash: pending team commit.

## P18 — Authentication, RBAC and immutable activity ledger

Status: Implemented and locally verified on 29 October 2026.

### Delivered

- PBKDF2 password hashing and constant-time verification.
- Expiring server-side bearer sessions with logout invalidation.
- ADMIN, AUDITOR, REVIEWER and VIEWER permission matrix.
- Object-level maker-checker separation for sensitive actions.
- Append-only activity entries with actor, UTC time, request/object IDs,
  versions, old/new values and chained-hash verification.
- Explicit rejection of activity update/delete operations.
- Login, logout and authorized activity-list APIs with 401/403 behavior.
- Optimistic workflow instance conflicts for 409 adapters.
- Concurrent activity and workflow-conflict tests.

### Acceptance evidence

- P18-focused tests — 7 passed; combined P17/P18 suite — 17 passed.
- Full backend suite — 150 passed with one dependency deprecation warning.
- Ruff and strict mypy passed across six changed source modules.
- Two simultaneous workflow changes with one version yield one winner.
- 100 concurrent ledger appends preserve a valid complete hash chain.

Production session storage, DB role restrictions, and atomic state-change plus
activity insertion must use the P02 Supabase transaction adapter when merged.
The hash chain is integrity evidence, not a claim of full tamper-proofness.

Commit hash: pending team commit.

## P19 — Frontend application and audit operations UI

Status: Live API-integrated application implemented and locally verified on
30 October 2026; private Sites publication was not requested.

### Prepared

- Complete route, screen, input, output, role, validation, and error-state map.
- API integration, idempotency, authentication, money/time, and pagination
  rules.
- Accessibility, responsive behaviour, security, testing, and design-delivery
  requirements.
- Explicit backend-readiness dependencies preventing unsupported UI behaviour.
- Responsive light audit dashboard matching the supplied neutral/lime reference.
- Dashboard, ingestion, transactions, findings, cases, rules, and activity
  routes with shared navigation and accessible responsive states.
- Typed API integration for login, metrics, ingestion, transactions, duplicate
  evidence, reconciliation, circular/splitting detectors, combined findings,
  case creation/claim, rules, workflow validation and activity history.
- Fifteen responsive application routes with loading, empty and error states.
- Next.js static production export; strict TypeScript check and build passed.

The authoritative contract remains `docs/phase19-frontend-requirements.md`.
The browser is connected to the composed API through `NEXT_PUBLIC_API_BASE_URL`.

## P20 — Stress, adversarial tests, performance and deployment

Status: Partially implemented and locally verified on 30 October 2026; final
release is blocked by production persistence and deployment verification.

### Delivered

- Repeatable eight-algorithm time/peak-memory benchmark runner and JSON report.
- Frozen circular/splitting expected evidence and fixture validator.
- Adversarial simultaneous re-import test preserving source identities.
- Repository-wide backend/frontend verification and secret-shape scan.
- Read-only Supabase version, connection-limit and migration verification.
- Repeatable 8–12 minute demo playbook and explicit release test report.
- Make targets for frontend, fixtures, benchmarks and release checks.

### Acceptance evidence

- Backend suite — 221 passed with one dependency deprecation warning.
- Ruff passed; strict mypy passed across 99 app/script source files.
- Frontend TypeScript and production export passed for fifteen app routes.
- Supabase PostgreSQL 17.11, 60 connections and `0002_ingestion (head)`.
- Eight custom-algorithm workloads are covered, including reconciliation.
- `.env` is ignored and no credential-shaped values were found in source.

### Blocking release gaps

- Production Supabase adapters are incomplete.
- The main API route surface is composed, but detector/reconciliation loaders
  still need durable canonical snapshots.
- Docker runtime, Supabase backup/PITR, Python 3.12 container verification and
  deployment remain unverified.
- Private Sites publishing remains paused pending explicit source approval.

See `docs/test-report.md` for the acceptance decision. P20 remains partial until
the production connections and deployment checks are closed.
