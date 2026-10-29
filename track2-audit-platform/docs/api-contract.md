# API contract

Reserve /api/v1 for backend routes. See PRD section 7 for endpoints, envelopes, authentication, CSRF and errors.

## P09 circular-flow detector

`POST /api/v1/detectors/circular/runs` validates P08 cycle candidates against a
versioned temporal/monetary policy and persists an idempotent checkpoint run.
`GET /api/v1/findings?finding_type=CIRCULAR_FLOW` returns immutable findings
with ordered transfer evidence. Reusing a completed checkpoint with changed
input produces HTTP 409 `RUN_INPUT_CONFLICT`.

## P11 splitting detector

`POST /api/v1/detectors/splitting/runs` accepts an aware UTC-compatible
`start_at`, `end_at`, positive `policy_version`, and nonblank
`snapshot_checkpoint`. It returns HTTP 202 with the completed/idempotently
replayed run ID, status, policy/checkpoint, finding IDs, finding count, and
`replayed` flag in the standard `{data, meta, request_id}` envelope. A retry of
the same policy/checkpoint with changed canonical input is HTTP 409
`RUN_INPUT_CONFLICT` after the shared P00 error handler formats the error.

`GET /api/v1/findings` accepts optional `finding_type`, `offset`, and `limit`
(maximum 500). P11 returns the canonical finding fields required by the PRD:
ID, type/status, algorithm/config versions, contributing transaction IDs,
typed facts, evidence, and fingerprint.

The router is constructed with policy, stable-snapshot transfer, and repository
adapters. This avoids module-global database state and lets the merged P00/P02
application supply authenticated Supabase implementations.

## P13 rule validation

`POST /api/v1/rules/validate` accepts `{ "expression": "..." }`. A valid rule
returns the complete typed token stream, immutable AST representation, Boolean
result type, registry metadata, and request ID. Exact decimal literals are JSON
strings rather than binary floating-point numbers.

Lexical or parser/static-type failures return HTTP 422 using the standard error
envelope. Details contain `phase` (`LEXER` or `PARSER`), stable code, message,
zero-based offset, one-based line/column, and source length. Validation does not
save, activate, or evaluate a rule; those operations begin in P14.

## P14 rule lifecycle

`POST /api/v1/rules` creates a validated immutable `DRAFT` version and accepts
`Idempotency-Key`. `POST /api/v1/rules/{rule_id}/activate` recompiles and
atomically activates that version, retiring the prior active version with the
same name. Responses identify the rule, name/version, expression, status,
creator, activator, and UTC timestamps.

P14's composable router accepts `X-Actor-ID` and `X-Roles` only as an integration
adapter for tests and the still-unmerged authentication layer. P18 must replace
these headers with authenticated server-side session/RBAC dependencies. Both
mutations require the `ADMIN` role. Missing identity returns 401, insufficient
role 403, missing rule 404, idempotency/state conflict 409, and invalid rule
422. Rule evaluation is an internal worker/service operation rather than a
public endpoint in this phase.

## P16 case lifecycle

`GET /api/v1/cases` returns deterministic case records with offset/limit
pagination metadata. `POST /api/v1/cases/{case_id}/claim` requires the expected
row version, worker ID, and a bounded lease duration. The claim is successful
only when persistent state is still `QUEUED` at that version; a lost CAS race
returns HTTP 409 `CASE_CLAIM_CONFLICT`.

`POST /api/v1/cases/{case_id}/transition` requires an expected row version and
one legal next state. The supported lifecycle is `CLAIMED -> IN_PROGRESS ->
(RESOLVED | REJECTED) -> CLOSED`. Missing temporary actor identity is 401,
missing case is 404, and stale versions or illegal transitions are 409. P18
must replace the temporary `X-Actor-ID` integration header with authenticated
session/RBAC dependencies.

Case creation is an internal service operation driven by qualifying rule
evaluations. Its stable key covers sorted unique finding IDs and rule-version
ID. The repository must commit case, `CASE_QUEUED` outbox event, and audit
intent in one database transaction; exact retries return the existing case.

### PostgreSQL adapter contract

The P02 adapter must implement the repository protocol using these atomic
database operations:

- Case claim: `UPDATE audit_cases SET state='CLAIMED', row_version=row_version+1,
  assignee_id=:worker, lease_until=:until WHERE id=:id AND state='QUEUED' AND
  row_version=:expected RETURNING *`.
- Outbox polling: select available `PENDING` or expired `PROCESSING` events with
  `FOR UPDATE SKIP LOCKED`, then assign a worker event lease in the same
  transaction.
- Lease recovery: conditionally move only expired claimed/in-progress cases
  back to `QUEUED`, increment `row_version`, and insert the versioned outbox
  event plus audit intent atomically.
- Unique constraints must cover the stable case key and logical outbox event
  identity `(event_type, entity_id, entity_version)`.

No database or network call is permitted while the P15 heap mutex is held.

## P17 workflow DAG

`POST /api/v1/workflows/validate` returns a deterministic topological order or
HTTP 422 with a readable cycle/graph error. `POST /api/v1/workflows/templates`
creates a versioned draft and may atomically activate it. `GET
/api/v1/cases/{case_id}/workflow` returns task states and row versions.

Dependencies use a custom adjacency list. A dependent task changes from
`LOCKED` to `READY` only after every incoming prerequisite is `COMPLETE`.

## P18 authentication and activity

`POST /api/v1/auth/login` creates an expiring server-side bearer session;
`POST /api/v1/auth/logout` invalidates it. `GET /api/v1/activity` requires an
authenticated role with `ACTIVITY_READ` and returns the append-only ledger.
Missing/expired identity is 401, insufficient permission is 403, and stale
workflow versions produce a conflict for the API adapter to expose as 409.
