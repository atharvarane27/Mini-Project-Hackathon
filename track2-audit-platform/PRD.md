PRODUCT REQUIREMENTS DOCUMENT (PRD)

Track 2 — Concurrent Banking Audit, Record Resolution & Rule-Driven Workflow Platform

Version: 1.0 | Status: Implementation blueprint | Date: 29 October 2026Product codename: AuditForge (working name; optional)Source of mandatory scope:HACKATHON PROBLEM STATEMENT.pdf, pp. 1–5, especially Track 2 row on p. 3.

Competition compliance notice: The official brief forbids the use of generative AI assistants during the hackathon. This document is a planning specification, not permission to use Codex. Before feeding it to Codex or using generated implementation, obtain explicit written confirmation from the organizers that this workflow is allowed. If that prohibition applies, the team must implement the system manually.

Requirement labels

[M] Explicit mandatory hackathon specification.

[E] Requested extra feature.

[D] Implementation decision/recommendation for a reproducible build; not specified by organizers.

[T] Verification/acceptance test.



1. Executive summary

Build a deterministic, multi-branch banking audit application that ingests a stream of noisy financial records, identifies potential duplicates through a custom memory-resident index, reconciles corresponding ledgers, detects circular fund flows and transaction splitting, evaluates administrator-entered audit expressions via a custom lexer/parser/AST, schedules cases using a thread-safe heap, enforces audit dependencies with DAG validation, and records state changes in an append-only audit ledger. Provide a role-restricted dashboard and observable multi-thread stress-test simulation.

Success means: a judge can inject duplicates, malformed rules, conflicting edits, concurrent case claims, and cyclic workflow dependencies; the application handles them deterministically, without corrupting data or deadlocking.

1.1 Goals

[M] Working low-memory record-resolution index with phonetic blocking and bucket-local string comparison.

[M] Runtime-editable text rules compiled by a custom lexer/parser into an AST.

[M] Correct thread-safe in-memory min/max heap under many simultaneous producers and consumers.

[M] DAG-based multi-prerequisite workflow, topological sorting, active cycle rejection.

[M] Secure RBAC, 3NF relational schema, immutable append-only activity history.

[E] Automated reconciliation of independent ledger sources.

[E] Circular transfer detection in a time-respecting account transaction graph.

[E] Windowed transaction splitting detection.

[D] Full end-to-end UI, deterministic sample generator, metrics and repeatable demos.

1.2 Non-goals and exclusions

No ML/AI scoring, embeddings, pretrained services, LLM APIs, OCR AI, or adaptive models.

No live banking-system integration, actual payments, real customer data, regulatory reporting or real fraud adjudication.

No full accounting core-banking platform. Use a synthetic test fixture dataset as representative data; do not invent claims of real fraud.

No hardcoded domain rule if/else chains. Parser implementation may naturally use control-flow branches to recognize grammar; prohibited hardcoding refers to business rules that administrators should be able to change dynamically.

2. Users, access and workflows

Role

Allowed operations

Restrictions

ADMIN

Upload source data, create/activate rules and workflow templates, assign roles, run test jobs, view logs

May not delete historic audit log or silently alter a previously activated rule version

AUDITOR

Browse assigned cases, inspect transactions and evidence, take review actions, acknowledge/resolve permitted tasks

Cannot activate rules or change roles; cannot approve their own maker-checker action if enabled

REVIEWER

Verify higher-risk findings, approve/decline escalation tasks

Cannot bypass DAG prerequisites

VIEWER

Read redacted dashboards and aggregate metrics

No mutations or unrestricted personal data

SYSTEM_WORKER

Process queues, emit findings and transition authorized automated states

Scoped internal service permissions only



Primary journey: source import → validated canonical events → Layer A candidate resolution → reconciliation and pattern detectors → findings → AST rule evaluation and priority calculation → heap → case assignment → DAG tasks → final review → audit history.

Important semantics: a duplicate source row must not automatically become a second economic transfer in graph or window analysis. Keep raw records, canonical event IDs, and audit findings as distinct entities. All suspicious-pattern outputs are flags for human review, not fraud verdicts.

3. Technology stack and operational decisions [D]

Layer

Technology

Reason / implementation constraint

Frontend

Next.js (TypeScript, App Router), React, Tailwind CSS, Recharts, React Flow

Dashboard, typed APIs, interactive graph and workflow views

API/backend

Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic

Explicit modules, schema validation and persistence

RDBMS

Supabase managed PostgreSQL

Hosted PostgreSQL with 3NF, foreign keys, ACID transactions and SQL migrations; Supabase is the provider, PostgreSQL remains the database engine

In-process algorithms

Python standard library dict, custom posting lists, threading, heapq or explicit custom binary heap, collections.deque, decimal

All core logic deterministic and locally inspectable. Implement custom heap operations for best defense

Background worker

Python process hosting bounded worker threads and own heap

Clear concurrency boundary and controlled thread ownership

Work dispatch

Supabase PostgreSQL durable outbox + worker polling

No mandatory Redis/Kafka; allows recoverability after crash

Authentication

FastAPI-managed local seeded accounts, Argon2 password hashing, secure httpOnly session cookies

Supabase Auth is optional and not required for MVP; fine-grained RBAC enforced in FastAPI

Testing

pytest, hypothesis optional, httpx, Playwright; Locust or custom thread stress harness

Unit/integration/property, live contention demo

Quality

Ruff, mypy, ESLint, TypeScript checks, pre-commit

Deterministic CI quality gates

Operations

Docker Compose: frontend, api, worker; remote Supabase PostgreSQL; optional local PostgreSQL fallback profile

Repeatable app deployment; cloud DB plus offline-demo option



3.1 Supabase persistence specification [D]

