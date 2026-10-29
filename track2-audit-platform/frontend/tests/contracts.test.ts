import { describe, it, expect } from "vitest";
import type {
  ApiResponse,
  PaginatedResponse,
  ApiErrorResponse,
  CanonicalTransaction,
  Finding,
  AuditCase,
  WorkflowTask,
  CaseWorkflow,
  IngestionJob,
  OutboxEvent,
} from "../src/lib/types";

describe("Frontend Type Contracts & Sample Payload Verification", () => {
  it("validates CanonicalTransaction payload conforms to type", () => {
    const txnResponse: PaginatedResponse<CanonicalTransaction> = {
      data: [
        {
          id: "txn-c101",
          external_canonical_ref: "CANON-2026-10-001",
          sender_account_id: "acc-br01-1001",
          receiver_account_id: "acc-br02-2002",
          amount_minor: 2500000,
          currency: "INR",
          occurred_at: "2026-10-29T10:15:30.000000Z",
          posted_at: "2026-10-29T10:15:32.000000Z",
          txn_type: "NEFT_TRANSFER",
          status: "POSTED",
        },
      ],
      meta: {
        next_cursor: "cursor-txn-c101",
        has_more: false,
        total_count: 1,
        limit: 1,
      },
      request_id: "req-txn-01",
    };

    expect(txnResponse.data[0].amount_minor).toBe(2500000);
    expect(Number.isInteger(txnResponse.data[0].amount_minor)).toBe(true);
    expect(txnResponse.data[0].currency).toBe("INR");
  });

  it("validates Finding payload and fact names conform to type", () => {
    const findingResponse: ApiResponse<Finding> = {
      data: {
        id: "find-circ-001",
        finding_type: "CIRCULAR_FLOW",
        fingerprint: "a3f5c71b82e9d0124a9e5b1287c9f4d1e2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7",
        status: "FLAGGED_FOR_REVIEW",
        algorithm_version: "cycle-dfs-v1",
        detector_config_version: 1,
        transaction_ids: ["txn-101", "txn-102", "txn-103"],
        facts: {
          Reconciliation_Variance_Minor: 0,
          Allowed_Variance_Minor: 0,
          Balance_Anomaly_Flag: false,
          Transaction_Velocity: 3,
          Circular_Flow_Detected: true,
          Cycle_Length: 3,
          Cycle_Duration_Minutes: 18,
          Splitting_Window_Sum_Minor: 0,
          Splitting_Window_Count: 0,
          Duplicate_Candidate_Flag: false,
          Severity: "HIGH",
        },
        evidence_json: {
          account_ids: ["acc-A", "acc-B", "acc-C", "acc-A"],
          transaction_ids: ["txn-101", "txn-102", "txn-103"],
          amounts_minor: [50000000, 49500000, 49000000],
          timestamps: [
            "2026-10-29T11:00:00Z",
            "2026-10-29T11:08:00Z",
            "2026-10-29T11:18:00Z",
          ],
          cycle_duration_minutes: 18,
          cycle_length: 3,
        },
        created_at: "2026-10-29T11:20:00.000000Z",
      },
      meta: {},
      request_id: "req-find-01",
    };

    expect(findingResponse.data.finding_type).toBe("CIRCULAR_FLOW");
    expect(findingResponse.data.facts.Circular_Flow_Detected).toBe(true);
    expect(findingResponse.data.facts.Cycle_Length).toBe(3);
  });

  it("validates AuditCase payload conforms to type", () => {
    const caseResponse: ApiResponse<AuditCase> = {
      data: {
        id: "case-9001",
        case_code: "CASE-2026-009001",
        state: "CLAIMED",
        priority: 85,
        row_version: 2,
        assignee_id: "usr-auditor-12",
        lease_until: "2026-10-29T19:00:00.000000Z",
        created_at: "2026-10-29T11:30:00.000000Z",
        finding_ids: ["find-circ-001"],
      },
      meta: {},
      request_id: "req-claim-01",
    };

    expect(caseResponse.data.priority).toBe(85);
    expect(caseResponse.data.row_version).toBe(2);
    expect(caseResponse.data.state).toBe("CLAIMED");
  });

  it("validates CaseWorkflow payload conforms to type", () => {
    const workflowResponse: ApiResponse<CaseWorkflow> = {
      data: {
        case_id: "case-9001",
        template_id: "tpl-audit-flow",
        template_version: 1,
        task_states: {
          Branch_Ledge_Clearance: "COMPLETED",
          External_Whistleblower_Audit: "IN_PROGRESS",
          Escalation_Status: "BLOCKED",
        },
        unlockable_keys: [],
        edges: [
          {
            template_id: "tpl-audit-flow",
            predecessor_task_stable_key: "Branch_Ledge_Clearance",
            successor_task_stable_key: "Escalation_Status",
          },
          {
            template_id: "tpl-audit-flow",
            predecessor_task_stable_key: "External_Whistleblower_Audit",
            successor_task_stable_key: "Escalation_Status",
          },
        ],
      },
      meta: {},
      request_id: "req-wf-01",
    };

    expect(workflowResponse.data.case_id).toBe("case-9001");
    expect(workflowResponse.data.task_states["Branch_Ledge_Clearance"]).toBe("COMPLETED");
    expect(workflowResponse.data.edges).toHaveLength(2);
  });

  it("validates WorkflowTask list conforms to type", () => {
    const tasksResponse: PaginatedResponse<WorkflowTask> = {
      data: [
        {
          id: "task-w1",
          case_id: "case-9001",
          task_template_id: "tpl-blc",
          stable_key: "Branch_Ledge_Clearance",
          display_name: "Branch Ledger Clearance",
          state: "COMPLETED",
          completed_at: "2026-10-29T12:00:00Z",
          row_version: 2,
        },
        {
          id: "task-w2",
          case_id: "case-9001",
          task_template_id: "tpl-ewa",
          stable_key: "External_Whistleblower_Audit",
          display_name: "External Whistleblower Audit",
          state: "IN_PROGRESS",
          completed_at: null,
          row_version: 1,
        },
        {
          id: "task-w3",
          case_id: "case-9001",
          task_template_id: "tpl-esc",
          stable_key: "Escalation_Status",
          display_name: "Senior Reviewer Escalation",
          state: "BLOCKED",
          completed_at: null,
          row_version: 1,
        },
      ],
      meta: {
        next_cursor: null,
        has_more: false,
        total_count: 3,
        limit: 50,
      },
      request_id: "req-tasks-01",
    };

    expect(tasksResponse.data).toHaveLength(3);
    expect(tasksResponse.data[0].stable_key).toBe("Branch_Ledge_Clearance");
    expect(tasksResponse.data[2].state).toBe("BLOCKED");
  });

  it("validates ApiErrorResponse conforms to standard error envelope", () => {
    const errorResponse: ApiErrorResponse = {
      error: {
        code: "VALIDATION_ERROR",
        message: "Invalid minor currency units",
        details: { field: "amount_minor", reason: "Cannot be float" },
      },
      request_id: "req-err-01",
    };

    expect(errorResponse.error.code).toBe("VALIDATION_ERROR");
    expect(errorResponse.request_id).toBe("req-err-01");
  });
});
