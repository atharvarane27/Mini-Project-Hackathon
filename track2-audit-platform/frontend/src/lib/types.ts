export type StableId = string & { readonly __brand: "StableId" };
export type UtcTimestamp = string & { readonly __brand: "UtcTimestamp" };
export type MinorUnits = number & { readonly __brand: "MinorUnits" };
export type CurrencyCode = "INR" | (string & { readonly __brand: "CurrencyCode" });

export type Role = "ADMIN" | "AUDITOR" | "REVIEWER" | "VIEWER";
export type OutboxStatus = "PENDING" | "PROCESSING" | "PUBLISHED" | "DEAD_LETTER";
export type FindingType =
  | "DUPLICATE_CANDIDATE"
  | "RECONCILIATION_MISMATCH"
  | "CIRCULAR_FLOW"
  | "SPLITTING_PATTERN";

export interface SourceRecord {
  readonly source_record_id: StableId;
  readonly source_system: StableId;
  readonly external_id: StableId;
  readonly revision: number;
  readonly received_at: UtcTimestamp;
  readonly raw_payload: Readonly<Record<string, unknown>>;
}

export interface CanonicalTransaction {
  readonly transaction_id: StableId;
  readonly source_record_ids: readonly StableId[];
  readonly sender_account_id: StableId;
  readonly receiver_account_id: StableId;
  readonly amount_minor: MinorUnits;
  readonly currency: CurrencyCode;
  readonly occurred_at: UtcTimestamp;
  readonly transaction_type: StableId;
  readonly status: StableId;
}

export interface Finding {
  readonly finding_id: StableId;
  readonly finding_type: FindingType;
  readonly fingerprint: string;
  readonly transaction_ids: readonly StableId[];
  readonly facts: Readonly<Record<string, unknown>>;
  readonly evidence: Readonly<Record<string, unknown>>;
  readonly detector_config_version: number;
  readonly algorithm_version: StableId;
  readonly status: StableId;
  readonly created_at: UtcTimestamp;
}

export interface AuditCase {
  readonly case_id: StableId;
  readonly case_code: StableId;
  readonly finding_ids: readonly StableId[];
  readonly rule_version_id: StableId;
  readonly state: "QUEUED" | "CLAIMED" | "IN_PROGRESS" | "RESOLVED" | "REJECTED" | "CLOSED";
  readonly priority: number;
  readonly row_version: number;
  readonly assignee_id: StableId | null;
  readonly lease_until: UtcTimestamp | null;
  readonly created_at: UtcTimestamp;
}

export interface WorkflowTask {
  readonly workflow_task_id: StableId;
  readonly case_id: StableId;
  readonly task_key: StableId;
  readonly state: "LOCKED" | "READY" | "IN_PROGRESS" | "COMPLETE";
  readonly prerequisite_task_ids: readonly StableId[];
  readonly row_version: number;
}

export interface OutboxEvent {
  readonly event_id: StableId;
  readonly event_type: StableId;
  readonly entity_id: StableId;
  readonly entity_version: number;
  readonly payload: Readonly<Record<string, unknown>>;
  readonly payload_hash: string;
  readonly status: OutboxStatus;
  readonly attempt_count: number;
  readonly created_at: UtcTimestamp;
}

export interface DataEnvelope<T> {
  readonly data: T;
  readonly meta: Readonly<Record<string, unknown>>;
  readonly request_id: StableId;
}

export interface ErrorEnvelope {
  readonly error: {
    readonly code: string;
    readonly message: string;
    readonly details: Readonly<Record<string, unknown>>;
  };
  readonly request_id: StableId;
}

export function minorUnits(value: number): MinorUnits {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new TypeError("minor units must be a non-negative safe integer");
  }
  return value as MinorUnits;
}

export function utcTimestamp(value: string): UtcTimestamp {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(value)) {
    throw new TypeError("timestamp must be ISO 8601 UTC with a Z suffix");
  }
  return value as UtcTimestamp;
}
