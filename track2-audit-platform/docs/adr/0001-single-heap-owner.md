# ADR 0001: Single heap owner

Status: Accepted for the MVP.

## Context

The mandatory queue is an application-owned in-memory binary heap. Python
thread locks coordinate threads inside one process only; they cannot coordinate
multiple worker processes or deployment replicas. PostgreSQL remains the source
of truth for cases, outbox events, row versions, claims, and restart recovery.

## Decision

One worker process owns one `SynchronizedCaseQueue` and may run multiple bounded
consumer/producer threads. The queue owns a custom `BinaryMaxHeap`, one
non-reentrant `Lock`, and one `Condition` built from that lock. No heap object is
shared directly with callers.

Every read and mutation of heap state occurs while holding the same lock,
including size, membership, peek, metrics, and invariant validation. No network
or database call may occur while that lock is held. P16 must pop an entry,
release the queue lock, and then attempt PostgreSQL compare-and-swap claiming.

Entries are unique by case ID and contain priority, enqueue sequence, case ID,
and case row version. Higher priority wins; equal priority uses the oldest
sequence, followed by case ID as a deterministic defensive fallback. Priority
updates replace the indexed entry and require a strictly newer case version.

Consumers wait in a condition loop, tolerating spurious wakeups. Timeout is a
controlled error. Shutdown rejects new work, wakes every waiter, allows already
queued work to drain, and then returns a shutdown signal instead of hanging.

## Consequences

- Heap mutations are `O(log N)` and peek/size/membership are `O(1)`.
- Duplicate queue entries and stale priority versions fail explicitly.
- Queue metrics expose pushes, pops, updates, removals, waits, timeouts, lock
  contention, rejections, maximum depth, and current depth.
- Process death loses only the in-memory projection; P16 rebuilds it from the
  durable outbox/case state.
- Horizontal multi-owner heap coordination is outside MVP scope. Scaling later
  requires database partition ownership or another durable coordination design,
  not an assumption that `threading.Lock` spans processes.
