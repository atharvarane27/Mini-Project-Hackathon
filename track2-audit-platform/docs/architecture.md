# Architecture — Track 2 Platform (AuditForge)

## High-Level Topology

```text
[Browser / Auditor UI]
         |
         v
 [Next.js App Router (Port 3000)]
         |
         | HTTP / JSON Envelopes {data, meta, request_id}
         v
 [FastAPI Backend API (Port 8000)]
         |
         +-----------------------------------------------+
         |                                               |
         v                                               v
[Supabase PostgreSQL (Primary DB)]             [Durable Outbox Table]
- 3NF Relational Schema                                  |
- Raw Records vs Canonical Txns                          v
- Append-Only Activity Log                    [Dedicated Worker Process]
- Case State & Claim Locks                    - Single authoritative Heap Owner
                                              - Pure In-RAM Engines (Index, DFS, AST)
                                              - Outbox poller & DAG coordinator
```

## Architectural Boundaries

1. **In-Memory Engines (`backend/app/engines/`)**:
   - Pure, deterministic algorithms with no direct database queries or external library black-boxes.
   - Hand-written implementations:
     - `identity/`: Inverted index, phonetic Soundex blocking, bucket-local Levenshtein edit distance.
     - `reconciliation/`: Exact and composite cross-ledger matcher, journal balance validator.
     - `circular/`: Multigraph DFS, cycle detection, temporal order validation.
     - `splitting/`: Time-ordered sliding window deques with threshold triggers.
     - `rules/`: Tokenizer, recursive-descent parser, typed AST evaluator (no `eval()` or `exec()`).
     - `queue/`: Thread-safe synchronized binary max-heap.
     - `workflow/`: Directed acyclic graph (DAG) builder, Kahn topological sorter, cycle rejector.

2. **Persistence & Transactions (`backend/app/db/` & `backend/app/services/`)**:
   - Supabase PostgreSQL is the primary source of truth.
   - SQLAlchemy 2 with 3NF relational models.
   - Strict separation of entities:
     - Raw source ingestion records (`source_records`)
     - Canonical economic transactions (`transactions`)
     - Discovered anomaly findings (`findings`)
     - Investigation cases (`audit_cases`)
   - Append-only activity log (`activity_log`) committed atomically in the same transaction as state transitions.

3. **Concurrency Boundary**:
   - Single worker process owns the in-memory priority heap and coordinates internal worker threads via `threading.Lock` and `threading.Condition`.
   - Cross-process safety is guaranteed by atomic database operations (`UPDATE ... WHERE status='QUEUED' AND row_version=:v RETURNING ...`) and durable outbox events. See [ADR 0001](adr/0001-single-heap-owner.md).

4. **Data Conventions**:
   - **Monetary amounts**: Unsigned 64-bit integer minor units (`BIGINT` paise in INR). Never floating-point.
   - **Timestamps**: UTC `timestamptz`.
   - **Currencies**: ISO 4217 standard codes (e.g., `INR`, `USD`).
