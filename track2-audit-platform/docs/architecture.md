# Architecture

Next.js frontend -> FastAPI -> Supabase PostgreSQL and durable outbox -> one worker process with bounded threads. Engines own business algorithms; services own database transactions; worker owns concurrency.

The API and dedicated single-owner worker are separate processes. PostgreSQL is
the durable authority; in-memory indexes and heaps are restartable projections.
Every HTTP request receives an `X-Request-ID` and emits a structured JSON log.
The optional Compose PostgreSQL profile is for local development only.

Frontend runtime and UI composition remain deferred until the user supplies the
Phase 19 design.

## Authoritative data flow

`source record -> canonical transaction/journal -> detector run -> immutable
finding -> versioned rule evaluation -> case + outbox -> synchronized heap ->
workflow tasks -> append-only activity`

Detectors persist findings only. They never write directly to the in-memory
heap. Case creation and its outbox event share one database transaction; the
worker projects durable queued cases into the heap after commit.

The circular financial graph models chronological money movement and may
contain suspicious cycles. The workflow graph models task prerequisites and
must always remain acyclic. These graphs are separate contracts and engines.