Database provider: Supabase managed PostgreSQL. Keep all business algorithms (inverted index, Soundex, Levenshtein, AST, custom synchronized heap, fund-flow graph, sliding windows, DAG) in FastAPI/worker memory; do not substitute Supabase search, Edge Functions, Realtime, or database stored procedures for the compulsory custom engines.

Connection: FastAPI and worker use SQLAlchemy 2 + psycopg v3 through a PostgreSQL connection string obtained from Supabase Dashboard → Connect. Use the direct session endpoint when IPv6 networking is available and connection counts are controlled; otherwise use the Supabase-supported session pooler. Verify endpoint, port and SSL settings using the current dashboard values, rather than hardcoding a hostname or port. Transaction-pooling endpoints can impose prepared-statement/session-state restrictions; do not assume interchangeability.

Configuration:.env.example documents DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:<port>/<database>?sslmode=require, DATABASE_POOL_SIZE=5, DATABASE_MAX_OVERFLOW=5, DATABASE_POOL_TIMEOUT=30, DATABASE_POOL_RECYCLE=1800, DB_BACKEND=supabase. Angle-bracket placeholders are not literal credentials. Configure API and worker pools separately, within the project's connection budget. Do not commit .env, connection strings containing credentials, Supabase service-role secrets, or JWT signing keys.

Migrations: Alembic owns application tables, constraints, FK behavior, indexes, and revisions. Apply migrations to a test Supabase project before production/demo. Avoid editing application schema ad hoc through the dashboard after migrations exist. Add infra/supabase/bootstrap.sql only for minimal role grants / optional policies that need controlled SQL setup; use infra/supabase/README.md for project creation and connection steps.

Security: FastAPI is the sole write/read API for application data in MVP, authenticates users and enforces RBAC. Use least-privileged DB credentials for the running API and worker; a separate migration/owner role manages DDL. Do not use an unrestricted Supabase service-role key in the browser. If direct browser data access is introduced later, enable and test RLS policies for every exposed table and coordinate them with backend authorization. Supabase Auth and Storage are optional future additions, not implementation requirements.

Immutability: keep Activity_Log append-only by application logic and DB permissions/triggers. Row-level security alone is not sufficient against privileged writes. Commit case transitions + corresponding activity rows in one SQL transaction.

Concurrency: Supabase is persistent truth for case state, outbox and worker leases, but the required heap still lives in one backend worker process protected by its own mutex/condition. Use optimistic version checks / UPDATE ... RETURNING and DB row locks where needed; one Python thread lock does not coordinate multiple deployment replicas.

Network resilience: Supabase needs network access. For a venue without reliable internet, add an optional local PostgreSQL fallback in Compose using the same Alembic migrations. Local fallback must preserve SQL semantics and be clearly labeled as contingency mode; do not silently switch stores during transactions.

Verification: acceptance requires a successful Supabase connection from both FastAPI and worker, applied migrations, rollback tests, FK integrity checks, role-denied operations, exactly-once case claims under race conditions, audit append-only protection, and reconnection/restart behavior. Log connection-pool exhaustion as a controlled error and do not expose credentials.

Important concurrency limitation: Keep one authoritative heap owner per worker process. A Python threading.Lock does not synchronize separate processes or replicas. The persistent database remains the source of truth for cases/jobs, and a row-claim lease/outbox ensures safe restart. Start with one worker process and multiple threads; horizontally scaling heap ownership is out of scope.

4. Architecture and processing contract

CSV / simulated branch feeds     |     v[API: Validation + normalization + idempotent ingest]     |     +--> [Supabase PostgreSQL: raw source records + canonical transactions + journal lines]     |     v[Layer A: Custom RAM inverted index -> blocking -> bucket-local edit distance]     |     +--> duplicate candidate findings (never silently merge)     |     +--> [Extra: Reconciliation matcher] -> missing/mismatch/balanced findings     |     +--> [Extra: Account transfer graph] -> time-respecting cycle findings     |     +--> [Extra: Partitioned sliding windows] -> split pattern findings     |     v[Finding facts + versioned admin text rules -> Lexer -> Parser -> AST -> evaluator]     |     v[Case creation transaction + outbox] -> [thread-safe heap / claim workers]     |     v[DAG tasks: predecessor completion -> topological scheduling -> case resolution]     |     +--> [append-only activity log] + [RBAC checks]     v[Next.js: overview, ledger reconciliation, pattern graphs, rules, queue, workflow, logs, stress metrics]

4.1 Canonical shared data contracts [D]

All financial amounts use integer minor units (for INR, paise), not floating-point; all timestamps are persisted UTC in timestamptz, shown to users in local timezone; currency is ISO 4217. Each transfer stores sender_account_id, receiver_account_id, posted timestamp, status, transfer kind, external reference, and unique canonical event identifier. Journal lines are separate debit/credit postings to avoid assuming a transfer maps to exactly two lines.

Use source_record_id to preserve ingestion rows, transaction_id for one canonical economic transfer, journal_id for accounting posting groups, finding_id for detector output, case_id for review work. Create stable SHA-256-based idempotency fingerprints from source-system identifier + immutable external event identifier + source revision; if this identifier is unavailable, flag for manual identity resolution rather than relying solely on amount/time.

4.2 Event ordering and consistency

Persist inbound rows in an ACID transaction with a durable outbox event.

Build/update in-memory index after commit, processing outbox events idempotently.

Reconstruct RAM index on startup via bounded batches; never load every source record at once.

Process detectors using committed canonical transactions; keep a per-partition checkpoint and event watermark.

When a late record falls before a watermark, mark affected findings for deterministic recomputation rather than silently ignoring it.

Findings must record algorithm_version, rule_version_id, relevant parameters, input txn IDs, source checkpoint/window, and evidence so outputs can be reproduced.

5. Functional requirements by module

