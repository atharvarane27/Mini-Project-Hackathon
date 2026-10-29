"""P09 temporal circular-flow finding and run acceptance tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.detectors import create_circular_router
from app.engines.circular.service import (
    ALGORITHM_VERSION,
    FINDING_TYPE,
    CircularRunInputConflict,
    InMemoryCircularRunRepository,
    run_circular_detector,
)
from app.engines.circular.temporal_validator import (
    CircularPolicy,
    CircularTransfer,
    CycleCandidate,
    validate_cycle,
)


START = datetime(2026, 1, 1, tzinfo=UTC)


def transfer(
    transaction_id: str,
    sender: str,
    receiver: str,
    amount: int,
    minute: int,
    currency: str = "INR",
) -> CircularTransfer:
    return CircularTransfer(
        transaction_id,
        sender,
        receiver,
        amount,
        currency,
        START + timedelta(minutes=minute),
    )


def valid_candidate() -> CycleCandidate:
    return CycleCandidate(
        ("A", "B", "C", "A"),
        (
            transfer("T1", "A", "B", 1_000_000, 0),
            transfer("T2", "B", "C", 950_000, 5),
            transfer("T3", "C", "A", 920_000, 10),
        ),
    )


def policy(version: int = 1, **changes: int) -> CircularPolicy:
    return CircularPolicy(version=version, **changes)


def test_valid_chronological_cycle_creates_one_reproducible_finding() -> None:
    repository = InMemoryCircularRunRepository()
    outcome = run_circular_detector(
        [valid_candidate()], policy(), "snapshot-1", repository
    )

    assert len(outcome.run.findings) == 1
    finding = outcome.run.findings[0]
    assert finding.draft.finding_type == FINDING_TYPE
    assert finding.draft.algorithm_version == ALGORITHM_VERSION
    assert finding.draft.transaction_ids == ("T1", "T2", "T3")
    assert finding.draft.facts["Circular_Flow_Detected"] is True
    assert finding.draft.facts["Cycle_Length"] == 3
    assert finding.draft.evidence["account_path"] == ["A", "B", "C", "A"]
    assert finding.draft.evidence["ordered_transaction_ids"] == ["T1", "T2", "T3"]
    assert finding.draft.evidence["policy"]["version"] == 1  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        finding.draft.algorithm_version = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("invalid,configured_policy", [
    (
        CycleCandidate(
            valid_candidate().account_path,
            (
                valid_candidate().transfers[0],
                replace(valid_candidate().transfers[1], occurred_at=START),
                valid_candidate().transfers[2],
            ),
        ),
        policy(),
    ),
    (valid_candidate(), policy(window_minutes=5)),
    (
        CycleCandidate(
            valid_candidate().account_path,
            (
                valid_candidate().transfers[0],
                replace(valid_candidate().transfers[1], currency="USD"),
                valid_candidate().transfers[2],
            ),
        ),
        policy(),
    ),
    (
        CycleCandidate(
            valid_candidate().account_path,
            (*valid_candidate().transfers[:2], replace(valid_candidate().transfers[2], amount_minor=700_000)),
        ),
        policy(),
    ),
    (valid_candidate(), policy(min_initial_amount_minor=2_000_000)),
])
def test_invalid_temporal_or_monetary_cycles_are_rejected(
    invalid: CycleCandidate, configured_policy: CircularPolicy
) -> None:
    assert validate_cycle(invalid, configured_policy) is None
    repository = InMemoryCircularRunRepository()
    outcome = run_circular_detector(
        [invalid], configured_policy, "invalid-snapshot", repository
    )
    assert outcome.run.findings == ()


def test_retry_and_duplicate_candidate_are_logically_idempotent() -> None:
    repository = InMemoryCircularRunRepository()
    candidate = valid_candidate()
    first = run_circular_detector([candidate], policy(), "snapshot-retry", repository)
    replay = run_circular_detector(
        [candidate, candidate], policy(), "snapshot-retry", repository
    )
    assert replay.replayed is True
    assert replay.run == first.run
    assert repository.run_count == repository.finding_count == 1


def test_changed_input_at_same_checkpoint_is_conflict() -> None:
    repository = InMemoryCircularRunRepository()
    run_circular_detector([valid_candidate()], policy(), "snapshot-conflict", repository)
    changed = replace(
        valid_candidate(),
        transfers=(
            *valid_candidate().transfers[:2],
            replace(valid_candidate().transfers[2], amount_minor=910_000),
        ),
    )
    with pytest.raises(CircularRunInputConflict, match="different"):
        run_circular_detector([changed], policy(), "snapshot-conflict", repository)


def test_circular_run_and_filtered_findings_api() -> None:
    repository = InMemoryCircularRunRepository()
    app = FastAPI()
    app.include_router(
        create_circular_router(
            repository=repository,
            load_policy=lambda version: policy(version),
            load_candidates=lambda start, end, checkpoint: [valid_candidate()],
        ),
        prefix="/api/v1",
    )
    client = TestClient(app)
    payload = {
        "start_at": "2026-01-01T00:00:00Z",
        "end_at": "2026-01-02T00:00:00Z",
        "policy_version": 1,
        "snapshot_checkpoint": "api-snapshot",
    }
    response = client.post("/api/v1/detectors/circular/runs", json=payload)
    assert response.status_code == 202
    assert response.json()["data"]["finding_count"] == 1
    replay = client.post("/api/v1/detectors/circular/runs", json=payload)
    assert replay.json()["data"]["replayed"] is True
    findings = client.get("/api/v1/findings", params={"finding_type": FINDING_TYPE})
    assert findings.status_code == 200
    assert findings.json()["data"][0]["type"] == FINDING_TYPE
