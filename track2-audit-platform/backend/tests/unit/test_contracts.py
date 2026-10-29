from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.cases import AuditCase, CaseState, TaskState, WorkflowTask
from app.schemas.common import (
    OutboxEvent,
    OutboxStatus,
    UserRole,
    compute_finding_fingerprint,
    compute_source_record_fingerprint,
)
from app.schemas.detectors import (
    CircularFlowEvidence,
    DuplicateEvidence,
    Finding,
    FindingDraft,
    FindingFacts,
    FindingStatus,
    FindingType,
    ReconciliationEvidence,
    SplittingEvidence,
    UnbalancedJournalEvidence,
)
from app.schemas.transactions import (
    CanonicalTransaction,
    Journal,
    JournalLine,
    RecordStatus,
    SourceRecord,
    TransactionStatus,
)


class TestCommonContracts:
    def test_deterministic_source_record_fingerprint(self) -> None:
        fp1 = compute_source_record_fingerprint("core_bank", "TXN-999", 1)
        fp2 = compute_source_record_fingerprint("CORE_BANK", "TXN-999", 1)
        fp3 = compute_source_record_fingerprint("CORE_BANK", "TXN-999", 2)
        assert fp1 == fp2
        assert fp1 != fp3
        assert len(fp1) == 64

    def test_utc_datetime_validation(self) -> None:
        event = OutboxEvent(
            id="out-1",
            event_type="INGESTION",
            entity_id="src-1",
            payload_json={"k": "v"},
            status=OutboxStatus.PENDING,
            attempt_count=0,
            created_at="2026-10-29T12:00:00Z",  # type: ignore[arg-type]
        )
        assert event.created_at.tzinfo is not None
        assert event.created_at == datetime(2026, 10, 29, 12, 0, 0, tzinfo=UTC)

    def test_reject_naive_datetime(self) -> None:
        with pytest.raises(ValidationError):
            OutboxEvent(
                id="out-1",
                event_type="INGESTION",
                entity_id="src-1",
                payload_json={},
                created_at="2026-10-29T12:00:00",  # type: ignore[arg-type]
            )

    def test_role_matrix_completeness(self) -> None:
        roles = {r.value for r in UserRole}
        assert roles == {"ADMIN", "AUDITOR", "REVIEWER", "VIEWER", "SYSTEM_WORKER"}