M01 — Ingestion, normalization and canonical transaction model [D; prerequisite]

Inputs: CSV upload or simulator event (source_system, branch_id, external_txn_ref, account/party labels, sender, receiver, amount, currency, txn_time, posting_time, direction, status, description).

Processing: parse/schema validate; reject negative or malformed amounts; normalize whitespace and casing of identifiers, decimal currency to minor units, dates to UTC; check known branches/accounts; derive safe fingerprint; persist source row and canonical mapping; emit outbox ingestion event. Retried exact import is idempotent; changed rows with same external ID become a conflict/revision review, not silent overwrite. Record import row-level errors.

Outputs: ingest job ID, accepted/rejected/duplicate counts, stable records, outbox events. Acceptance: a 10,000-row mixed CSV can be imported without whole-file memory loading; repeats don't double-count economic events.

M02 — Mandatory Layer A: low-memory duplicate/identity resolution [M]

Goal: find duplicate/inverted/misspelled ledger records across branches without a naive all-record cross-product or DB-only matching.

Data structure: custom InMemoryInvertedIndex with posting_map: dict[BlockingKey, set[RecordID]], capped/incremental RAM record summaries, reference pointers to persisted detail; optional prefix Trie for name tokens. Block by account/party key, currency, amount band, date bucket and Soundex of name/description token; allow multiple blocking keys per record for recall (e.g., neighboring date or amount bands). Soundex is useful for names, not numeric transaction fields.

Algorithm: for each new row, derive keys → union candidate posting lists → bound candidates and fetch minimal fields → compare account/amount/time/direction and compute custom Levenshtein for relevant descriptions within buckets → emit potential duplicate cluster (exact, fuzzy, needs review) with individual features and decision reason. Avoid auto-merging legitimate debit-credit pairs or reversal entries. Field inversion handling should use normalized pair keys for source/destination plus accounting semantics.

Bounds: hashing average O(1) per key; candidate lookup O(sum posting-list sizes); Levenshtein O(|s||t|) per candidate and can use two-row O(min(|s|,|t|)) memory. Overall O(N log N) or better is a target under bounded bucket sizes; don't falsely promise worst-case O(N log N) if adversarial collisions create huge buckets. Protect with bucket size caps, secondary partitioning, metrics and counterexamples. Lock index partitions for concurrent insertion or use snapshot swap.

Tests: exact duplicates; misspelled descriptions; field inversions; same amounts but unrelated counterparties; oversized bucket; stream replay; concurrent index mutation; memory tracking.

M03 — Extra: automated ledger reconciliation [E]

Goal: compare independent ledger representations, not just remove duplicates.

Inputs: pair of ledger sources, reconciliation period and cutoff, matching policy version, journal lines and external reference fields.

Execution: (1) filter posted valid events in two sources; (2) exact match by stable external reference + source and currency; (3) compare direction, amount, counterparties and posting dates; (4) for unmatched records use a composite key and Layer A candidate index; (5) enforce one-to-one matches (mark consumed IDs), quarantine ambiguous many-to-one candidates for review; (6) apply cutoff to distinguish PENDING_LATE from UNMATCHED; (7) validate postings per journal group: sum debit == sum credit; (8) persist results and amount variance; (9) emit findings for mismatches, imbalances, missing rows.

Statuses:MATCHED, AMOUNT_MISMATCH, FIELD_MISMATCH, INTERNAL_ONLY, COUNTERPART_ONLY, PENDING_LATE, AMBIGUOUS, UNBALANCED_JOURNAL.

Example: internal T102 = INR 25,000 vs clearing T102 = INR 24,500 → AMOUNT_MISMATCH, 50,000 minor-unit variance. Internal T103 absent, past cutoff → INTERNAL_ONLY. An independent T104 counterpart-only → COUNTERPART_ONLY.

Algorithm/scale: exact-key average O(N+M), excluding DB I/O. Matching ambiguous candidates is bounded by configurable candidate cap; if optimal one-to-one matching is introduced, document separate matching cost. Idempotent runs keyed by ledger pair + period + policy version + input checkpoint. Acceptance: exact matches, one-to-one disputes, missing records, late arrivals, reversal sign conventions, and journal imbalance all pass tests.

M04 — Extra: circular fund-flow detection [E]

Goal: flag valid temporally ordered transfer cycles, not merely account graph cycles.

Graph: directed multigraph accounts V; posted canonical transfer edges E with txn ID, amount, timestamp, currency; do not use debit-credit accounting lines as independent transfers. Restrict by currency, time window and optionally bank-branch/account cohort. Store adjacency lists partitioned by time/currency; DFS colors WHITE/GRAY/BLACK for cycle existence. Consider Tarjan SCC as a pruning stage; DFS/SCC O(V+E) for a graph snapshot but enumerating all simple cycles can be exponential: enforce maximum depth, time window, candidate cap, and cancellation.

Temporal and amount validation: valid path must use different canonical transfer IDs, strictly nondecreasing timestamps (tie-break txn ID), return to original account, complete within configured max_cycle_minutes, respect min_initial_amount_minor and max_amount_drop_percent or amount-flow plausibility. Deduplicate rotated representations of same cycle using canonical ordered transaction ID tuple starting at smallest ID. Suspicious pattern is not proof of fraud.

Outputs:CIRCULAR_FLOW finding with participating accounts/txn IDs, cycle length, start/end, duration, amount variation, detector config version; render interactive path graph. Acceptance: A→B→C→A in correct time order flags; a graph-only cycle with invalid order does not; self-transfer and reversal test cases handled explicitly; budgets stop pathological exploration.

M05 — Extra: transaction splitting detector [E]

Goal: flag related transfers which individually fall below a configured threshold yet combined within a time window cross a deterministic aggregate threshold.

