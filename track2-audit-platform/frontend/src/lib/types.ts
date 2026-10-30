// RBAC Role Matrix
export type UserRole = "ADMIN" | "AUDITOR" | "REVIEWER" | "VIEWER" | "SYSTEM_WORKER";

// Outbox Lifecycle
export type OutboxStatus = "PENDING" | "CLAIMED" | "PROCESSED" | "FAILED";

// Standard API Envelopes
export interface ApiResponse<T> {
  readonly data: T;
  readonly meta: Record<string, unknown>;
  readonly request_id: string;
}

export interface CursorPaginationMeta {
  readonly next_cursor: string | null;
  readonly has_more: boolean;
  readonly total_count: number | null;
  readonly limit: number;
}

export interface PaginatedResponse<T> {
  readonly data: readonly T[];
  readonly meta: CursorPaginationMeta;
  readonly request_id: string;
}

export interface ApiErrorDetail {
  readonly code: string;
  readonly message: string;
  readonly details?: unknown;
}

export interface ApiErrorResponse {
  readonly error: ApiErrorDetail;
  readonly request_id: string;
}

export interface HealthStatus {
  readonly status: string;
  readonly app: string;
  readonly version: string;
  readonly timestamp: string;
  readonly db_backend: string;
}

export interface OutboxEvent {
  readonly id: string;
  readonly event_type: string;
  readonly entity_id: string;
  readonly payload_json: Record<string, unknown>;
  readonly status: OutboxStatus;
  readonly attempt_count: number;
  readonly created_at: string;
  readonly claimed_at: string | null;
}

// Ingestion & Transactions
export type RecordStatus = "ACCEPTED" | "REJECTED" | "CONFLICT" | "PENDING_REVIEW";
export type TransactionStatus = "POSTED" | "PENDING" | "REVERSED";
export type TransferKind = "EXTERNAL_TRANSFER" | "INTERNAL_TRANSFER" | "REVERSAL" | "FEE";
export type EntryDirection = "DEBIT" | "CREDIT";

export interface SourceRecord {
  readonly id: string;
  readonly ingestion_job_id: string;
  readonly source_system: string;
  readonly external_ref: string;
  readonly source_revision: number;
  readonly payload_json: Record<string, unknown>;
  readonly payload_hash: string;
  readonly received_at: string;
  readonly record_status: RecordStatus;
}

export interface CanonicalTransaction {
  readonly id: string;
  readonly external_canonical_ref: string | null;
  readonly sender_account_id: string;
  readonly receiver_account_id: string;
  readonly amount_minor: number;
  readonly currency: string;
  readonly occurred_at: string;
  readonly posted_at: string;
  readonly txn_type: string;
  readonly status: TransactionStatus;
}

export interface JournalLine {
  readonly id: string;
  readonly journal_id: string;
  readonly account_id: string;
  readonly debit_minor: number;
  readonly credit_minor: number;
  readonly currency: string;
}

export interface Journal {
  readonly id: string;
  readonly branch_id: string;
  readonly posted_at: string;
  readonly journal_ref: string;
  readonly status: string;
  readonly lines: readonly JournalLine[];
}

export interface SourceRecordTransactionLink {
  readonly source_record_id: string;
  readonly transaction_id: string;
  readonly link_type: string;
}

export interface AccountingErrorDetail {
  readonly error_code: string;
  readonly message: string;
  readonly imbalance_minor: number;
  readonly journal_id: string | null;
  readonly total_debit_minor: number | null;
  readonly total_credit_minor: number | null;
}

export interface TransactionResponseItem extends CanonicalTransaction {
  readonly source_record_count: number;
  readonly source_record_ids: readonly string[];
  readonly journal_ref: string | null;
  readonly journal_status: string | null;
  readonly accounting_integrity_error: AccountingErrorDetail | null;
}

// Detector Findings Taxonomy
export type FindingType =
  | "DUPLICATE_CANDIDATE"
  | "RECONCILIATION_MISMATCH"
  | "CIRCULAR_FLOW"
  | "TRANSACTION_SPLITTING"
  | "UNBALANCED_JOURNAL";

export type FindingStatus =
  | "FLAGGED_FOR_REVIEW"
  | "IN_REVIEW"
  | "RESOLVED"
  | "FALSE_POSITIVE";

export interface FindingFacts {
  readonly Reconciliation_Variance_Minor: number;
  readonly Allowed_Variance_Minor: number;
  readonly Balance_Anomaly_Flag: boolean;
  readonly Transaction_Velocity: number;
  readonly Circular_Flow_Detected: boolean;
  readonly Cycle_Length: number;
  readonly Cycle_Duration_Minutes: number;
  readonly Splitting_Window_Sum_Minor: number;
  readonly Splitting_Window_Count: number;
  readonly Duplicate_Candidate_Flag: boolean;
  readonly Severity: string;
}

