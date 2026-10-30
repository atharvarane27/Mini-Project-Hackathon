# Finstack Project Execution Guide

## 1. Project overview

Finstack is a banking audit review platform. It imports ledger data, normalizes
valid records, identifies possible duplicates, compares independent ledgers,
detects suspicious transaction patterns, evaluates configurable audit rules,
and organizes review work into cases and workflows.

The platform is an evidence and review tool. A duplicate match or detector
finding is a signal for human investigation, not an automatic fraud verdict.
The project requirements and domain scope are described in [PRD.md](../PRD.md).

## 2. Technology stack

| Area | Technology | How it is used |
|---|---|---|
| Frontend | Next.js, React, TypeScript | Renders the dashboard and feature pages, manages browser interactions, and calls the API through typed client functions. |
| API | FastAPI, Python, Pydantic | Exposes versioned HTTP endpoints, validates inputs, coordinates services, and formats API responses. |
| Audit algorithms | Python standard library | Implements the matching, reconciliation, graph, window, rule, heap, and workflow algorithms. |
| Database access | SQLAlchemy 2, Psycopg 3 | Provides PostgreSQL engine and connection support. |
| Schema migrations | Alembic | Manages versioned PostgreSQL schema changes. |
| Database | PostgreSQL, intended Supabase deployment | Intended durable store for business data; current feature runtime primarily uses in-memory repositories. |
| Local orchestration | Make and Docker Compose | Provides development, checks, migration commands, and service definitions. Docker runtime verification is still outstanding. |

The frontend API client is [frontend/src/lib/api.ts](../frontend/src/lib/api.ts).
The FastAPI application and shared service composition are in
[backend/app/main.py](../backend/app/main.py) and
[backend/app/runtime.py](../backend/app/runtime.py).

## 3. System architecture and execution flow

The intended data flow is:

```text
CSV upload
  -> row parsing, validation, normalization
  -> accepted source records and quarantined invalid rows
  -> canonical transactions and journal postings
  -> duplicate analysis, reconciliation, and pattern detection
  -> findings and rule evaluation
  -> case creation and prioritization
  -> queue and workflow tasks
  -> append-only activity history
```

In the current local demo, the browser sends requests to FastAPI under
`/api/v1`. The API routes call service objects created at startup by
`RuntimeServices`. The services run the domain algorithms and return data to
the frontend. The frontend displays those results.

The architecture document describes the intended production topology as
Next.js -> FastAPI -> PostgreSQL/outbox -> a single-owner worker. PostgreSQL is
intended to be the durable authority, while in-memory indexes, graphs, and
heaps are restartable projections. See
[docs/architecture.md](./architecture.md).

## 4. Local execution

From the project root:

1. Copy `.env.example` to `.env` and configure the required environment values.
2. Install backend dependencies with `make install`.
3. Start the API with `make api`. The health route is
   `http://127.0.0.1:8000/api/v1/health`.
4. In another terminal, enter `frontend` and run `npm run dev`.
5. Open `http://localhost:3000/login/`.
6. Use the interface to import fixture data and explore the audit features.

Useful checks and commands from the root `Makefile`:

| Command | Purpose |
|---|---|
| `make verify` | Runs backend lint, strict type checking, and tests. |
| `make frontend-check` | Runs frontend TypeScript checking and production build. |
| `make migrate` | Applies Alembic migrations to the configured database. |
| `make demo-fixtures` | Runs the demo seeding script. |
| `make benchmark` | Runs algorithm benchmarks and writes benchmark results. |
| `make release-check` | Runs verification, frontend checks, fixture seeding, and benchmarks. |

The detailed quick start is in [README.md](../README.md).

## 5. Login and access behavior

The login UI is at
[frontend/src/app/login/page.tsx](../frontend/src/app/login/page.tsx).
It currently uses a **dummy client-side demo flow**:

1. The user enters a username and password.
2. The page checks that neither value is empty.
3. It sets a demo token in frontend memory.
4. It redirects the user to the dashboard.

Any non-empty credentials work. This is not secure authentication and should
not be treated as access control. The demo token is not a server-issued token,
so backend endpoints that require a real authenticated session may reject
requests.

The backend has a separate authentication endpoint at
`POST /api/v1/auth/login`; its route is implemented in
[backend/app/api/v1/auth.py](../backend/app/api/v1/auth.py). Authentication
service and role definitions are in `backend/app/core`. The demo login page
does not currently call this backend endpoint.

## 6. CSV ingestion

The ingestion page accepts a CSV file and a source-system name. The API accepts
the upload as multipart form data.

The backend ingestion process:

1. Reads CSV rows in bounded batches instead of loading the entire file into
   memory.