Partition key: configurable sender + receiver + currency + txn_type (or sender-only policy). Track only accepted posted canonical transactions; apply policy-specific inclusion/exclusion of reversals, fees, cash and internal movements. Admin parameters: window_minutes default 60, amount_threshold_minor demo 10,000,000 (INR 100,000), min_count default 3, individual_max_minor default under threshold, group_mode.

Algorithm: per-key time-ordered deque; for each txn add amount and count; evict items older than window; if count >= min_count AND sum >= threshold with eligible individual entries, emit a finding. For sorted arrivals O(K) for K events in one group; unsorted data needs O(K log K) sort or bounded out-of-order buffering. Use inclusive window boundary and >= threshold as explicit conventions.

Avoid alert floods: stable finding fingerprint (policy_version, group key, first/last associated txn ID or canonical cluster ID); merge overlapping alerts into a case with evidence set, and allow recomputation when late events arrive. Acceptance: 40k+35k+30k INR within 60 minutes flags at 100k; same outside window not flagged; exact boundary, duplicate ingestion, reversal, different receiver, mixed currency, and out-of-order arrival tested.

M06 — Mandatory Layer B1: runtime text rule language + AST [M]

No hardcoded rules: admin adds versions of expressions, not Python eval/exec. Create custom Lexer, recursive-descent/Pratt Parser, typed AST, safe interpreter.

Grammar (minimal):

expr        := or_expror_expr     := and_expr ("OR" and_expr)*and_expr    := not_expr ("AND" not_expr)*not_expr    := "NOT" not_expr | comparisoncomparison  := primary ((">"|">="|"<"|"<="|"=="|"!=") primary)?primary     := IDENT | NUMBER | BOOL | "(" expr ")"

Operator precedence: parentheses > NOT > comparisons > AND > OR. Lexer positions used in errors. NUMBER is decimal/integer, not a quoted Python expression. Rule context is a registry of typed fields; reject unknown identifiers, invalid types, unsupported tokens, deep trees, too-long rules, division (not in MVP grammar), or unbalanced brackets.

Required Track 2 variable support:Variance_Threshold, Balance_Anomaly_Flag, Transaction_Velocity. Additional fields: Reconciliation_Variance_Minor, Circular_Flow_Detected, Cycle_Length, Cycle_Duration_Minutes, Splitting_Window_Sum_Minor, Splitting_Window_Count, Duplicate_Candidate_Flag, Severity. Define Variance_Threshold carefully as measured variance in normalized units for the sample expression, while admin-configured maximum lives in a separate named field (Allowed_Variance_Minor) to avoid ambiguity.

Example admin rule:(Reconciliation_Variance_Minor > 50000 AND Balance_Anomaly_Flag == TRUE) OR (Circular_Flow_Detected == TRUE AND Cycle_Length >= 3) OR (Splitting_Window_Sum_Minor >= 10000000 AND Splitting_Window_Count >= 3).

Rule version lifecycle: DRAFT → VALIDATED → ACTIVE → RETIRED; immutable activated expression; evaluation stores version and facts snapshot. Admin can dry-run against sample case before activation. Syntax errors return line/column with 422, not server exception. Acceptance: precedence, parentheses, unary NOT, type errors, injection attempts, empty rules, concurrent activation and deterministic replay.

M07 — Mandatory Layer B2: thread-safe in-memory priority heap [M]

Use explicit binary Max Heap class (push, peek, pop, update_priority, size, validate_heap) with internal array and case ID → position map. Each entry = (priority integer, enqueue_sequence integer, case_id, case_version); deterministic tie break by oldest enqueue sequence. Keep threading.Lock and Condition around every heap mutation/claim; never hold heap lock while doing network/DB calls. Workers block on condition when empty and wake on enqueue. Avoid deadlocks with documented lock-order and bounded critical sections.

Consistency with DB: create case/outbox in one DB transaction; worker consumes outbox, enqueues idempotently. When claiming, use SQL atomic compare-and-swap UPDATE ... WHERE status='QUEUED' AND version=:v RETURNING ... before treating claim as final. If claim fails, discard stale heap entry/reload. Persist assignment lease; recover timed-out leases and rebuild queue at restart. Processing idempotent (finding_id+rule_version_id uniqueness). New priority must invalidate stale heap entries rather than duplicate claims. Acceptance: 50 producer/consumer threads with no lost/duplicate claims and heap invariant intact; collision test yields exactly one winner; shutdown without hanging.

M08 — Mandatory Layer C1: DAG workflow dependencies [M]

Track 2 hard requirement: both Branch_Ledge_Clearance[spelling exactly as in official PDF] and External_Whistleblower_Audit must resolve to unlock Escalation_Status. Preserve PDF field spelling in outward-facing workflow ID; optional human label "Branch Ledger Clearance".

Model: workflow template version contains tasks and prerequisite edges; TaskDependencies(prerequisite -> dependent). Activation runs Kahn topological sort and DFS colored cycle validation. Reject self-edge, duplicate edge, missing task, cycle, or cross-template link with 422 and stable error code CYCLIC_DEPENDENCY. Runtime unlock requires all prerequisite tasks in COMPLETED; parallel independent tasks may execute simultaneously. Task completion + unlock notifications + activity records are atomic DB transaction updates. Activated workflow version immutable for existing cases.

Example:Branch_Ledge_Clearance and External_Whistleblower_Audit start independently; Escalation_Status stays BLOCKED until both complete. Test invalid A→B→C→A and concurrent completions to ensure exactly-once unlock.

M09 — Mandatory Layer C2: access control + immutable activity history [M]

Server-side RBAC check on every mutation and sensitive read; fail closed. Create Activity_Log append-only with UUID, user ID (nullable for SYSTEM actor with explicit actor type), UTC timestamp, action type, entity type/id, old/new JSON values, request correlation ID and source job ID. Use DB permission model that denies UPDATE/DELETE to runtime role; separate admin migration owner, optional triggers to block mutation. Store transitions in same transaction as change. Optional hash chain enhances tamper evidence but is not mandatory.

