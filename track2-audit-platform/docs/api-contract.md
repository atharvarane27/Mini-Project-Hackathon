# API Contract & System Interface Specification (Prefix `/api/v1`)

## 1. Architectural Foundations & Mandatory Invariants

1. **Duplicate Ingestion Does Not Double-Count Economic Events**:
   - Inbound rows (`SourceRecord`) preserve source provenance, revisions, and raw payloads.
   - When duplicate or replayed rows arrive, they map to the existing `CanonicalTransaction` or flag a revision dispute. They NEVER create multiple independent economic transfers in graph analysis, sliding windows, or account balances.

2. **Financial Cycles vs. Workflow DAG Cycles**:
   - **Financial Cycles (`CIRCULAR_FLOW`)**: Directed cyclic flow of funds across accounts (e.g., $A \to B \to C \to A$) occurring in strictly non-decreasing chronological time. These are detected by `engines/circular/` and emitted as audit findings.
   - **Workflow DAG Cycles**: Structural dependencies between review tasks (e.g., Task A depends on Task B). Cycles in workflow templates are strictly forbidden and rejected at template validation with HTTP 422 and error code `CYCLIC_DEPENDENCY`.

3. **Detectors Never Write to the Heap Directly**:
   - Detectors (`identity`, `reconciliation`, `circular`, `splitting`) emit immutable `FindingDraft` records.
   - Findings are evaluated by runtime AST rules. If an active rule matches, an `AuditCase` is created in Supabase PostgreSQL alongside a durable outbox event.
   - The heap owner worker process consumes the outbox and enqueues the case into its in-memory synchronized heap.

4. **Strict Execution Pipeline**:
   ```text
   Ingestion (Source Records)
         |
         v
   Canonicalization (Transactions & Journal Lines)
         |
         v
   Detectors (Identity, Reconciliation, Graph Cycles, Splitting Windows)
         |
         v
   Findings (Normalized Facts & Structured Evidence)
         |
         v
   Rule Evaluation (Custom Lexer -> Parser -> AST -> Facts Matcher)
         |
         v
   Cases & Queue (Durable Outbox -> Thread-Safe Binary Heap Claims)
         |
         v
   Workflow DAG (Prerequisite Gating, Tasks, Approvals, Append-Only Activity Log)
   ```

---

## 2. Global Conventions

### A. Envelope Structures

- **Success Envelope**:
  ```json
  {
    "data": { ... },
    "meta": { ... },
    "request_id": "7f7bc86e11894d0c9a410319520cb955"
  }
  ```

- **Error Envelope**:
  ```json
  {
    "error": {
      "code": "VALIDATION_ERROR",
      "message": "Human-readable failure message",
      "details": { ... }
    },
    "request_id": "7f7bc86e11894d0c9a410319520cb955"
  }
  ```

### B. Standard HTTP Status Codes

- `200 OK`: Successful read or synchronous mutation.
- `201 Created`: Entity created.
- `202 Accepted`: Long-running async job initiated (`{ "job_id": "...", "status_url": "..." }`).
- `401 Unauthorized`: Missing or invalid session authentication.
- `403 Forbidden`: Authenticated user lacks required RBAC role.
- `404 Not Found`: Resource does not exist.
- `409 Conflict`: Optimistic locking collision (`row_version` mismatch) or invalid state transition.
- `422 Unprocessable Entity`: Schema validation failure or rule AST syntax error.
- `500 Internal Server Error`: Unhandled server exception.

### C. Standard Headers

- `X-Request-ID`: Client-provided or server-generated tracing UUID.
- `Idempotency-Key`: Mandatory on unsafe mutations (e.g., CSV imports, case claims).

### D. Cursor-Based Pagination

Paginated endpoints return:
```json
{
  "data": [ ... ],
  "meta": {
    "next_cursor": "eyJpZCI6ICJ0eG4tMTAwIiwgInRzIjogMTc2MTc0ODgwMH0=",
    "has_more": true,
    "total_count": 1045,
    "limit": 50
  },
  "request_id": "req-12345"
}
```

