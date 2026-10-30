# Phase 19 frontend requirements and UI handoff contract

Status: requirements frozen; implementation must wait for the user-supplied UI
design. This document describes behaviour and data, not visual styling.

## 1. Objective and boundaries

Build an authenticated audit operations interface over `/api/v1`. The frontend
must display ingestion, transactions, detector evidence, rules, cases,
workflows, and activity without changing financial or audit records.

- Use the backend API as the only business-data authority.
- Never connect the browser directly to PostgreSQL or expose a Supabase service
  role key.
- Do not infer, merge, delete, or alter evidence in the browser.
- Do not describe deterministic duplicate scores as probabilities or AI
  confidence.
- Preserve the supplied visual design while keeping the contracts in this
  document unchanged.
- Phase 20 owns production integration, performance measurements, deployment,
  and final end-to-end acceptance.

## 2. Required design handoff

The UI design must provide:

1. Desktop frames for every route in section 5, plus tablet and mobile rules.
2. Navigation, breadcrumbs, page titles, filters, tables, drawers, dialogs,
   notifications, and pagination.
3. Default, hover, focus, selected, disabled, loading, empty, success, warning,
   error, unauthorized, and stale-data states.
4. Tokens for colours, typography, spacing, radii, shadows, breakpoints, and
   light/dark behaviour if dark mode is required.
5. Component variants and dimensions, including dense audit tables.
6. Exportable icons/images with ownership or licence information.
7. Interaction notes for graphs, workflow nodes, evidence expansion, rule
   diagnostics, case transitions, and responsive table behaviour.
8. Exact chart types and legends. Every chart must retain a tabular equivalent.

Preferred delivery is a Figma link with inspect access plus exported assets.
Screenshots alone are acceptable only if spacing, fonts, colours, responsive
behaviour, and interactions are separately documented.

## 3. Frontend technical contract

- Framework: Next.js App Router with TypeScript strict mode.
- API base URL: environment variable `NEXT_PUBLIC_API_BASE_URL`; no hard-coded
  localhost or production URL.
- All network calls go through one typed API client in `src/lib/api.ts`.
- Shared domain types remain in `src/lib/types.ts` and must match backend JSON.
- Server responses use `DataEnvelope<T>` or `ErrorEnvelope` where implemented.
- Send `X-Request-ID` on each request and show/copy it in error details.
- Send `Authorization: Bearer <token>` for authenticated routes.
- Keep bearer tokens in memory, not local storage. A refresh may require login
  until the backend adds secure HttpOnly cookie or refresh-session support.
- Generate one `Idempotency-Key` per user mutation and reuse it for retries of
  that same action. Generate a new key only for a genuinely new action.
- Cancel superseded reads with `AbortController`; never retry mutations with a
  new idempotency key automatically.
- Use UTC API timestamps and render an explicit local timezone label.
- API money is an integer in minor units. Format for display using currency
  fraction rules; never send floating-point money.
- Pagination uses `offset`, `limit` (1–500), and `total`.

## 4. Roles and navigation

| Capability | ADMIN | AUDITOR | REVIEWER | VIEWER |
|---|---:|---:|---:|---:|
| View dashboard/evidence/cases/activity | yes | yes | yes | yes |
| Claim and investigate cases | yes | yes | no | no |
| Review case transitions | yes | yes | yes | no |
| Manage rules, workflow templates, users | yes | no | no | no |

Hide actions that a role can never perform, but still handle backend `403`
responses. Do not treat hidden buttons as authorization. Maker-checker actions
must prevent the initiating actor from approving their own sensitive change.

Required global shell:

- Product identity and environment indicator.
- Role-aware primary navigation.
- Current user, roles, session expiry, logout.
- Breadcrumb and page heading.
- Global request/error notification region.
- Connection/session-expired state.
- Keyboard-accessible skip link and focus management.

## 5. Route and screen requirements

### `/login`

Inputs: username and password. Submit to `POST /api/v1/auth/login`.

Output: bearer token, token type, expiry, and roles. Redirect authenticated
users to `/dashboard`. Show a generic invalid-credentials message on `401`;
never reveal whether a username exists. Disable duplicate submission, allow a
password visibility toggle, and never log the password.

### `/dashboard`

Show data freshness and links to ingestion jobs, open cases, findings by type,
recent activity, and detector runs. Summary cards must link to filtered source
tables. Until aggregate endpoints exist, do not download all records merely to
calculate dashboard totals; use explicit unavailable placeholders.