Authentication: password hashing via Argon2, secure httpOnly cookies, CSRF protection where applicable, no plaintext secrets committed. Mask account identifiers in general dashboard, apply API rate limits and sanitize CSV formula injection on export. Acceptance: forbidden role gets 403, allowed action audited exactly once, no normal API permits log mutation, concurrent transitions preserve ordered history per case.

M10 — Audit cases and deterministic priority [D]

Normalize every detector output to Finding{type, severity_inputs, txn_ids, evidence_json, config_version, fingerprint}. An administrator-entered AST rule decides whether to create a review case. Priority computation is configurable deterministic math, not a trained risk score. For demo: priority = min(100, 40*severe_recon_mismatch + 35*circular_flow + 25*splitting + min(20, aging_points)), using booleans and integer aging; actual thresholds stored in config. Prevent case explosion: unique finding fingerprint and policy version; group overlapping patterns where appropriate. A case can have several linked findings (use CaseFindings junction), and priority recalculation is versioned and logged.

Statuses: QUEUED → CLAIMED → IN_REVIEW → ESCALATED or RESOLVED; BLOCKED for DAG-gated stage, FAILED/RETRY_PENDING for workers. Define permitted transitions explicitly and reject invalid 409 INVALID_STATE_TRANSITION.

M11 — UI / demo [D]

Pages: (1) Overview metrics (2) Ingestion and source-record quality (3) Duplicate candidates (4) Reconciliation comparison and exception drill-down (5) Circular-flow graph and transaction timeline (6) Splitting window explorer (7) Dynamic rules editor showing token stream and AST preview (8) Priority queue/cases (9) DAG workflow builder/status with cycle error (10) Activity ledger and stress metrics. UI states: loading, empty, error, pending, conflict, partial import, retry. Never claim a transfer is fraudulent; label "Flagged for audit review".

6. Relational schema and data integrity [D, must meet 3NF M]

Core tables (minimum column families; explicitly define full indexes and migrations):

branches(id PK, code UNIQUE, name)

accounts(id PK, branch_id FK RESTRICT, currency, masked_label, UNIQUE(branch_id,masked_label))

source_systems(id PK, name UNIQUE)

ingestion_jobs(id PK, source_system_id FK, received_at, state, counts_json)

source_records(id PK, ingestion_job_id FK, source_system_id FK, external_ref, source_revision, payload_json, payload_hash, received_at, record_status, UNIQUE(source_system_id,external_ref,source_revision))

transactions(id PK, external_canonical_ref UNIQUE NULL, sender_account_id FK RESTRICT, receiver_account_id FK RESTRICT, amount_minor BIGINT CHECK(amount_minor>0), currency CHAR(3), occurred_at timestamptz, posted_at timestamptz, txn_type, status)

source_record_transactions(source_record_id FK, transaction_id FK, link_type, PK(source_record_id,transaction_id))

journals(id PK, branch_id FK, posted_at, journal_ref UNIQUE, status)

journal_lines(id PK, journal_id FK RESTRICT, account_id FK RESTRICT, debit_minor BIGINT DEFAULT 0, credit_minor BIGINT DEFAULT 0, CHECK(...nonnegative and exactly one side positive))

reconciliation_runs(id PK, source_left_id FK, source_right_id FK, start_at, cutoff_at, policy_version_id FK, input_checkpoint, status)

reconciliation_results(id PK, run_id FK, left_record_id FK NULL, right_record_id FK NULL, status, variance_minor, reason_code, UNIQUE(run_id,left_record_id,right_record_id))

detector_configs(id PK, detector_type, version, config_json, status, UNIQUE(detector_type,version))

findings(id PK, finding_type, fingerprint UNIQUE, detector_config_id FK, algorithm_version, status, evidence_json, created_at)

finding_transactions(finding_id FK, transaction_id FK, path_position, PK(finding_id,transaction_id))

rules(id PK, name, version, expression, status, created_by FK, activated_at, UNIQUE(name,version))

audit_cases(id PK, case_code UNIQUE, state, priority INT CHECK(0<=priority AND priority<=100), row_version INT, assignee_id FK NULL, lease_until NULL, created_at)

case_findings(case_id FK, finding_id FK, PK(case_id,finding_id))

workflow_templates(id PK, name, version, status, UNIQUE(name,version))

workflow_task_templates(id PK, template_id FK, stable_key, display_name, UNIQUE(template_id,stable_key))

workflow_edges(template_id FK, predecessor_template_task_id FK, successor_template_task_id FK, composite PK; validate same template)

case_tasks(id PK, case_id FK, task_template_id FK, state, completed_at NULL, row_version)

users(id PK, username UNIQUE, password_hash, status) + roles(id PK, name UNIQUE) + user_roles(user_id FK, role_id FK, composite PK)

activity_log(id PK, actor_user_id FK NULL, actor_type, occurred_at, action_type, entity_type, entity_id, old_value JSONB, new_value JSONB, correlation_id)

outbox_events(id PK, event_type, entity_id, payload_json, status, attempt_count, created_at, claimed_at NULL, UNIQUE(event_type,entity_id, payload_hash))

3NF note: keep branch attributes only in branches, account properties only in accounts, role names only in roles. Derived aggregate metrics can be computed or stored in explicit cache tables with regeneration semantics. JSONB evidence is allowed for heterogeneous detector-specific details, but stable relational keys and references remain normalized. Add indexes on transactions(occurred_at,sender_account_id), transactions(receiver_account_id,occurred_at), source_records(source_system_id,external_ref), findings(finding_type,created_at), audit_cases(state,priority), case_tasks(case_id,state), activity_log(entity_type,entity_id,occurred_at). Use RESTRICT / NO ACTION on audit history; no cascade deletion of economic records. Use cascading deletes only for truly disposable children in a nonproduction test fixture, if necessary.