---

## 3. RBAC Role Matrix

| Role | Permitted Operations | Restricted Operations |
| :--- | :--- | :--- |
| `ADMIN` | Ingestion, rule management, workflow templates, role assignment, stress test triggers. | Cannot delete audit log or silently alter active rule versions. |
| `AUDITOR` | Browse assigned cases, inspect transactions, resolve assigned tasks. | Cannot activate rules or modify user roles. |
| `REVIEWER` | Verify high-risk findings, approve/decline escalation tasks. | Cannot bypass DAG prerequisites. |
| `VIEWER` | Read redacted dashboards and aggregated metrics. | No state mutations or unmasked account views. |
| `SYSTEM_WORKER` | Process outbox queues, claim cases, advance automated states. | Internal background worker credentials only. |

---

## 4. Transactional Outbox Lifecycle

```text
[Transaction Commit: Entity + OutboxEvent]
                 |
                 v
             [PENDING] (attempt_count = 0)
                 |
                 v
             [CLAIMED] (worker leases event; attempt_count += 1)
                 |
        +--------+--------+
        |                 |
     (Success)         (Failure)
        v                 v
   [PROCESSED]        [FAILED] (max retries reached, dead-lettered)
```

---

## 5. Finding Facts Catalog

The custom AST rule engine compiles expressions evaluating against this typed facts schema:

| Fact Identifier | Type | Units / Meaning |
| :--- | :--- | :--- |
| `Reconciliation_Variance_Minor` | `int` | Measured variance in minor units (paise). |
| `Allowed_Variance_Minor` | `int` | Admin-configured variance tolerance (paise). |
| `Balance_Anomaly_Flag` | `bool` | True if ledger balance fails mathematical consistency. |
| `Transaction_Velocity` | `int` | Number of transfers on account within lookback window. |
| `Circular_Flow_Detected` | `bool` | True if a valid time-ordered transfer cycle exists. |
| `Cycle_Length` | `int` | Number of hops in the transfer cycle (e.g., 3 for A->B->C->A). |
| `Cycle_Duration_Minutes` | `int` | Elapsed minutes between first transfer and cycle closing. |
| `Splitting_Window_Sum_Minor` | `int` | Sum of amounts in window (paise). |
| `Splitting_Window_Count` | `int` | Count of transactions in window. |
| `Duplicate_Candidate_Flag` | `bool` | True if record matches an existing record in RAM index. |
| `Severity` | `string` | Categorical rating: `"LOW"`, `"MEDIUM"`, `"HIGH"`, `"CRITICAL"`. |

---

## 6. Sample Request & Response Payloads

### A. Ingestion Job Submission
- **POST** `/api/v1/ingestion/jobs`
- **Request Headers**: `Idempotency-Key: idemp-csv-batch-001`
- **Request**: Multipart form data with file `ledger_internal.csv`, `source_system_id: "SRC_INTERNAL_CORE"`
- **Response** (`202 Accepted`):
  ```json
  {
    "data": {
      "job_id": "ingest-job-901",
      "source_system_id": "SRC_INTERNAL_CORE",
      "state": "PROCESSING",
      "received_at": "2026-10-29T18:00:00.000000Z"
    },
    "meta": {},
    "request_id": "req-ingest-01"
  }
  ```

### B. Canonical Transaction Retrieval
- **GET** `/api/v1/transactions?limit=1`
- **Response** (`200 OK`):
  ```json
  {
    "data": [
      {
        "id": "txn-c101",
        "external_canonical_ref": "CANON-2026-10-001",
        "sender_account_id": "acc-br01-1001",
        "receiver_account_id": "acc-br02-2002",
        "amount_minor": 2500000,
        "currency": "INR",
        "occurred_at": "2026-10-29T10:15:30.000000Z",
        "posted_at": "2026-10-29T10:15:32.000000Z",
        "txn_type": "NEFT_TRANSFER",
        "status": "POSTED"
      }
    ],
    "meta": {
      "next_cursor": "cursor-txn-c101",
      "has_more": false,
      "total_count": 1,
      "limit": 1
    },
    "request_id": "req-txn-01"
  }
  ```