### `/ingestion`

Inputs: one CSV file, source system, and generated idempotency key. Submit as
multipart form data to `POST /api/v1/ingestion/jobs`.

Output fields: job ID, status, source system/file, SHA-256 file hash, last row,
processed, accepted, rejected, duplicate counts, and failure message. Poll
`GET /api/v1/ingestion/jobs/{job_id}` while running and stop on completed or
failed. Provide accessible progress and count summaries.

Accept `.csv` in the picker but treat server validation as authoritative. Do
not load the full file into browser memory, promise cancellation, or claim that
rejected rows were accepted. `409 IDEMPOTENCY_CONFLICT` requires an explicit
new-import action rather than an automatic retry.

### `/transactions`

Inputs: optional exact account ID, exact reference, offset, and limit for
`GET /api/v1/transactions`.

Output: transaction ID, source IDs, sender/receiver accounts, formatted amount
and currency, occurrence time, type, and status. A detail drawer must retain
all source-record links and label reversals/corrections without overwriting the
original event.

### `/reconciliation`

Reserved for Phase 7. The design may include run summary, mismatch table,
variance, ledger/bank evidence, and status filters, but implementation must not
invent endpoints or mock production results. Mark the route unavailable until
P07 contracts are delivered.

### `/duplicates`

Inputs: classification (`EXACT`, `CANDIDATE`, `AMBIGUOUS`, `NON_MATCH`), offset,
and limit for `GET /api/v1/duplicates`.

Output: both source record IDs, deterministic score, classification, compared
attributes, edit distances/reasons, and algorithm version. Evidence must be
expandable and copyable. Never offer an automatic destructive merge.

### `/patterns/circular`

Run input: versioned policy/checkpoint and the backend-defined candidate
snapshot for `POST /api/v1/detectors/circular/runs`. Findings input:
`finding_type=CIRCULAR_FLOW`, offset, and limit for `GET /api/v1/findings`.

Output: run status and immutable findings with ordered transaction evidence,
facts, fingerprint, algorithm/config versions, and timestamps. Graph arrows
must preserve chronological direction; also provide an ordered evidence table.
Show `RUN_INPUT_CONFLICT` as a changed-snapshot conflict, not a generic retry.

### `/patterns/splitting`

Run inputs: UTC-aware start time, end time, positive policy version, snapshot
checkpoint, and stable canonical input required by the API. Submit to
`POST /api/v1/detectors/splitting/runs`.

Output: run ID/status, versions, finding IDs/count, and replay indicator.
Findings show transaction IDs, sum/count/duration facts, evidence, fingerprint,
and versions. Reject end-before-start and naive timestamps before submission,
while retaining server validation messages.

### `/rules`

Validation input: rule expression for `POST /api/v1/rules/validate`.
Output: typed tokens, AST, Boolean result type, registry metadata, or a `422`
diagnostic with phase, stable code, message, offset, line, column, and length.
The editor must highlight the exact source range and preserve the expression.

ADMIN-only lifecycle inputs: name/expression and idempotency key for rule
creation, then rule ID for activation. Outputs include immutable version,
status (`DRAFT`, `ACTIVE`, `RETIRED`), creator/activator, and timestamps.
Activation requires a confirmation dialog and must display `409` conflicts.

### `/cases`

List inputs: offset and limit for `GET /api/v1/cases`. Output: case code,
finding IDs, rule version, state, priority, assignee, lease, row version, and
created time. Provide filters in the design, but activate only filters supported
by the API.

Claim input: case ID, displayed `expected_version`, worker ID, and bounded lease
seconds for `POST /api/v1/cases/{id}/claim`. Transition input: case ID,
displayed `expected_version`, and legal next state for the transition endpoint.
On `409`, keep unsaved user context, refetch the case, and explain that another
actor changed it. Never silently overwrite a newer row version.

Case detail must show findings, immutable evidence, rule identity, assignment,
state history/activity, and workflow. Legal lifecycle:
`QUEUED → CLAIMED → IN_PROGRESS → RESOLVED|REJECTED → CLOSED`.

### `/workflow`

ADMIN template builder inputs: unique task IDs/names, directed prerequisite
edges, template name, and activate flag. Validate via
`POST /api/v1/workflows/validate`; output a deterministic topological order or
readable cycle error. Create via `POST /api/v1/workflows/templates`.