class TestTransactionContracts:
    def test_canonical_transaction_valid(self) -> None:
        txn = CanonicalTransaction(
            id="txn-1",
            external_canonical_ref="REF-1",
            sender_account_id="acc-1",
            receiver_account_id="acc-2",
            amount_minor=100000,
            currency="INR",
            occurred_at="2026-10-29T10:00:00Z",  # type: ignore[arg-type]
            posted_at="2026-10-29T10:01:00Z",  # type: ignore[arg-type]
            txn_type="NEFT",
            status=TransactionStatus.POSTED,
        )
        assert txn.amount_minor == 100000
        assert txn.currency == "INR"

    def test_reject_float_money(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalTransaction(
                id="txn-1",
                sender_account_id="acc-1",
                receiver_account_id="acc-2",
                amount_minor=1000.50,  # type: ignore[arg-type]
                currency="INR",
                occurred_at="2026-10-29T10:00:00Z",  # type: ignore[arg-type]
                posted_at="2026-10-29T10:01:00Z",  # type: ignore[arg-type]
                txn_type="NEFT",
            )

    def test_reject_non_positive_amount(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalTransaction(
                id="txn-1",
                sender_account_id="acc-1",
                receiver_account_id="acc-2",
                amount_minor=0,
                currency="INR",
                occurred_at="2026-10-29T10:00:00Z",  # type: ignore[arg-type]
                posted_at="2026-10-29T10:01:00Z",  # type: ignore[arg-type]
                txn_type="NEFT",
            )

    def test_reject_invalid_currency(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalTransaction(
                id="txn-1",
                sender_account_id="acc-1",
                receiver_account_id="acc-2",
                amount_minor=5000,
                currency="IN",  # type: ignore[arg-type]
                occurred_at="2026-10-29T10:00:00Z",  # type: ignore[arg-type]
                posted_at="2026-10-29T10:01:00Z",  # type: ignore[arg-type]
                txn_type="NEFT",
            )

    def test_journal_line_exact_one_side_positive(self) -> None:
        # Valid debit
        line_debit = JournalLine(
            id="jl-1",
            journal_id="j-1",
            account_id="acc-1",
            debit_minor=1000,
            credit_minor=0,
            currency="INR",
        )
        assert line_debit.debit_minor == 1000

        # Valid credit
        line_credit = JournalLine(
            id="jl-2",
            journal_id="j-1",
            account_id="acc-2",
            debit_minor=0,
            credit_minor=1000,
            currency="INR",
        )
        assert line_credit.credit_minor == 1000

        # Both positive rejected
        with pytest.raises(ValidationError):
            JournalLine(
                id="jl-3",
                journal_id="j-1",
                account_id="acc-1",
                debit_minor=1000,
                credit_minor=500,
                currency="INR",
            )

        # Both zero rejected
        with pytest.raises(ValidationError):
            JournalLine(
                id="jl-4",
                journal_id="j-1",
                account_id="acc-1",
                debit_minor=0,
                credit_minor=0,
                currency="INR",
            )

    def test_journal_balancing(self) -> None:
        l1 = JournalLine(
            id="jl-1", journal_id="j-1", account_id="a1", debit_minor=5000, credit_minor=0, currency="INR"
        )
        l2 = JournalLine(
            id="jl-2", journal_id="j-1", account_id="a2", debit_minor=0, credit_minor=5000, currency="INR"
        )
        journal = Journal(
            id="j-1",
            branch_id="br-1",
            posted_at="2026-10-29T10:00:00Z",  # type: ignore[arg-type]
            journal_ref="JREF-01",
            lines=(l1, l2),
        )
        assert journal.is_balanced() is True

        l3_unbalanced = JournalLine(
            id="jl-3", journal_id="j-2", account_id="a3", debit_minor=0, credit_minor=4000, currency="INR"
        )
        unbalanced_journal = Journal(
            id="j-2",
            branch_id="br-1",
            posted_at="2026-10-29T10:00:00Z",  # type: ignore[arg-type]
            journal_ref="JREF-02",
            lines=(l1, l3_unbalanced),
        )
        assert unbalanced_journal.is_balanced() is False


class TestDetectorContracts:
    def test_all_detector_types_serialize_to_same_finding_contract(self) -> None:
        # 1. Duplicate
        dup_ev = DuplicateEvidence(
            candidate_source_record_ids=("src-1", "src-2"),
            matching_account_keys=("ACC100",),
            amount_minor=25000,
            soundex_code="A230",
            levenshtein_distance=1,
            similarity_ratio=0.95,
            resolution_reason="Phonetic description match with identical amount band",
        )
        draft1 = FindingDraft(
            finding_type=FindingType.DUPLICATE_CANDIDATE,
            fingerprint=compute_finding_fingerprint("DUPLICATE_CANDIDATE", "src-1", "src-2"),
            evidence_json=dup_ev.model_dump(),
            transaction_ids=("txn-1",),
            facts=FindingFacts(Duplicate_Candidate_Flag=True, Severity="LOW"),
            algorithm_version="levenshtein-v1",
        )

        # 2. Reconciliation
        recon_ev = ReconciliationEvidence(
            left_record_id="src-left",
            right_record_id="src-right",
            left_amount_minor=50000,
            right_amount_minor=45000,
            variance_minor=5000,
            reconciliation_status="AMOUNT_MISMATCH",
            reason_code="VARIANCE_EXCEEDS_THRESHOLD",
        )
        draft2 = FindingDraft(
            finding_type=FindingType.RECONCILIATION_MISMATCH,
            fingerprint=compute_finding_fingerprint("RECONCILIATION_MISMATCH", "src-left", "src-right"),
            evidence_json=recon_ev.model_dump(),
            facts=FindingFacts(Reconciliation_Variance_Minor=5000, Severity="HIGH"),
            algorithm_version="recon-matcher-v1",
        )

        # 3. Circular Flow
        circ_ev = CircularFlowEvidence(
            account_ids=("A", "B", "C", "A"),
            transaction_ids=("t1", "t2", "t3"),
            timestamps=("2026-10-29T10:00:00Z", "2026-10-29T10:10:00Z", "2026-10-29T10:20:00Z"),  # type: ignore[arg-type]
            amounts_minor=(100000, 99000, 98000),
            cycle_duration_minutes=20,
            cycle_length=3,
        )
        draft3 = FindingDraft(
            finding_type=FindingType.CIRCULAR_FLOW,
            fingerprint=compute_finding_fingerprint("CIRCULAR_FLOW", "t1", "t2", "t3"),
            evidence_json=circ_ev.model_dump(),
            transaction_ids=("t1", "t2", "t3"),
            facts=FindingFacts(Circular_Flow_Detected=True, Cycle_Length=3, Cycle_Duration_Minutes=20, Severity="CRITICAL"),
            algorithm_version="cycle-dfs-v1",
        )

        # 4. Splitting
        split_ev = SplittingEvidence(
            sender_account_id="acc-s",
            receiver_account_id="acc-r",
            window_start="2026-10-29T10:00:00Z",  # type: ignore[arg-type]
            window_end="2026-10-29T10:50:00Z",  # type: ignore[arg-type]
            transaction_ids=("t1", "t2", "t3"),
            transaction_amounts_minor=(4000000, 3500000, 3000000),
            window_sum_minor=10500000,
            transaction_count=3,
        )
        draft4 = FindingDraft(
            finding_type=FindingType.TRANSACTION_SPLITTING,
            fingerprint=compute_finding_fingerprint("TRANSACTION_SPLITTING", "acc-s", "acc-r"),
            evidence_json=split_ev.model_dump(),
            transaction_ids=("t1", "t2", "t3"),
            facts=FindingFacts(Splitting_Window_Sum_Minor=10500000, Splitting_Window_Count=3, Severity="HIGH"),
            algorithm_version="sliding-window-v1",
        )

        # 5. Unbalanced Journal
        unb_ev = UnbalancedJournalEvidence(
            journal_id="j-99",
            branch_id="br-01",
            total_debit_minor=10000,
            total_credit_minor=9000,
            imbalance_minor=1000,
            line_count=2,
        )
        draft5 = FindingDraft(
            finding_type=FindingType.UNBALANCED_JOURNAL,
            fingerprint=compute_finding_fingerprint("UNBALANCED_JOURNAL", "j-99"),
            evidence_json=unb_ev.model_dump(),
            facts=FindingFacts(Balance_Anomaly_Flag=True, Severity="HIGH"),
            algorithm_version="journal-check-v1",
        )

        for draft in (draft1, draft2, draft3, draft4, draft5):
            finding = Finding(
                id="find-uuid",
                finding_type=draft.finding_type,
                fingerprint=draft.fingerprint,
                status=FindingStatus.FLAGGED_FOR_REVIEW,
                evidence_json=draft.evidence_json,
                transaction_ids=draft.transaction_ids,
                facts=draft.facts,
                detector_config_version=draft.detector_config_version,
                algorithm_version=draft.algorithm_version,
                created_at="2026-10-29T11:00:00Z",  # type: ignore[arg-type]
            )
            dump = finding.model_dump()
            assert "finding_type" in dump
            assert "fingerprint" in dump
            assert "facts" in dump
            assert "evidence_json" in dump
            assert "created_at" in dump


class TestCasesAndWorkflowContracts:
    def test_audit_case_priority_bounds(self) -> None:
        case = AuditCase(
            id="c-1",
            case_code="CASE-001",
            state=CaseState.QUEUED,
            priority=85,
            row_version=1,
            created_at="2026-10-29T10:00:00Z",  # type: ignore[arg-type]
        )
        assert case.priority == 85

        with pytest.raises(ValidationError):
            AuditCase(
                id="c-2",
                case_code="CASE-002",
                priority=101,  # out of bounds > 100
                created_at="2026-10-29T10:00:00Z",  # type: ignore[arg-type]
            )

        with pytest.raises(ValidationError):
            AuditCase(
                id="c-3",
                case_code="CASE-003",
                priority=-1,  # out of bounds < 0
                created_at="2026-10-29T10:00:00Z",  # type: ignore[arg-type]
            )

    def test_workflow_task_stable_key_preservation(self) -> None:
        task = WorkflowTask(
            id="t-1",
            case_id="c-1",
            task_template_id="tpl-1",
            stable_key="Branch_Ledge_Clearance",
            display_name="Branch Ledger Clearance",
            state=TaskState.PENDING,
            row_version=1,
        )
        assert task.stable_key == "Branch_Ledge_Clearance"


class TestImmutabilityFrozenModels:
    def test_models_are_frozen(self) -> None:
        src = SourceRecord(
            id="s-1",
            ingestion_job_id="j-1",
            source_system="CBS",
            external_ref="E1",
            payload_json={},
            payload_hash="hash",
            received_at="2026-10-29T10:00:00Z",  # type: ignore[arg-type]
            record_status=RecordStatus.ACCEPTED,
        )
        with pytest.raises(ValidationError):
            src.source_system = "NEW"  # type: ignore[misc]

        facts = FindingFacts(Transaction_Velocity=5)
        with pytest.raises(ValidationError):
            facts.Transaction_Velocity = 10  # type: ignore[misc]