### C. Circular Flow Finding
- **GET** `/api/v1/findings/find-circ-001`
- **Response** (`200 OK`):
  ```json
  {
    "data": {
      "id": "find-circ-001",
      "finding_type": "CIRCULAR_FLOW",
      "fingerprint": "a3f5c71b82e9d0124a9e5b1287c9f4d1e2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7",
      "status": "FLAGGED_FOR_REVIEW",
      "algorithm_version": "cycle-dfs-v1",
      "detector_config_version": 1,
      "transaction_ids": ["txn-101", "txn-102", "txn-103"],
      "facts": {
        "Reconciliation_Variance_Minor": 0,
        "Allowed_Variance_Minor": 0,
        "Balance_Anomaly_Flag": false,
        "Transaction_Velocity": 3,
        "Circular_Flow_Detected": true,
        "Cycle_Length": 3,
        "Cycle_Duration_Minutes": 18,
        "Splitting_Window_Sum_Minor": 0,
        "Splitting_Window_Count": 0,
        "Duplicate_Candidate_Flag": false,
        "Severity": "HIGH"
      },
      "evidence_json": {
        "account_ids": ["acc-A", "acc-B", "acc-C", "acc-A"],
        "transaction_ids": ["txn-101", "txn-102", "txn-103"],
        "amounts_minor": [50000000, 49500000, 49000000],
        "timestamps": [
          "2026-10-29T11:00:00Z",
          "2026-10-29T11:08:00Z",
          "2026-10-29T11:18:00Z"
        ],
        "cycle_duration_minutes": 18,
        "cycle_length": 3
      },
      "created_at": "2026-10-29T11:20:00.000000Z"
    },
    "meta": {},
    "request_id": "req-find-01"
  }
  ```

### D. Case Claim Execution
- **POST** `/api/v1/cases/case-9001/claim`
- **Request Body**:
  ```json
  {
    "expected_row_version": 1
  }
  ```
- **Response** (`200 OK`):
  ```json
  {
    "data": {
      "id": "case-9001",
      "case_code": "CASE-2026-009001",
      "state": "CLAIMED",
      "priority": 85,
      "row_version": 2,
      "assignee_id": "usr-auditor-12",
      "lease_until": "2026-10-29T19:00:00.000000Z",
      "created_at": "2026-10-29T11:30:00.000000Z",
      "finding_ids": ["find-circ-001"]
    },
    "meta": {},
    "request_id": "req-claim-01"
  }
  ```

### E. Track 2 Dual Prerequisite Workflow
- Mandatory DAG Prerequisite Rule: Both `Branch_Ledge_Clearance` and `External_Whistleblower_Audit` must resolve to `COMPLETED` before `Escalation_Status` unlocks.
- **GET** `/api/v1/cases/case-9001/workflow`
- **Response** (`200 OK`):
  ```json
  {
    "data": {
      "case_id": "case-9001",
      "tasks": [
        {
          "id": "task-w1",
          "case_id": "case-9001",
          "task_template_id": "tpl-blc",
          "stable_key": "Branch_Ledge_Clearance",
          "display_name": "Branch Ledger Clearance",
          "state": "COMPLETED",
          "completed_at": "2026-10-29T12:00:00Z",
          "row_version": 2
        },
        {
          "id": "task-w2",
          "case_id": "case-9001",
          "task_template_id": "tpl-ewa",
          "stable_key": "External_Whistleblower_Audit",
          "display_name": "External Whistleblower Audit",
          "state": "IN_PROGRESS",
          "completed_at": null,
          "row_version": 1
        },
        {
          "id": "task-w3",
          "case_id": "case-9001",
          "task_template_id": "tpl-esc",
          "stable_key": "Escalation_Status",
          "display_name": "Senior Reviewer Escalation",
          "state": "BLOCKED",
          "completed_at": null,
          "row_version": 1
        }
      ]
    },
    "meta": {},
    "request_id": "req-wf-01"
  }
  ```