7. API contract (prefix /api/v1) [D]

Conventions: JSON response envelopes {data,meta,request_id}; error {error:{code,message,details},request_id}. Input validation 422, auth 401, forbidden 403, conflict 409, not found 404, server 500. Mutation endpoints require session auth + CSRF and support Idempotency-Key where appropriate. Long-running operations return 202 {job_id,status_url}.

Method

Path

Purpose / payload summary

POST

/auth/login

username/password → session

POST

/ingestion/jobs

multipart CSV, source_system_id → job_id

GET

/ingestion/jobs/{id}

progress/counts/errors

GET

/transactions

cursor-based search/filter

GET

/duplicates

candidate pairs/cluster with evidence

POST

/reconciliation/runs

left/right sources, time range, cutoff, policy version → job

GET

/reconciliation/runs/{id}/results

paginated reconciliation results

POST

/detectors/circular/runs

date range, config version, snapshot checkpoint → job

POST

/detectors/splitting/runs

date range, config version, snapshot checkpoint → job

GET

/findings

filter detector type/status/date

GET

/findings/{id}

full evidence with linked transactions

POST

/rules/validate

expression → tokens, AST, typed diagnostic

POST

/rules

create DRAFT version

POST

/rules/{id}/activate

validate and activate immutable version

GET

/cases

priority/status/assignee filters

POST

/cases/{id}/claim

expected row_version → atomic claim

POST

/cases/{id}/transition

action, expected state/version, reason

POST

/workflows/validate

task nodes + edges → order or cycle path

POST

/workflows/templates

validated template version

GET

/cases/{id}/workflow

nodes, edges, current task states

GET

/activity-log

authorized paginated audit trail

POST

/admin/stress-tests

seed, number of workers, workload config → job

GET

/metrics

queue size, contention, p95 latency, throughput, failures



Representative finding payload:

{  "finding_id":"uuid",  "type":"CIRCULAR_FLOW",  "status":"FLAGGED_FOR_REVIEW",  "algorithm_version":"cycle-v1",  "detector_config_version":1,  "transaction_ids":["txn-101","txn-102","txn-103"],  "facts":{"Circular_Flow_Detected":true,"Cycle_Length":3,"Cycle_Duration_Minutes":15},  "evidence":{"accounts":["A","B","C","A"],"currency":"INR"},  "fingerprint":"sha256-hex"}

8. Exact repository/file structure [D]

track2-audit-platform/├── README.md├── PRD.md├── .env.example                # Supabase connection + pool configuration├── .gitignore├── docker-compose.yml├── Makefile├── docs/│   ├── architecture.md│   ├── api-contract.md│   ├── schema-erd.md│   ├── algorithm-complexity.md│   ├── demo-playbook.md│   └── adr/0001-single-heap-owner.md├── backend/│   ├── pyproject.toml│   ├── alembic.ini│   ├── alembic/versions/│   ├── app/│   │   ├── main.py│   │   ├── config.py│   │   ├── db/session.py│   │   ├── db/models/ (accounts.py, transactions.py, journals.py, findings.py, cases.py, workflow.py, auth.py, audit.py, outbox.py)│   │   ├── schemas/ (common.py, ingestion.py, transactions.py, reconciliation.py, detectors.py, rules.py, cases.py, workflows.py)│   │   ├── api/v1/ (auth.py, ingestion.py, transactions.py, duplicates.py, reconciliation.py, detectors.py, rules.py, cases.py, workflows.py, activity.py, metrics.py)│   │   ├── core/auth.py│   │   ├── core/rbac.py│   │   ├── core/errors.py│   │   ├── core/idempotency.py│   │   ├── core/audit_writer.py│   │   ├── ingestion/csv_reader.py│   │   ├── ingestion/normalizer.py│   │   ├── ingestion/canonicalizer.py│   │   ├── ingestion/service.py│   │   ├── engines/identity/inverted_index.py│   │   ├── engines/identity/blocking.py│   │   ├── engines/identity/soundex.py│   │   ├── engines/identity/levenshtein.py│   │   ├── engines/identity/resolver.py│   │   ├── engines/reconciliation/matcher.py│   │   ├── engines/reconciliation/journal_balance.py│   │   ├── engines/reconciliation/service.py│   │   ├── engines/circular/graph.py│   │   ├── engines/circular/dfs.py│   │   ├── engines/circular/temporal_validator.py│   │   ├── engines/circular/service.py│   │   ├── engines/splitting/window.py│   │   ├── engines/splitting/partition.py│   │   ├── engines/splitting/service.py│   │   ├── engines/rules/tokens.py│   │   ├── engines/rules/lexer.py│   │   ├── engines/rules/parser.py│   │   ├── engines/rules/ast_nodes.py│   │   ├── engines/rules/types.py│   │   ├── engines/rules/evaluator.py│   │   ├── engines/rules/service.py│   │   ├── engines/queue/binary_heap.py│   │   ├── engines/queue/synchronized_queue.py│   │   ├── engines/queue/claim_service.py│   │   ├── engines/workflow/dag.py│   │   ├── engines/workflow/toposort.py│   │   ├── engines/workflow/cycle_detection.py│   │   ├── engines/workflow/service.py│   │   ├── services/finding_service.py│   │   ├── services/case_service.py│   │   ├── services/outbox_service.py│   │   └── worker/main.py│   ├── tests/unit/ (test_index.py, test_soundex.py, test_levenshtein.py, test_lexer.py, test_parser.py, test_heap.py, test_dag.py, test_reconciliation.py, test_circular.py, test_splitting.py)│   ├── tests/integration/ (test_ingestion.py, test_cases.py, test_rbac.py, test_audit_log.py, test_outbox.py)│   ├── tests/stress/ (test_concurrent_claim.py, test_queue_contention.py, test_workflow_race.py, test_index_concurrency.py)│   └── scripts/ (seed_demo.py, generate_fixture.py, benchmark_algorithms.py)├── frontend/│   ├── package.json│   ├── tsconfig.json│   ├── src/app/ (login/, dashboard/, ingestion/, duplicates/, reconciliation/, patterns/circular/, patterns/splitting/, rules/, cases/, workflow/, audit-log/, stress/)│   ├── src/components/ (layout/, tables/, graph/, charts/, rules/, cases/, workflow/)│   ├── src/lib/api.ts│   ├── src/lib/types.ts│   └── tests/├── infra/supabase/README.md├── infra/supabase/bootstrap.sql├── infra/local-postgres/init.sql└── fixtures/    ├── branches.csv    ├── accounts.csv    ├── ledger_internal.csv    ├── ledger_counterpart.csv    ├── circular_transfers.csv    ├── splitting_transfers.csv    ├── malformed_records.csv    └── expected_findings.json