The graph editor must support keyboard operation and a list/table alternative.
It must distinguish workflow dependency graphs from circular-money graphs.
Case workflow output shows task key, `LOCKED|READY|IN_PROGRESS|COMPLETE`,
prerequisites, and row version. Locked tasks cannot be started.

### `/audit-log`

Inputs: offset and limit for authenticated `GET /api/v1/activity`. Output must
show actor, UTC/local time, action, request ID, object type/ID/version, old/new
values, and integrity-chain information when supplied. Entries are read-only;
the UI must expose no edit/delete action. Large value objects open in a safe
JSON viewer with secrets redacted by the backend.

### `/stress`

ADMIN/development-only Phase 20 diagnostics. It must never appear in normal
production navigation unless the backend exposes authorized benchmark data.
Do not run stress tests from ordinary browser sessions.

## 6. Standard UI states and error behaviour

Every data view requires skeleton/loading, empty, populated, stale/refetching,
partial-data, and error states. Every mutation requires idle, submitting,
success, validation failure, conflict, unauthorized, forbidden, and unknown
failure states.

| HTTP status | Required frontend behaviour |
|---:|---|
| 400/422 | Keep inputs; map field/diagnostic details to the relevant control. |
| 401 | Clear in-memory session and return to login with a safe reason. |
| 403 | Keep the page readable; disable the forbidden action. |
| 404 | Show resource-not-found with navigation back to its list. |
| 409 | Explain stale version/idempotency/input conflict and offer refetch. |
| 429 | Respect `Retry-After`; do not retry mutations automatically. |
| 500/503 | Preserve user input and show request ID plus a manual retry. |

Unknown response fields should not crash the page. Missing required fields
must produce a controlled contract error, not fabricated values.

## 7. Accessibility, responsiveness, and presentation

- Target WCAG 2.2 AA: keyboard access, visible focus, semantic headings,
  labelled controls, error association, adequate contrast, and reduced motion.
- Never use colour alone for risk, status, graph edges, or validation.
- Tables need headers, captions, sortable-state announcements, and a usable
  narrow-screen representation. Do not hide audit-critical fields on mobile;
  move them into an expandable detail region.
- Graphs and charts require text/table alternatives.
- Use confirmation only for consequential mutations, not routine navigation.
- Format IDs in a copyable monospace treatment without truncating the copied
  value. Display hashes/fingerprints in expandable form.

## 8. Security and privacy requirements

- No database password, service-role key, raw `.env`, or bearer token in client
  bundles, URLs, analytics, console logs, or error monitoring.
- Escape all backend/user content; never inject raw HTML from evidence or rule
  text.
- Validate uploaded file type for usability, while relying on backend checks
  for security.
- Apply sensible `Content-Security-Policy`, clickjacking protection, secure
  transport, and dependency auditing in deployment.
- Redact sensitive account/party fields according to the authenticated role;
  backend authorization remains mandatory.
- Logout must invalidate the backend session and clear frontend memory.

## 9. Testing and Phase 19 acceptance

Required automated coverage:

- Type checking, linting, and production build.
- API-client envelope/error parsing and money/time formatting unit tests.
- Component tests for all states in section 6.
- Route tests for role visibility and direct-navigation authorization.
- Login/logout, upload/status polling, filters/pagination, rule diagnostics,
  case conflict/refetch, workflow cycle, and audit-log flows.
- Accessibility checks plus manual keyboard and screen-reader smoke tests.
- Responsive verification at the design breakpoints.
- End-to-end tests against a seeded non-production backend; no production data.

Phase 19 is accepted only when the supplied design is faithfully implemented,
all supported API flows work without mocked production data, prohibited roles
cannot perform mutations, and the frontend build/test suite is green.

## 10. Backend readiness dependencies

Before full frontend integration:

1. Mount auth, transactions, duplicates, detectors, rules, cases, workflows,
   and activity routers in the main FastAPI application. Currently health and
   ingestion are the only composed runtime routes.
2. Replace reference/in-memory repositories and temporary identity headers
   with Supabase-backed transactions and P18 authentication dependencies.
3. Complete P07 and freeze reconciliation endpoints.
4. Add dashboard aggregate endpoints rather than client-side full scans.
5. Standardize every route on the shared success/error envelope and request ID.
6. Confirm CORS, production origins, session transport, upload limits, polling
   interval, and data-redaction policy.

These dependencies do not block visual design, but they block honest Phase 19
end-to-end completion.
