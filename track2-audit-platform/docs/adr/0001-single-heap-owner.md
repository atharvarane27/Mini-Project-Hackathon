# ADR 0001: Single heap owner

Status: Planned, per PRD.

One worker process owns the in-memory heap and coordinates bounded threads using a mutex/condition. Thread locks do not synchronize replicas. PostgreSQL remains authoritative for cases, outbox events, claims and restart recovery.
