"""Scaffold for backend/tests/unit/test_reconciliation; implementation pending."""

from __future__ import annotations

from datetime import datetime, timezone

from app.engines.reconciliation.journal_balance import validate_journal_balance
from app.engines.reconciliation.matcher import ReconciliationMatcher, ReconciliationStatus, compute_run_id


class TestReconciliationMatcher:
    def test_amount_mismatch_reports_paise_variance(self) -> None:
        left = [{
            "id": "L-1",
            "external_ref": "REF-100",
            "amount_minor": 25000,
            "currency": "INR",
            "source": "left",
            "occurred_at": "2024-01-10T10:00:00Z",
        }]
        right = [{
            "id": "R-1",
            "external_ref": "REF-100",
            "amount_minor": 24500,
            "currency": "INR",
            "source": "right",
            "occurred_at": "2024-01-10T10:00:05Z",
        }]
        result = ReconciliationMatcher().match_records(left, right, cutoff_at=datetime(2024, 1, 12, tzinfo=timezone.utc), currency="INR")[0]
        assert result.status == ReconciliationStatus.AMOUNT_MISMATCH
        assert result.variance_minor == 500
        assert result.reason_code == "AMOUNT_MISMATCH"

    def test_missing_past_cutoff_is_pending_late(self) -> None:
        left = [{
            "id": "L-2",
            "external_ref": "REF-200",
            "amount_minor": 5200,
            "currency": "INR",
            "source": "left",
            "occurred_at": "2024-01-15T08:00:00Z",
        }]
        right: list[dict[str, object]] = []
        result = ReconciliationMatcher().match_records(left, right, cutoff_at=datetime(2024, 1, 15, 7, 0, tzinfo=timezone.utc), currency="INR")[0]
        assert result.status == ReconciliationStatus.PENDING_LATE

    def test_late_arrival_is_reported_as_pending_late(self) -> None:
        left = [{
            "id": "L-3",
            "external_ref": "REF-300",
            "amount_minor": 12000,
            "currency": "INR",
            "source": "left",
            "occurred_at": "2024-01-15T08:00:00Z",
        }]
        right = [{
            "id": "R-3",
            "external_ref": "REF-300",
            "amount_minor": 12000,
            "currency": "INR",
            "source": "right",
            "occurred_at": "2024-01-15T09:00:00Z",
        }]
        result = ReconciliationMatcher().match_records(left, right, cutoff_at=datetime(2024, 1, 15, 8, 30, tzinfo=timezone.utc), currency="INR")[0]
        assert result.status == ReconciliationStatus.PENDING_LATE

    def test_reversal_sign_is_treated_as_match(self) -> None:
        left = [{
            "id": "L-4",
            "external_ref": "REF-400",
            "amount_minor": 25000,
            "currency": "INR",
            "source": "left",
            "occurred_at": "2024-01-10T08:00:00Z",
        }]
        right = [{
            "id": "R-4",
            "external_ref": "REF-400",
            "amount_minor": -25000,
            "currency": "INR",
            "source": "right",
            "occurred_at": "2024-01-10T08:00:02Z",
        }]
        result = ReconciliationMatcher().match_records(left, right, cutoff_at=datetime(2024, 1, 12, tzinfo=timezone.utc), currency="INR")[0]
        assert result.status == ReconciliationStatus.MATCHED

    def test_unbalanced_journal_reports_unbalanced_journal(self) -> None:
        journal = {
            "id": "J-UNBAL-01",
            "lines": [
                {"debit_minor": 10000, "credit_minor": 0},
                {"debit_minor": 0, "credit_minor": 9000},
            ],
        }
        result = validate_journal_balance(journal)
        assert result.status == "UNBALANCED_JOURNAL"
        assert result.imbalance_minor == 1000

    def test_run_id_is_stable_and_idempotent(self) -> None:
        first = compute_run_id(
            source_left_id="SRC-A",
            source_right_id="SRC-B",
            start_at="2024-01-01T00:00:00Z",
            cutoff_at="2024-01-31T00:00:00Z",
            currency="INR",
            policy_version="p07",
            input_checkpoint="cp-42",
        )
        second = compute_run_id(
            source_left_id="SRC-A",
            source_right_id="SRC-B",
            start_at="2024-01-01T00:00:00Z",
            cutoff_at="2024-01-31T00:00:00Z",
            currency="INR",
            policy_version="p07",
            input_checkpoint="cp-42",
        )
        assert first == second
        assert len(first) == 32