export interface DuplicateEvidence {
  readonly candidate_source_record_ids: readonly string[];
  readonly matching_account_keys: readonly string[];
  readonly amount_minor: number;
  readonly soundex_code: string;
  readonly levenshtein_distance: number;
  readonly similarity_ratio: number;
  readonly resolution_reason: string;
}

export interface ReconciliationEvidence {
  readonly left_record_id: string | null;
  readonly right_record_id: string | null;
  readonly left_amount_minor: number | null;
  readonly right_amount_minor: number | null;
  readonly variance_minor: number;
  readonly reconciliation_status: string;
  readonly reason_code: string;
}

export interface CircularFlowEvidence {
  readonly account_ids: readonly string[];
  readonly transaction_ids: readonly string[];
  readonly timestamps: readonly string[];
  readonly amounts_minor: readonly number[];
  readonly cycle_duration_minutes: number;
  readonly cycle_length: number;
}

export interface SplittingEvidence {
  readonly sender_account_id: string;
  readonly receiver_account_id: string;
  readonly window_start: string;
  readonly window_end: string;
  readonly transaction_ids: readonly string[];
  readonly transaction_amounts_minor: readonly number[];
  readonly window_sum_minor: number;
  readonly transaction_count: number;
}

export interface UnbalancedJournalEvidence {
  readonly journal_id: string;
  readonly branch_id: string;
  readonly total_debit_minor: number;
  readonly total_credit_minor: number;
  readonly imbalance_minor: number;
  readonly line_count: number;
}

export interface FindingDraft {
  readonly finding_type: FindingType;
  readonly fingerprint: string;
  readonly evidence_json: Record<string, unknown>;
  readonly transaction_ids: readonly string[];
  readonly facts: FindingFacts;
  readonly detector_config_version: number;
  readonly algorithm_version: string;
}

export interface Finding {
  readonly id: string;
  readonly finding_type: FindingType;
  readonly fingerprint: string;
  readonly status: FindingStatus;
  readonly evidence_json: Record<string, unknown>;
  readonly transaction_ids: readonly string[];
  readonly facts: FindingFacts;
  readonly detector_config_version: number;
  readonly algorithm_version: string;
  readonly created_at: string;
}

// Cases & DAG Workflows
export type CaseState =
  | "QUEUED"
  | "CLAIMED"
  | "IN_REVIEW"
  | "BLOCKED"
  | "ESCALATED"
  | "RESOLVED"
  | "CLOSED";

export type TaskState = "PENDING" | "BLOCKED" | "IN_PROGRESS" | "COMPLETED";

export interface AuditCase {
  readonly id: string;
  readonly case_code: string;
  readonly state: CaseState;
  readonly priority: number;
  readonly row_version: number;
  readonly assignee_id: string | null;
  readonly lease_until: string | null;
  readonly created_at: string;
  readonly finding_ids: readonly string[];
}

export interface WorkflowTask {
  readonly id: string;
  readonly case_id: string;
  readonly task_template_id: string;
  readonly stable_key: string;
  readonly display_name: string;
  readonly state: TaskState;
  readonly completed_at: string | null;
  readonly row_version: number;
}

export interface CaseTransitionRequest {
  readonly target_state: CaseState;
  readonly expected_row_version: number;
  readonly reason: string;
}

export interface CaseClaimRequest {
  readonly expected_row_version: number;
}

// ─── Ingestion ────────────────────────────────────────────────────────────────

export type IngestionJobState =
  | "PENDING"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "PARTIAL";

export interface IngestionJobCounts {
  readonly total_rows: number;
  readonly accepted: number;
  readonly rejected: number;
  readonly duplicate: number;
  readonly conflict: number;
  readonly pending_review: number;
}

export interface IngestionJob {
  readonly id: string;
  readonly source_system_id: string;
  readonly state: IngestionJobState;
  readonly counts: IngestionJobCounts;
  readonly errors: readonly Record<string, unknown>[];
  readonly started_at: string;
  readonly completed_at: string | null;
}

export interface IngestionRowError {
  readonly row_number: number;
  readonly external_ref: string | null;
  readonly error_code: string;
  readonly error_message: string;
  readonly raw_data: Record<string, unknown> | null;
}

// ─── Reconciliation ───────────────────────────────────────────────────────────

export type ReconciliationRunState = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";

export type ReconciliationMatchStatus =
  | "MATCHED"
  | "MISSING_LEFT"
  | "MISSING_RIGHT"
  | "MISMATCH"
  | "AMBIGUOUS"
  | "WITHIN_TOLERANCE";

