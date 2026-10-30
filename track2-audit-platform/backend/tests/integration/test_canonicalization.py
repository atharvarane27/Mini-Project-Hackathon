"""P04 canonical transfer, provenance, and journal acceptance tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.transactions import create_transactions_router
from app.ingestion.canonicalizer import (
    AcceptedSourceTransfer,
    InMemoryCanonicalRepository,
    SourceRevisionConflict,
    UnbalancedJournalError,
    validate_balanced_journal,
)


NOW = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)


def source(source_id: str, **changes: object) -> AcceptedSourceTransfer:
    values: dict[str, object] = {
        "source_record_id": source_id,
        "source_system": "branch-ledger",
        "external_id": "EXT-001",
        "revision": 1,
        "transaction_reference": "TXN-001",
        "sender_account_id": "ACCOUNT-A",
        "receiver_account_id": "ACCOUNT-B",
        "amount_minor": 125_050,
        "currency": "INR",
        "occurred_at": NOW,
    }
    values.update(changes)
    return AcceptedSourceTransfer(**values)  # type: ignore[arg-type]


def test_repeated_transport_copies_map_to_one_canonical_event() -> None:
    repository = InMemoryCanonicalRepository()
    first = repository.canonicalize(source("source-1"))
    copy = repository.canonicalize(source("source-2"))

    assert first.replayed is False
    assert copy.replayed is True
    assert copy.transaction.transaction_id == first.transaction.transaction_id
    assert copy.transaction.source_record_ids == ("source-1", "source-2")
    assert len(repository.downstream_snapshot()) == 1


def test_changed_payload_under_same_source_revision_is_conflict() -> None:
    repository = InMemoryCanonicalRepository()
    repository.canonicalize(source("source-1"))
    with pytest.raises(SourceRevisionConflict, match="changed payload"):
        repository.canonicalize(source("source-2", amount_minor=999_999))
    assert len(repository.downstream_snapshot()) == 1


def test_distinct_references_with_same_economics_are_retained_for_review() -> None:
    repository = InMemoryCanonicalRepository()
    first = repository.canonicalize(source("source-1"))
    second = repository.canonicalize(
        source(
            "source-2",
            external_id="EXT-002",
            transaction_reference="TXN-ALTERNATE",
        )
    )
    snapshot = repository.downstream_snapshot()
    assert len(snapshot) == 2
    assert second.transaction.review_required is True
    assert next(
        item for item in snapshot if item.transaction_id == first.transaction.transaction_id
    ).review_required is True


def test_correction_creates_traceable_reversal_without_mutating_original() -> None:
    repository = InMemoryCanonicalRepository()
    original = repository.canonicalize(source("source-1")).transaction
    correction = repository.canonicalize(
        source(
            "source-correction",
            external_id="EXT-CORRECTION",
            transaction_reference="TXN-001-REV",
            correction_of_reference="TXN-001",
        )
    ).transaction
    assert correction.reversal_of_transaction_id == original.transaction_id
    assert correction.sender_account_id == original.receiver_account_id
    assert correction.receiver_account_id == original.sender_account_id
    assert original in repository.downstream_snapshot()


def test_unbalanced_journal_is_flagged_and_balanced_postings_remain_traceable() -> None:
    repository = InMemoryCanonicalRepository()
    result = repository.canonicalize(source("source-1"))
    validate_balanced_journal(result.journal)
    assert {posting.source_record_ids for posting in result.journal} == {
        ("source-1",)
    }
    bad = replace(result.journal[1], credit_minor=100)
    with pytest.raises(UnbalancedJournalError, match="totals differ"):
        validate_balanced_journal((result.journal[0], bad))
    assert repository.journal_for(result.transaction.transaction_id) == result.journal


def test_transactions_api_searches_canonical_events_only() -> None:
    repository = InMemoryCanonicalRepository()
    repository.canonicalize(source("source-1"))
    repository.canonicalize(source("source-2"))
    app = FastAPI()
    app.include_router(create_transactions_router(repository), prefix="/api/v1")
    response = TestClient(app).get(
        "/api/v1/transactions", params={"account_id": "ACCOUNT-A"}
    )
    assert response.status_code == 200
    assert response.json()["meta"]["returned"] == 1
    assert response.json()["data"][0]["source_record_ids"] == [
        "source-1", "source-2"
    ]
