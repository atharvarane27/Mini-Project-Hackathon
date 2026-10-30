"""P06 duplicate classification, evidence and API acceptance tests."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.duplicates import create_duplicates_router
from app.engines.identity.resolver import (
    ALGORITHM_VERSION,
    CandidateBucketOverflow,
    DuplicateClassification,
    IdentityRecord,
    InMemoryDuplicateRepository,
    MatchPolicy,
    analyze_duplicates,
    compare_records,
    resolve_record,
)


NOW = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)


def record(record_id: str, **changes: object) -> IdentityRecord:
    values: dict[str, object] = {
        "record_id": record_id,
        "transaction_reference": "TXN-12345",
        "sender_account_id": "ACCOUNT-A",
        "receiver_account_id": "ACCOUNT-B",
        "sender_name": "Atharva Rane",
        "receiver_name": "Example Supplier",
        "amount_minor": 125_050,
        "currency": "INR",
        "occurred_at": NOW,
    }
    values.update(changes)
    return IdentityRecord(**values)  # type: ignore[arg-type]


class MappingProvider:
    def __init__(self, mapping: dict[str, tuple[IdentityRecord, ...]]) -> None:
        self.mapping = mapping
        self.comparison_candidates = 0

    def candidates_for(self, item: IdentityRecord) -> Iterable[IdentityRecord]:
        candidates = self.mapping.get(item.record_id, ())
        self.comparison_candidates += len(candidates)
        return candidates


def test_exact_and_typo_classifications_include_auditable_evidence() -> None:
    original = record("left")
    exact = compare_records(original, record("exact"))
    typo = compare_records(
        original,
        record(
            "typo",
            transaction_reference="TXN-12346",
            sender_name="Atharva Rnae",
        ),
    )
    assert exact.classification is DuplicateClassification.EXACT
    assert exact.score == 100
    assert typo.classification is DuplicateClassification.CANDIDATE
    assert typo.algorithm_version == ALGORITHM_VERSION
    assert typo.compared_attributes["transaction_reference_distance"] == 1
    assert "REFERENCE_WITHIN_EDIT_BOUND" in typo.reasons


def test_inverted_sides_reversal_and_recurring_transactions_are_not_matches() -> None:
    original = record("left")
    inverted = record(
        "inverted",
        sender_account_id="ACCOUNT-B",
        receiver_account_id="ACCOUNT-A",
        sender_name="Example Supplier",
        receiver_name="Atharva Rane",
    )
    reversal = record("reversal", reversal_of_record_id="left")
    recurring = record(
        "recurring",
        transaction_reference="MONTHLY-PAYMENT-999",
        occurred_at=NOW + timedelta(minutes=1),
    )
    assert compare_records(original, inverted).reasons == ("TRANSFER_SIDES_INVERTED",)
    assert compare_records(original, reversal).reasons == ("REVERSAL_PAIR",)
    result = compare_records(original, recurring)
    assert result.classification is DuplicateClassification.NON_MATCH
    assert "DISTINCT_RECURRING_TRANSACTION_GUARD" in result.reasons


def test_equal_best_candidates_remain_ambiguous_and_linked() -> None:
    original = record("left")
    candidates = (
        record("candidate-a", transaction_reference="TXN-12346"),
        record("candidate-b", transaction_reference="TXN-12344"),
    )
    results = resolve_record(original, candidates)
    assert {item.classification for item in results} == {
        DuplicateClassification.AMBIGUOUS
    }
    assert {item.right_record_id for item in results} == {
        "candidate-a",
        "candidate-b",
    }


def test_blocked_candidate_counts_are_far_below_quadratic() -> None:
    records = [
        record(
            f"record-{index}",
            transaction_reference=f"REF-{index}",
            sender_account_id=f"S-{index}",
        )
        for index in range(1_000)
    ]
    mapping = {
        item.record_id: (records[index ^ 1],)
        for index, item in enumerate(records)
    }
    provider = MappingProvider(mapping)
    saved = analyze_duplicates(records, provider, InMemoryDuplicateRepository())
    assert provider.comparison_candidates == 1_000
    assert provider.comparison_candidates < len(records) ** 2 // 100
    assert len(saved) == 500


def test_skewed_bucket_is_stopped_at_explicit_bound() -> None:
    with pytest.raises(CandidateBucketOverflow, match="bound"):
        resolve_record(
            record("left"),
            (record(f"candidate-{index}") for index in range(6)),
            MatchPolicy(max_candidates_per_record=5),
        )


def test_duplicates_api_filters_and_preserves_record_links() -> None:
    repository = InMemoryDuplicateRepository()
    repository.save(
        [compare_records(record("left"), record("right"))]
    )
    app = FastAPI()
    app.include_router(create_duplicates_router(repository), prefix="/api/v1")
    response = TestClient(app).get(
        "/api/v1/duplicates", params={"classification": "EXACT"}
    )
    assert response.status_code == 200
    assert response.json()["meta"]["returned"] == 1
    assert response.json()["data"][0]["left_record_id"] == "left"
    assert response.json()["data"][0]["right_record_id"] == "right"