2. Validates columns, types, timestamps, amounts, and other required values.
3. Normalizes valid rows into source-transfer records.
4. Quarantines invalid rows with row-level diagnostic information.
5. Detects exact replays and conflicting reuse of a source identity/revision.
6. Tracks job status and processed, accepted, rejected, and duplicate counts.

The ingestion service uses a default batch size of 500 and supports
idempotency keys so retrying the same operation does not silently create
another job. Its implementation is in
[backend/app/ingestion/service.py](../backend/app/ingestion/service.py).

Typical required CSV fields include `external_id`,
`transaction_reference`, `sender_account_id`, `receiver_account_id`, `amount`,
`currency`, and timezone-aware `occurred_at`. Example files are in
[fixtures/](../fixtures/). The small `test_all_features.csv` fixture is
intended to exercise multiple feature paths.

## 7. Canonical transactions and journal integrity

A single economic transfer may be represented in multiple imported source
records. Canonicalization represents the economic event once while retaining
the source-record IDs as provenance.

The canonicalization process:

1. Validates source identity, revision, amount, currency, and timestamp.
2. Computes stable fingerprints for source and transaction payloads.
3. Reuses an existing canonical event for an exact replay or equivalent event.
4. Links additional source records to the canonical event rather than
   double-counting it.
5. Creates debit/credit journal postings and checks that a journal balances.

This behavior is implemented in
[backend/app/ingestion/canonicalizer.py](../backend/app/ingestion/canonicalizer.py).
The Transactions page displays canonical economic events and their
transaction-level attributes.

## 8. Duplicate resolution

Duplicate resolution produces comparison evidence; it does not delete or merge
source records.

The identity engine:

1. Builds deterministic blocking keys for each record.
2. Uses an inverted index to retrieve a bounded set of plausible candidates,
   instead of comparing every record with every other record.
3. Compares candidate attributes using exact checks and bounded string
   similarity, including phonetic blocking and Levenshtein distance.
4. Returns deterministic classifications, scores, reasons, and algorithm
   versions.

Classifications include `EXACT`, `CANDIDATE`, `AMBIGUOUS`, and `NON_MATCH`.
Scores are rule points and edit-distance results, not probabilities. The
implementation is under
[backend/app/engines/identity/](../backend/app/engines/identity/). The
Duplicates page presents the compared records and the reasons behind the
classification.

## 9. Ledger reconciliation

Reconciliation compares two source ledgers across a requested time interval.
The matching engine compares transaction references and other transfer
attributes, then classifies matched, missing, or mismatched records. Journal
checks can also detect unbalanced accounting entries.

Execution:

1. The user selects two source-system IDs and a time range.
2. The frontend sends a reconciliation run request.
3. The backend loads entries for both sources.
4. The matcher applies the configured reconciliation policy.
5. The service stores a run result and returns classification counts and
   evidence.

The API router is `backend/app/api/v1/reconciliation.py`; the algorithms are
under [backend/app/engines/reconciliation/](../backend/app/engines/reconciliation/).
The UI presents the classification counts after a run.

## 10. Circular-transfer detection

The circular detector models accounts as graph nodes and transfers as directed
edges from sender to receiver. Each edge carries transaction, time, amount,
and currency information.

Execution:

1. Transfers in the selected time range are loaded.
2. A directed transfer graph is built.
3. A bounded depth-first search finds candidate cycles.
4. A temporal and monetary policy validates candidate cycles.
5. Valid candidates are stored as findings with ordered transaction evidence.

The graph search is bounded by policy limits because cycle enumeration can
grow quickly in dense graphs. A cycle is an audit signal, not proof of
wrongdoing. Code is under
[backend/app/engines/circular/](../backend/app/engines/circular/).

## 11. Transaction-splitting detection

The splitting detector searches for groups of related transfers that occur
within a configured time window and meet policy criteria, such as a combined
amount threshold.

Execution:

1. Canonical transfers are filtered by time, status, currency, and policy.
2. Eligible transfers are partitioned by configured attributes, such as
   sender and currency.
3. Each partition is ordered deterministically by timestamp and transaction
   ID.
4. A sliding window tracks the running total and events inside the window.
5. Qualifying windows are deduplicated/suppressed according to the detector
   policy and emitted as findings.

The window implementation uses a deque and running integer amount totals. It
does not silently discard late or over-limit data. Code is under
[backend/app/engines/splitting/](../backend/app/engines/splitting/).

## 12. Findings

Findings are structured outputs from detector runs. A finding records:

- Finding type and status.
- Transaction IDs involved.
- Typed facts and evidence.
- Detector configuration and algorithm versions.
- A stable fingerprint for deterministic deduplication.

Findings provide the explanation and evidence needed for review. They are
separate from cases: a case is a unit of human investigation that can include
one or more findings.

## 13. Rules and rule lifecycle

