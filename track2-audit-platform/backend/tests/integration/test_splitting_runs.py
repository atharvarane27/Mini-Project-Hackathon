"""P11 integration tests for findings, retries, and HTTP contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.detectors import create_splitting_router
from app.engines.splitting.partition import SplittingPolicy, TransferEvent
from app.engines.splitting.service import (
    ALGORITHM_VERSION,
    FINDING_TYPE,
    InMemorySplittingRunRepository,
    RunInputConflict,
    run_splitting_detector,
)


START = datetime(2024, 1, 1, tzinfo=UTC)


def event(transaction_id: str, amount: int, minute: int) -> TransferEvent:
    return TransferEvent(
        transaction_id=transaction_id,
        sender_account_id="SENDER-1",
        receiver_account_id=f"RECEIVER-{transaction_id}",
        amount_minor=amount,
        currency="INR",
        occurred_at=START + timedelta(minutes=minute),
        transaction_type="TRANSFER",
    )


def policy(version: int = 1) -> SplittingPolicy:
    return SplittingPolicy(
        version=version,
        window_minutes=60,
        amount_threshold_minor=10_000_000,
        min_count=3,
        individual_max_minor=9_999_999,
    )


def overlapping_events() -> list[TransferEvent]:
    return [
        event("T-1", 4_000_000, 0),
        event("T-2", 4_000_000, 10),
        event("T-3", 4_000_000, 20),
        event("T-4", 4_000_000, 30),
    ]


def test_overlapping_windows_become_one_complete_finding() -> None:
    repository = InMemorySplittingRunRepository()

    outcome = run_splitting_detector(
        overlapping_events(), policy(), "checkpoint-001", repository
    )

    assert outcome.replayed is False
    assert outcome.run.status == "COMPLETED"
    assert len(outcome.run.findings) == 1
    finding = outcome.run.findings[0]
    assert finding.draft.finding_type == FINDING_TYPE
    assert finding.draft.algorithm_version == ALGORITHM_VERSION
    assert finding.draft.transaction_ids == ("T-1", "T-2", "T-3", "T-4")
    assert finding.draft.facts == {
        "Splitting_Window_Sum_Minor": 16_000_000,
        "Splitting_Window_Count": 4,
        "Splitting_Window_Duration_Minutes": 30,
        "Splitting_Threshold_Minor": 10_000_000,
        "Transaction_Velocity": 4,
    }
    contributions = finding.draft.evidence["transactions"]
    assert isinstance(contributions, list)
    assert sum(item["amount_minor"] for item in contributions) == 16_000_000


def test_retry_is_idempotent_despite_order_and_exact_replay() -> None:
    repository = InMemorySplittingRunRepository()
    events = overlapping_events()
    first = run_splitting_detector(events, policy(), "checkpoint-002", repository)
    second = run_splitting_detector(
        [events[0], *reversed(events)], policy(), "checkpoint-002", repository
    )

    assert second.replayed is True
    assert second.run == first.run
    assert repository.run_count == 1
    assert repository.finding_count == 1


def test_same_checkpoint_with_changed_input_is_conflict() -> None:
    repository = InMemorySplittingRunRepository()
    run_splitting_detector(overlapping_events(), policy(), "checkpoint-003", repository)

    changed = [*overlapping_events(), event("T-5", 1_000_000, 35)]
    with pytest.raises(RunInputConflict, match="different input"):
        run_splitting_detector(changed, policy(), "checkpoint-003", repository)

    assert repository.run_count == 1
    assert repository.finding_count == 1


def test_policy_version_changes_run_and_finding_identity() -> None:
    repository = InMemorySplittingRunRepository()
    first = run_splitting_detector(
        overlapping_events(), policy(1), "checkpoint-versioned", repository
    )
    second = run_splitting_detector(
        overlapping_events(), policy(2), "checkpoint-versioned", repository
    )

    assert first.run.run_id != second.run.run_id
    assert (
        first.run.findings[0].draft.fingerprint
        != second.run.findings[0].draft.fingerprint
    )
    assert repository.run_count == 2
    assert repository.finding_count == 2


def test_completed_run_can_have_no_findings() -> None:
    repository = InMemorySplittingRunRepository()

    outcome = run_splitting_detector(
        overlapping_events()[:2], policy(), "checkpoint-empty", repository
    )

    assert outcome.run.status == "COMPLETED"
    assert outcome.run.findings == ()
    assert repository.run_count == 1


def test_http_run_and_findings_endpoints() -> None:
    repository = InMemorySplittingRunRepository()
    transactions = overlapping_events()
    app = FastAPI()
    app.include_router(
        create_splitting_router(
            repository=repository,
            load_policy=lambda version: policy(version),
            load_transfers=lambda start, end, checkpoint: [
                item for item in transactions if start <= item.occurred_at <= end
            ],
        ),
        prefix="/api/v1",
    )
    client = TestClient(app)
    payload = {
        "start_at": "2024-01-01T00:00:00Z",
        "end_at": "2024-01-02T00:00:00Z",
        "policy_version": 1,
        "snapshot_checkpoint": "api-checkpoint",
    }

    response = client.post(
        "/api/v1/detectors/splitting/runs",
        json=payload,
        headers={"X-Request-ID": "request-123"},
    )

    assert response.status_code == 202
    assert response.json()["request_id"] == "request-123"
    assert response.json()["data"]["finding_count"] == 1
    assert response.json()["data"]["replayed"] is False

    replay = client.post("/api/v1/detectors/splitting/runs", json=payload)
    assert replay.status_code == 202
    assert replay.json()["data"]["replayed"] is True

    findings = client.get(
        "/api/v1/findings",
        params={"finding_type": FINDING_TYPE, "limit": 10},
    )
    assert findings.status_code == 200
    assert findings.json()["meta"]["returned"] == 1
    assert findings.json()["data"][0]["type"] == FINDING_TYPE
    assert findings.json()["data"][0]["facts"]["Splitting_Window_Count"] == 4


def test_http_rejects_invalid_date_range() -> None:
    repository = InMemorySplittingRunRepository()
    app = FastAPI()
    app.include_router(
        create_splitting_router(
            repository=repository,
            load_policy=lambda version: policy(version),
            load_transfers=lambda start, end, checkpoint: [],
        ),
        prefix="/api/v1",
    )

    response = TestClient(app).post(
        "/api/v1/detectors/splitting/runs",
        json={
            "start_at": "2024-01-02T00:00:00Z",
            "end_at": "2024-01-01T00:00:00Z",
            "policy_version": 1,
            "snapshot_checkpoint": "invalid-range",
        },
    )

    assert response.status_code == 422
