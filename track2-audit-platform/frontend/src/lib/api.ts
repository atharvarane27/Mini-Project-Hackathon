import type { DataEnvelope, ErrorEnvelope } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

let accessToken: string | null = null;
let currentRoles: string[] = [];

export function setSession(token: string | null, roles: string[] = []): void {
  accessToken = token;
  currentRoles = roles;
}

export function session(): { token: string | null; roles: string[] } {
  return { token: accessToken, roles: [...currentRoles] };
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public requestId?: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<DataEnvelope<T>> {
  const headers = new Headers(init.headers);
  headers.set("X-Request-ID", crypto.randomUUID());
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}/api/v1${path}`, { ...init, headers });
  const text = await response.text();
  const payload = text ? JSON.parse(text) as DataEnvelope<T> | ErrorEnvelope : null;
  if (response.status === 204) return { data: undefined as T, meta: {}, request_id: response.headers.get("X-Request-ID") ?? "no-content" } as DataEnvelope<T>;
  if (!response.ok || (payload && "error" in payload)) {
    const error = payload && "error" in payload ? payload.error : { code: "HTTP_ERROR", message: `Request failed (${response.status})` };
    throw new ApiError(response.status, error.code, error.message, payload?.request_id);
  }
  if (!payload || !("data" in payload)) throw new ApiError(response.status, "INVALID_RESPONSE", "API returned an invalid response");
  return payload;
}

export interface LoginSession { access_token: string; token_type: string; expires_at: string; roles: string[] }
export interface IngestionJob { job_id: string; status: "RUNNING" | "COMPLETED" | "FAILED"; source_system: string; source_file: string; file_hash: string; last_row_number: number; processed_count: number; accepted_count: number; rejected_count: number; duplicate_count: number; failure_message: string | null }
export interface Transaction { transaction_id: string; transaction_reference: string; sender_account_id: string; receiver_account_id: string; amount_minor: number; currency: string; occurred_at: string; transaction_type: string; status: string; source_record_ids: string[]; review_required: boolean }
export interface DuplicateEvidence { left_record_id: string; right_record_id: string; classification: string; score: number; reasons: string[]; algorithm_version: string }
export interface Finding { finding_id: string; type: string; fingerprint: string; transaction_ids: string[]; facts: Record<string, unknown>; evidence: Record<string, unknown>; detector_config_version: number; algorithm_version: string; status: string }
export interface AuditCase { case_id: string; case_code: string; finding_ids: string[]; rule_version_id: string; priority: number; state: string; row_version: number; assignee_id: string | null; created_at: string }
export interface ActivityEntry { activity_id: string; actor_id: string; action: string; object_id: string; object_version: number; occurred_at: string; request_id: string; entry_hash: string }
export interface Metrics { ingestion_source_records: number; canonical_transactions: number; duplicate_evidence: number; circular_findings: number; splitting_findings: number; case_count: number; activity_count: number }
export interface RunSummary { run_id: string; status: string; finding_count?: number; finding_ids?: string[]; result_count?: number; classification_counts?: Record<string, number>; replayed: boolean }
export interface RuleValidation { valid: boolean; tokens: unknown[]; ast: Record<string, unknown>; result_type: string }

export async function login(username: string, password: string): Promise<LoginSession> {
  const payload = await request<LoginSession>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
  setSession(payload.data.access_token, payload.data.roles);
  return payload.data;
}

export async function logout(): Promise<void> {
  try { await request<never>("/auth/logout", { method: "POST" }); } finally { setSession(null); }
}

export async function createIngestionJob(file: File, sourceSystem: string): Promise<IngestionJob> {
  const body = new FormData();
  body.append("file", file);
  body.append("source_system", sourceSystem.trim());
  const payload = await request<IngestionJob>("/ingestion/jobs", { method: "POST", body, headers: { "Idempotency-Key": `ui-${crypto.randomUUID()}` } });
  return payload.data;
}

export const getMetrics = async () => (await request<Metrics>("/metrics")).data;
export const listTransactions = async () => (await request<Transaction[]>("/transactions?limit=500")).data;
export const listDuplicates = async () => (await request<DuplicateEvidence[]>("/duplicates?limit=500")).data;
export const listFindings = async () => (await request<Finding[]>("/findings?limit=500")).data;
export const listCases = async () => (await request<AuditCase[]>("/cases?limit=500")).data;
export const listActivity = async () => (await request<ActivityEntry[]>("/activity?limit=500")).data;

export async function runDetector(kind: "circular" | "splitting", startAt: string, endAt: string): Promise<RunSummary> {
  return (await request<RunSummary>(`/detectors/${kind}/runs`, { method: "POST", body: JSON.stringify({ start_at: startAt, end_at: endAt, policy_version: 1, snapshot_checkpoint: `${kind}-${Date.now()}` }) })).data;
}

export async function runReconciliation(left: string, right: string, startAt: string, endAt: string): Promise<RunSummary> {
  return (await request<RunSummary>("/reconciliation/runs", { method: "POST", body: JSON.stringify({ left_source_id: left, right_source_id: right, start_at: startAt, end_at: endAt, cutoff_at: endAt, policy_version: 1, snapshot_checkpoint: `reconciliation-${Date.now()}` }) })).data;
}

export async function validateRule(expression: string): Promise<RuleValidation> {
  return (await request<RuleValidation>("/rules/validate", { method: "POST", body: JSON.stringify({ expression }) })).data;
}

export async function createRule(name: string, expression: string): Promise<Record<string, unknown>> {
  return (await request<Record<string, unknown>>("/rules", { method: "POST", body: JSON.stringify({ name, expression }), headers: { "X-Actor-ID": "demo-admin", "X-Roles": "ADMIN", "Idempotency-Key": crypto.randomUUID() } })).data;
}

export async function claimCase(item: AuditCase): Promise<AuditCase> {
  return (await request<AuditCase>(`/cases/${item.case_id}/claim`, { method: "POST", body: JSON.stringify({ expected_version: item.row_version, worker_id: "demo-admin", lease_seconds: 300 }) })).data;
}

export async function createCase(findingIds: string[], priority = 70): Promise<AuditCase> {
  return (await request<AuditCase>("/cases", { method: "POST", body: JSON.stringify({ finding_ids: findingIds, rule_version_id: "system-default-v1", priority }), headers: { "X-Actor-ID": "demo-admin" } })).data;
}

export async function validateWorkflow(nodes: { task_id: string; name: string }[], edges: { prerequisite_id: string; dependent_id: string }[]): Promise<{ valid: boolean; topological_order: string[] }> {
  return (await request<{ valid: boolean; topological_order: string[] }>("/workflows/validate", { method: "POST", body: JSON.stringify({ nodes, edges }) })).data;
}

export async function health(): Promise<Record<string, unknown>> {
  return (await request<Record<string, unknown>>("/health")).data;
}
