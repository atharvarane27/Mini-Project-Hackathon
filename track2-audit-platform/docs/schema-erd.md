# Database schema

P01 freezes these persistence-neutral identities before P02 maps them to 3NF:

- SourceRecord: source system + external ID + positive revision.
- CanonicalTransaction: one economic event linked to one or more source records.
- JournalLine: exactly one positive debit or credit in integer minor units.
- Finding: common detector envelope, stable fingerprint, facts and evidence.
- AuditCase: finding/rule identity, bounded priority and optimistic row version.
- OutboxEvent: entity version, payload hash, attempts and lifecycle status.
- WorkflowTask: case-scoped task key, prerequisites, state and row version.

Financial and audit evidence is immutable. P02 must not configure cascade delete
from canonical/source records into journals, findings, cases or activity.

## P02 normalized implementation

The initial migration creates 26 tables grouped as follows:

- Reference: `branches`, `accounts`, `source_systems`.
- Financial provenance: `source_records`, `canonical_transactions`,
  `source_record_links`, `journals`, `journal_lines`.
- Detection: `detector_runs`, `findings`, `finding_evidence`,
  `reconciliation_runs`, `reconciliation_results`, `audit_rules`,
  `audit_rule_versions`.
- Orchestration: `audit_cases`, `case_findings`, `outbox_events`,
  `workflow_templates`, `workflow_task_templates`, `workflow_dependencies`,
  `case_workflow_tasks`.
- Security/audit: `users`, `roles`, `user_roles`, `activity_log`.

Foreign keys protecting financial/audit evidence use `RESTRICT`. Uniqueness
covers source revision identity, canonical fingerprints, finding fingerprints,
case stable keys and logical outbox events. Queue/outbox, detector, transaction
time/currency and activity object/version access paths have explicit indexes.
PostgreSQL append-only permissions and a mutation-rejection trigger protect
`activity_log`; application controls remain defense in depth.

## P03 ingestion persistence

Migration `0002_ingestion` adds four tables: `ingestion_jobs`, `source_files`,
`ingestion_source_rows`, and `ingestion_row_errors`. Together they preserve job
progress, file hashes, row numbers, raw payload hashes, normalized source
identity, and stable quarantine diagnostics. Unique constraints cover
idempotency keys, file identity, row provenance, and source-system/external-ID/
revision identity. The normalized schema therefore contains 30 tables after P03.
