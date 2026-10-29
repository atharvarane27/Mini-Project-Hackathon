"""P16 case lifecycle, transaction, lease, and API acceptance tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.cases import create_cases_router
from app.services.case_service import (
    AtomicCommitError,
    CaseConflictError,
    CaseService,
    CaseState,
    InMemoryCaseRepository,
    InvalidCaseTransitionError,
    OutboxState,
    stable_case_key,
)


NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def make_service(
    repository: InMemoryCaseRepository | None = None,
    now: datetime = NOW,
) -> tuple[InMemoryCaseRepository, CaseService]:
    saved = repository or InMemoryCaseRepository()
    return saved, CaseService(saved, clock=lambda: now)


def test_stable_case_creation_atomically_writes_case_outbox_and_audit() -> None:
    repository, service = make_service()

    created = service.create_from_findings(
        ["finding-b", "finding-a", "finding-a"],
        "rule-v3",
        85,
        "system",
    )
    replay = service.create_from_findings(
        ["finding-a", "finding-b"],
        "rule-v3",
        85,
        "system",
    )

    assert replay == created
    assert created.stable_key == stable_case_key(
        ["finding-a", "finding-b"], "rule-v3"
    )
    assert created.finding_ids == ("finding-a", "finding-b")
    assert created.state is CaseState.QUEUED
    assert len(repository.list_cases()) == 1
    assert len(repository.list_outbox_events()) == 1
    assert repository.list_outbox_events()[0].status is OutboxState.PENDING
    assert [intent.action for intent in repository.list_audit_intents()] == [
        "CASE_CREATED"
    ]


def test_failed_atomic_commit_exposes_no_partial_case_event_or_audit() -> None:
    repository, service = make_service()
    repository.inject_commit_failure_once()

    with pytest.raises(AtomicCommitError, match="simulated"):
        service.create_from_findings(["finding-1"], "rule-v1", 50, "system")

    assert repository.list_cases() == ()
    assert repository.list_outbox_events() == ()
    assert repository.list_audit_intents() == ()


def test_claim_transition_versions_and_invalid_transition_are_enforced() -> None:
    _, service = make_service()
    case = service.create_from_findings(["finding-1"], "rule-v1", 50, "system")

    claimed = service.claim_direct(
        case.case_id,
        case.row_version,
        "worker-1",
        timedelta(minutes=5),
    )
    assert claimed.state is CaseState.CLAIMED
    assert claimed.row_version == 2
    assert claimed.lease_until == NOW + timedelta(minutes=5)

    in_progress = service.transition(
        case.case_id, claimed.row_version, CaseState.IN_PROGRESS, "auditor-1"
    )
    resolved = service.transition(
        case.case_id, in_progress.row_version, CaseState.RESOLVED, "auditor-1"
    )
    closed = service.transition(
        case.case_id, resolved.row_version, CaseState.CLOSED, "reviewer-1"
    )
    assert closed.state is CaseState.CLOSED
    assert closed.assignee_id is None
    assert closed.lease_until is None

    with pytest.raises(CaseConflictError, match="version"):
        service.transition(
            case.case_id, claimed.row_version, CaseState.IN_PROGRESS, "auditor-1"
        )
    with pytest.raises(InvalidCaseTransitionError, match="cannot transition"):
        service.transition(
            case.case_id, closed.row_version, CaseState.IN_PROGRESS, "auditor-1"
        )


def test_expired_claim_is_requeued_with_new_version_and_outbox_event() -> None:
    repository, service = make_service()
    case = service.create_from_findings(["finding-1"], "rule-v1", 50, "system")
    claimed = service.claim_direct(
        case.case_id, 1, "worker-1", timedelta(seconds=10)
    )
    later = CaseService(repository, clock=lambda: NOW + timedelta(seconds=11))

    recovered = later.recover_expired_leases()

    assert len(recovered) == 1
    assert recovered[0].state is CaseState.QUEUED
    assert recovered[0].row_version == claimed.row_version + 1
    assert len(repository.list_outbox_events()) == 2
    assert repository.list_audit_intents()[-1].action == "CASE_LEASE_EXPIRED"


def test_case_api_lists_claims_and_transitions_with_conflict_responses() -> None:
    _, service = make_service()
    case = service.create_from_findings(["finding-api"], "rule-v1", 75, "system")
    app = FastAPI()
    app.include_router(create_cases_router(service), prefix="/api/v1")
    client = TestClient(app)

    listed = client.get(
        "/api/v1/cases", headers={"X-Request-ID": "case-list-request"}
    )
    assert listed.status_code == 200
    assert listed.json()["data"][0]["case_id"] == case.case_id
    assert listed.json()["request_id"] == "case-list-request"

    claim = client.post(
        f"/api/v1/cases/{case.case_id}/claim",
        json={"expected_version": 1, "worker_id": "api-worker", "lease_seconds": 60},
    )
    assert claim.status_code == 200
    assert claim.json()["data"]["state"] == "CLAIMED"

    duplicate = client.post(
        f"/api/v1/cases/{case.case_id}/claim",
        json={"expected_version": 1, "worker_id": "other-worker"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "CASE_CLAIM_CONFLICT"

    transitioned = client.post(
        f"/api/v1/cases/{case.case_id}/transition",
        json={"expected_version": 2, "new_state": "IN_PROGRESS"},
        headers={"X-Actor-ID": "auditor-api"},
    )
    assert transitioned.status_code == 200
    assert transitioned.json()["data"]["state"] == "IN_PROGRESS"

    stale = client.post(
        f"/api/v1/cases/{case.case_id}/transition",
        json={"expected_version": 2, "new_state": "RESOLVED"},
        headers={"X-Actor-ID": "auditor-api"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CASE_VERSION_CONFLICT"