Audit rules use a custom expression language. They are not evaluated with
Python `eval` or `exec`.

The rule execution stages are:

1. **Lexing:** Converts text into typed tokens.
2. **Parsing:** Applies operator precedence and creates an abstract syntax
   tree (AST).
3. **Static validation:** Resolves identifiers against a field registry and
   checks operand types.
4. **Evaluation:** Walks the AST against a facts snapshot and produces a
   Boolean result and explanation.
5. **Versioning:** Stores rule drafts and supports activation of immutable
   versions.

Supported operators include comparisons and Boolean `AND`, `OR`, and `NOT`.
Numeric values support exact integer/decimal semantics. The parser rejects
unknown fields and invalid type combinations. Modules are in
[backend/app/engines/rules/](../backend/app/engines/rules/); language details
are in [docs/rule-language.md](./rule-language.md).

## 14. Cases and priority queue

Cases organize findings for investigation and move through a controlled
lifecycle. Case claims use expected versions so a stale or competing claim
cannot silently overwrite a newer state.

The queue engine includes a custom binary max-heap and a synchronized wrapper:

- The heap keeps high-priority cases at the top.
- A case-ID-to-position map supports efficient updates and removal.
- A lock coordinates concurrent producers and consumers.
- Consumers can wait for work instead of continuously polling the heap.

The queue implementation is under
[backend/app/engines/queue/](../backend/app/engines/queue/), and case service
code is under [backend/app/services/](../backend/app/services/).

## 15. Workflow DAG

Workflows describe task prerequisites, not money movement. They use a separate
graph from the circular-transfer detector.

The workflow service:

1. Accepts workflow task nodes and prerequisite edges.
2. Checks for cycles.
3. Rejects invalid cyclic dependency structures.
4. Computes a topological order for valid workflows.
5. Tracks prerequisite completion so dependent tasks can be unlocked.

The workflow implementation is in
[backend/app/engines/workflow/](../backend/app/engines/workflow/).

## 16. Activity history and API conventions

The activity ledger records important actions and is designed to be append-only.
Audit history should not be silently edited or deleted.

The API uses the `/api/v1` prefix and standard success/error response
envelopes. It also uses request IDs for tracing and idempotency keys for
retry-safe mutations. Pagination, timestamps, and money values follow the
contracts in [docs/api-contract.md](./api-contract.md).

The frontend includes routes for dashboard, ingestion, transactions,
duplicates, reconciliation, findings, circular and splitting detectors, cases,
rules, workflow, stress diagnostics, audit log, and login. The UI composition
and data loading components are in
[frontend/src/components/audit-app.tsx](../frontend/src/components/audit-app.tsx).

## 17. Persistence and production status

The codebase includes SQLAlchemy database connection setup and Alembic
migrations, but database infrastructure does not imply that every feature
persists its business data in PostgreSQL.

At the time of this guide:

- `RuntimeServices` composes in-memory repositories for ingestion,
  canonicalization, duplicate analysis, reconciliation, detector runs, rules,
  cases, and workflows.
- The database engine can be configured, and the health endpoint can check
  connectivity.
- Alembic migration support exists.
- The dedicated worker has service classes for queue/outbox work, but its
  current process entry point waits for shutdown signals instead of composing a
  live persistent polling loop.
- Docker Compose is defined but was not verified on the documented workstation.
- Final production persistence, worker integration, and deployment checks
  remain incomplete.

Therefore, a local demonstration can show the algorithms and API flows, but
the current in-memory service data is not production-durable across API
restarts. Check
[docs/integration-connections.md](./integration-connections.md) and
[docs/test-report.md](./test-report.md) for the latest integration status.

## 18. Test and verification status

The project test report records 221 backend tests passing at the time of its
run, with backend lint/type checks and frontend TypeScript/build checks
reported as passing. It also lists concurrency tests for case claims, queue
producers/consumers, detector retries, and workflow dependencies.

These are local verification results; they do not establish production
latency, capacity, backup readiness, or deployment success. Refer to
[docs/test-report.md](./test-report.md) for the recorded environment,
limitations, and release blockers.

## 19. Dataset and fixture notes

The project includes small feature fixtures and a larger synthetic dataset.
Synthetic labels are for fixture selection and expected-outcome testing only;
they must not be used as matching inputs or production decision signals.
Scenario proportions in synthetic data do not represent real-world anomaly
rates. See [docs/dataset.md](./dataset.md) and
[fixtures/README.md](../fixtures/README.md).

## 20. Hackathon compliance reminder

The project PRD includes a notice that the official hackathon brief may
prohibit the use of generative AI assistants. Confirm the applicable rules and
obtain organizer approval if required before using AI-generated work. See the
notice in [PRD.md](../PRD.md).