export interface ReconciliationRun {
  readonly id: string;
  readonly source_left_id: string;
  readonly source_right_id: string;
  readonly start_at: string;
  readonly cutoff_at: string;
  readonly policy_version_id: string;
  readonly input_checkpoint: string | null;
  readonly state: ReconciliationRunState;
  readonly created_at: string;
  readonly completed_at: string | null;
  readonly total_count: number;
  readonly matched_count: number;
  readonly mismatch_count: number;
  readonly missing_count: number;
}

export interface ReconciliationResult {
  readonly id: string;
  readonly run_id: string;
  readonly left_record_id: string | null;
  readonly right_record_id: string | null;
  readonly status: ReconciliationMatchStatus;
  readonly variance_minor: number;
  readonly reason_code: string;
  readonly left_amount_minor: number | null;
  readonly right_amount_minor: number | null;
  readonly created_at: string;
}

export interface ReconciliationSummary {
  readonly run_id: string;
  readonly matched: number;
  readonly mismatch: number;
  readonly missing_left: number;
  readonly missing_right: number;
  readonly ambiguous: number;
  readonly within_tolerance: number;
  readonly total: number;
  readonly total_variance_minor: number;
}

// ─── Rule Engine ──────────────────────────────────────────────────────────────

export type RuleStatus = "DRAFT" | "ACTIVE" | "DEPRECATED";

export type TokenKind =
  | "INTEGER"
  | "BOOLEAN"
  | "STRING"
  | "IDENTIFIER"
  | "EQ"
  | "NEQ"
  | "LT"
  | "LTE"
  | "GT"
  | "GTE"
  | "AND"
  | "OR"
  | "NOT"
  | "LPAREN"
  | "RPAREN"
  | "EOF"
  | "UNKNOWN";

export interface RuleToken {
  readonly kind: TokenKind;
  readonly value: string;
  readonly position: number;
}

export type AstNodeKind =
  | "LITERAL"
  | "IDENTIFIER"
  | "COMPARISON"
  | "LOGICAL_AND"
  | "LOGICAL_OR"
  | "LOGICAL_NOT";

export interface AstNode {
  readonly kind: AstNodeKind;
  readonly value: string | number | boolean | null;
  readonly operator: string | null;
  readonly children: readonly AstNode[];
}

export type DiagnosticSeverity = "ERROR" | "WARNING" | "INFO";

export interface RuleDiagnostic {
  readonly severity: DiagnosticSeverity;
  readonly code: string;
  readonly message: string;
  readonly position: number | null;
  readonly token: string | null;
}

export interface RuleValidationResult {
  readonly expression: string;
  readonly tokens: readonly RuleToken[];
  readonly ast: AstNode | null;
  readonly diagnostics: readonly RuleDiagnostic[];
  readonly is_valid: boolean;
}

export interface Rule {
  readonly id: string;
  readonly name: string;
  readonly version: number;
  readonly expression: string;
  readonly status: RuleStatus;
  readonly description: string | null;
  readonly created_by: string | null;
  readonly activated_at: string | null;
}

export interface ExplanationNode {
  readonly expression: string;
  readonly result: boolean;
  readonly children: readonly ExplanationNode[];
}

export interface RuleEvaluationResult {
  readonly rule_id: string;
  readonly rule_name: string;
  readonly matched: boolean;
  readonly expression_version: number;
  readonly explanation_tree: ExplanationNode | null;
  readonly error: string | null;
}

// ─── Workflow Templates & DAG ─────────────────────────────────────────────────

export type WorkflowTemplateStatus = "DRAFT" | "ACTIVE" | "DEPRECATED";

export interface WorkflowTaskTemplate {
  readonly id: string;
  readonly template_id: string;
  readonly stable_key: string;
  readonly display_name: string;
  readonly description: string | null;
  readonly assignable_roles: readonly string[];
}

export interface WorkflowEdge {
  readonly template_id: string;
  readonly predecessor_task_stable_key: string;
  readonly successor_task_stable_key: string;
}

export interface WorkflowTemplate {
  readonly id: string;
  readonly name: string;
  readonly version: number;
  readonly status: WorkflowTemplateStatus;
  readonly description: string | null;
  readonly tasks: readonly WorkflowTaskTemplate[];
  readonly edges: readonly WorkflowEdge[];
}

export interface DagValidationError {
  readonly code: string;
  readonly message: string;
  readonly involved_keys: readonly string[];
}

export interface DagValidationResult {
  readonly is_valid: boolean;
  readonly errors: readonly DagValidationError[];
  readonly topological_order: readonly string[];
}

export interface CaseWorkflow {
  readonly case_id: string;
  readonly template_id: string;
  readonly template_version: number;
  readonly task_states: Record<string, string>;
  readonly unlockable_keys: readonly string[];
  readonly edges: readonly WorkflowEdge[];
}

export interface TaskCompleteRequest {
  readonly task_id: string;
  readonly expected_row_version: number;
  readonly notes: string | null;
}