File ownership: Python engines/* must be pure business logic wherever possible; API routes only validate and orchestrate; DB services own transactions; workers own concurrency; frontend must not recompute financial audit decisions client-side.

9. Execution plan and dependencies (incremental build) [D]

Each phase is a mergeable vertical slice with a demo and tests. Do not start all modules as unintegrated stubs.

Phase

Deliverables / specific files

Exit criteria

P0 Foundation

Supabase project/connectivity, config, Alembic migrations, DB session, typed API envelope, auth/RBAC seeds, front-end shell, CI, fixtures

docker compose up starts frontend/API/worker with configured Supabase; DB health check; demo login; migration clean; local fallback smoke-tested

P1 Ingest + canonical model

M01 parsers, source_record and transaction/journal tables, import endpoint, demo CSV

10k records streamed; repeat import idempotent; row errors visible

P2 Mandatory index

M02 index/blocking/soundex/levenshtein/resolver, /duplicates, unit/benchmark

fuzzy case detected; no all-pairs scan; partition metrics reported

P3 Reconciliation extra

M03, match results, 3NF links, reconciliation dashboard

seeded matched/missing/mismatch/ambiguous scenarios correct

P4 Pattern extras

M04 graph/DFS/time filter; M05 sliding window; APIs/UI evidence

seeded positive/negative patterns, retries, late events correct

P5 Custom rule engine

lexer/parser/AST/typing/version service, rule editor

changing rules requires no source edit; bad input returns typed diagnostics

P6 Heap + claims

custom heap, mutex/condition, outbox, worker claims, recovery, priority UI

stress: exactly-once claim, zero heap invariant violations

P7 DAG + audit

DAG validation, topological sorting, workflow templates, activity append-only, review UI

dual prerequisite unlock, cycle rejected, RBAC/log verified

P8 Hardening

cross-module e2e, metrics, p95 throughput measurements, load script, demo runbook

all acceptance tests and required judge injections pass



Parallel team assignment (four devs): Dev A M01+M02; Dev B M06+M07; Dev C M08+M09+DB; Dev D M03+M04+M05 + frontend coordination. Integrate through shared data contracts from P0; rotate stress-test ownership. No one should independently invent incompatible transaction schema or priorities.

10. Interface contracts between engine teams [D]

Ingestion → identity:SourceRecordEvent(source_record_id, normalized_fields, canonical_transaction_id?, checkpoint).

Ingestion → detection:CanonicalTransferEvent(transaction_id, sender, receiver, amount_minor, currency, occurred_at, status, checkpoint).

Detectors → findings:FindingDraft(type, fingerprint, evidence, transaction_ids, facts, config_version, algorithm_version).

Findings → rules: typed read-only mapping of facts, plus rule version; evaluator returns {matched, expression_version, explanation_tree}.

Rules → cases:{finding_ids, priority, rule_version, idempotency_key}; database write case + log + outbox atomically.

Queue → workflow:{case_id, expected_row_version, claimed_by}; claim commits before mutable actions.

Workflow → activity: every transition sends old and new serialized state within same DB transaction.

11. Non-functional requirements and performance budgets [D]

Correctness first: zero double assignments and zero lost audit events in reproducible stress fixtures; deterministic results for same input/checkpoint/config.

Data scale demo target: 100,000 source rows, >=10,000 canonical transfers, >=1,000 accounts; generate with a saved random seed. These are demonstration targets, not published competition thresholds.

Latency targets on stated demo hardware (aspirational): indexed duplicate candidate lookup p95 <100ms for a bounded bucket; queue push/pop p95 <20ms with light contention; /cases paginated API p95 <500ms. Always report actual hardware, load, measurements and exception rates; do not claim guarantees.

Bounded memory: streaming CSV iterator, compact index summaries, capped candidate buckets, bounded detector windows, configurable max cycle exploration, database pagination. Report heap and index memory footprint.

Observability: counters for ingest rate, accepted/rejected, duplicate candidates, reconciliation statuses, pattern counts, AST parse failures, heap depth, queue contention, task unlock failures, retries, log writes, p50/p95 response latency.

Security: RBAC, input size limits, parser AST depth/length limits, parameterized SQL, no untrusted eval, no production secrets in repository, restricted audit-log writes.

Reliability: outbox retries, job idempotency, worker shutdown/recovery, TTL leases, 409 state conflicts, no unbounded loops or heap lock held during DB calls.

12. Acceptance test matrix / judge demo [T]

Test ID

Stimulus

Expected outcome

T01

same row replayed 3 times

one canonical event, three traceable source attempts/rows as policy permits, no double counting

T02

typo / shifted date in bank description

bucket-local fuzzy candidate returned with evidence

T03

100k noisy records

bounded RAM; candidate scan metrics demonstrate partitioning

T04

ledger T102 25,000 vs 24,500 INR

amount mismatch of INR 500

T05

one-to-many reconciliation candidates

AMBIGUOUS, no silent multi-match

T06

debit 10000, credit 9000 in journal

unbalanced journal finding

T07

A→B→C→A, monotonic time

circular-flow candidate generated

T08

graph cycle but time order invalid

no valid financial cycle finding

T09

cycles many in dense SCC

exploration bound/cancellation enforced

T10

40k+35k+30k within 60 min

splitting finding >=100k, minimum 3

T11

same outside 60min or duplicate retry

no false aggregate breach

T12

invalid rule foo >>> 10

422 with source location, no execution

T13

admin changes/activates rule text

new cases use new version, old evidence keeps old version

T14

50 concurrent claims same case

exactly one claim succeeds; others 409/no-op

T15

producer/consumer heap contention

invariant preserved; no lost/duplicate claims

T16

only first branch prerequisite complete

Escalation_Status remains BLOCKED

T17

both required prerequisites complete

Escalation_Status unlocked exactly once

T18

add A→B→C→A

template rejected with CYCLIC_DEPENDENCY

T19

VIEWER attempts activate rule

403 and no mutation

T20

update/delete activity log through API/runtime account

forbidden; historic event unchanged

T21

worker killed after outbox commit

replay/recovery processes once after restart

T22

combined demo all detectors

consistent findings → rule evaluation → heap → workflow → activity log



Test artifacts: automated test reports, seed used, fixture CSVs, benchmark JSON, screenshot or live display of thread counts, queue invariant count, conflict count and cycle errors.

13. Demo script (8–12 minutes) [D]

Login as ADMIN and show role matrix. Upload sample ledgers; show progress and raw-vs-canonical counts.

Show duplicate typo handled by memory index and explanation of keys/candidates.

Run reconciliation, show matched, INR 500 variance, missing/pending entries and journal imbalance.

Open circular graph A→B→C→A; click edges to see timestamps/amounts; show invalid temporal cycle filtered.

Display splitting example 40k+35k+30k and change threshold/window to demonstrate deterministic behavior.

Enter new rule text; show tokens, AST and live evaluation; submit malformed rule and show precise 422.

Run worker stress (e.g., 50 threads); show queue and no double claims/corruption.

Complete one Track 2 DAG prerequisite, show escalation blocked; complete second, show unlocked. Inject cycle and show rejection.

Open append-only Activity_Log; switch to VIEWER and show forbidden mutations. Conclude with measured memory/time Big-O analysis.

14. Definition of Done and guardrails for implementation agent [D]

A module is done only if: working implementation; typed API; migration; unit + integration tests; input validation; RBAC; audit event for state changes; docs and example fixtures; no TODO stubs in execution path; reproducible local command; and a demo acceptance test. Never mark success from tests that were not run. Commit in small logical increments, do not make silent architecture changes, and document deviations in docs/adr/.

Suggested build-agent instructions (subject to competition rules):

Read this PRD and official PDF before implementation. Treat [M] as nonnegotiable and [E] as included scope.

Preserve exact Track 2 prerequisite Branch_Ledge_Clearance spelling in API stable keys.

Use the single canonical transaction model and shared FindingDraft contract.

Implement core algorithms in the named engines/ files rather than delegating matching, parsing, heap or DAG behavior to external black boxes.

Never use ML/AI APIs, eval, exec, and never substitute simple SQL duplicate queries for the in-RAM index.

Build phases P0→P8 with runnable tests; after each phase state what is implemented, migrations added, tests executed and known limitations.

For thread tests distinguish in-process thread safety from cross-process DB coordination.

Do not invent passing performance numbers. If a test fails, fix it or report the failure explicitly.

Do not silently weaken audit semantics, data integrity, RBAC or event history to make a demo appear successful.

15. Risks and open design decisions

Risk

Mitigation / decision

AI-assistant prohibition applies to Codex

Verify organizer permission before Codex-based implementation; otherwise manually implement

O(N log N) claim under skewed buckets

Cap/refine buckets and measure actual candidate counts; document worst case

False positive cycles

Require chronology, amount/currency validation and manual review

Transaction splitting false positives

Configurable grouping, reversals handling, seeded tests, never automatically label fraud

Unreliable cross-ledger references

Tiered matching, human review ambiguous cases, one-to-one enforcement

Thread/process contention

Single heap owner, mutex/condition, DB CAS and leases

Append-only versus privileged DB ownership

Minimal runtime DB role, privileged migrations separate, audited maintenance

Missing counterpart due to delayed postings

PENDING_LATE until configurable cutoff; rerun when late events arrive

Scope too broad

Complete mandatory three engines and one end-to-end case path first; add extras in P3/P4



16. Traceability to official problem statement

Original source

Mandatory criterion

Implementation reference

PDF pp. 1–2, Layer A

stream fuzzy resolution, custom RAM index, phonetic blocking and edit distance

M01/M02, T01–T03

PDF p. 2, Layer B

custom text lexer/parser/AST, in-memory thread-safe priority heap

M06/M07, T12–T15

PDF pp. 2–3, Layer C

DAG, topological sorting, cycle detection, RBAC, immutable activity log

M08/M09, T16–T20

PDF p. 3, Track 2

overlapping branch ledgers; variance, balance anomaly, velocity; dual prerequisite escalation

M02/M06/M08

PDF pp. 4–5

3NF, FK/cascades, live stress and complexity defense

schema, P8, T14–T22

User-approved extensions

reconciliation, circular flow, splitting

M03–M05



End of PRD v1.0
