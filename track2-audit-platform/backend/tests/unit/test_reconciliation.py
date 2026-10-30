"""P07 one-to-one matching, journals, idempotency, and API tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.reconciliation import create_reconciliation_router
from app.engines.reconciliation.journal_balance import (
    ReconciliationJournalLine,
    evaluate_journal_balances,
)
from app.engines.reconciliation.matcher import (
    LedgerEntry,
    ReconciliationPolicy,
    ReconciliationStatus,
    reconcile_entries,
)
from app.engines.reconciliation.service import (
    InMemoryReconciliationRepository,
    run_reconciliation,
)


BASE = datetime(2026, 10, 29, 10, tzinfo=UTC)


def entry(
    transaction_id: str,
    source: str,
    reference: str,
    amount: int,
    *,
    sender: str = "A",
    receiver: str = "B",
    occurred_at: datetime = BASE,
) -> LedgerEntry:
    return LedgerEntry(
        transaction_id, source, reference, sender, receiver, amount, "INR", occurred_at
    )


def test_reference_matching_classifies_variance_fields_and_missing() -> None:
    left = (
        entry("l1", "internal", "T101", 100_000),
        entry("l2", "internal", "T102", 2_500_000),
        entry("l3", "internal", "T103", 50_000),
        entry("l4", "internal", "T104", 70_000, receiver="C"),
    )
    right = (
        entry("r1", "clearing", "T101", 100_000),
        entry("r2", "clearing", "T102", 2_450_000),
        entry("r4", "clearing", "T104", 70_000, receiver="D"),
        entry("r5", "clearing", "T105", 80_000),
    )
    results = reconcile_entries(left, right, cutoff_at=BASE)
    by_status = {result.status for result in results}
    assert by_status == {
        ReconciliationStatus.MATCHED,
        ReconciliationStatus.AMOUNT_MISMATCH,
        ReconciliationStatus.FIELD_MISMATCH,
        ReconciliationStatus.INTERNAL_ONLY,
        ReconciliationStatus.COUNTERPART_ONLY,
    }
    mismatch = next(result for result in results if result.status is ReconciliationStatus.AMOUNT_MISMATCH)
    assert mismatch.variance_minor == 50_000


def test_ambiguous_reference_never_silently_multi_matches() -> None:
    results = reconcile_entries(
        (entry("l1", "left", "DUP", 10), entry("l2", "left", "DUP", 10)),
        (entry("r1", "right", "DUP", 10),),
        cutoff_at=BASE,
    )
    assert len(results) == 1
    assert results[0].status is ReconciliationStatus.AMBIGUOUS
    assert results[0].evidence["left_candidate_ids"] == ["l1", "l2"]


def test_composite_fallback_is_one_to_one_and_pending_uses_cutoff() -> None:
    later = datetime(2026, 10, 30, 10, tzinfo=UTC)
    results = reconcile_entries(
        (entry("l1", "left", "LEFT-REF", 10), entry("late", "left", "LATE", 20, occurred_at=later)),
        (entry("r1", "right", "RIGHT-REF", 10),),
        cutoff_at=BASE,
    )
    assert results[0].status is ReconciliationStatus.MATCHED
    assert "COMPOSITE_KEY" in results[0].reason_codes
    assert results[1].status is ReconciliationStatus.PENDING_LATE


def test_journal_balance_reports_exact_variance() -> None:
    balances = evaluate_journal_balances(
        (
            ReconciliationJournalLine("j1", "1", 10_000, 0, "INR"),
            ReconciliationJournalLine("j1", "2", 0, 9_000, "INR"),
        )
    )
    assert balances[0].variance_minor == 1_000
    assert not balances[0].balanced


def test_reconciliation_run_is_idempotent_and_api_pages_results() -> None:
    repository = InMemoryReconciliationRepository()
    policy = ReconciliationPolicy(version=1)
    values = {
        "internal": (entry("l1", "internal", "T1", 100),),
        "clearing": (entry("r1", "clearing", "T1", 90),),
    }
    outcome = run_reconciliation(
        left_source_id="internal",
        right_source_id="clearing",
        left_entries=values["internal"],
        right_entries=values["clearing"],
        journal_lines=(),
        cutoff_at=BASE,
        checkpoint="cp-1",
        policy=policy,
        repository=repository,
    )
    replay = run_reconciliation(
        left_source_id="internal",
        right_source_id="clearing",
        left_entries=values["internal"],
        right_entries=values["clearing"],
        journal_lines=(),
        cutoff_at=BASE,
        checkpoint="cp-1",
        policy=policy,
        repository=repository,
    )
    assert replay.replayed and replay.run.run_id == outcome.run.run_id

    app = FastAPI()
    app.include_router(
        create_reconciliation_router(
            repository=repository,
            load_ledger=lambda source, _start, _end, _cp: values[source],
            load_journals=lambda *_args: (),
            load_policy=lambda version: ReconciliationPolicy(version=version),
        ),
        prefix="/api/v1",
    )
    client = TestClient(app)
    response = client.post(
        "/api/v1/reconciliation/runs",
        json={
            "left_source_id": "internal",
            "right_source_id": "clearing",
            "start_at": "2026-10-29T00:00:00Z",
            "end_at": "2026-10-30T00:00:00Z",
            "cutoff_at": "2026-10-29T10:00:00Z",
            "policy_version": 1,
            "snapshot_checkpoint": "cp-1",
        },
    )
    assert response.status_code == 202
    assert response.json()["data"]["replayed"] is True
    result_response = client.get(
        f"/api/v1/reconciliation/runs/{outcome.run.run_id}/results?limit=1"
    )
    assert result_response.status_code == 200
    assert result_response.json()["data"][0]["variance_minor"] == 10
