"""P18 immutable activity ledger and authorization tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.activity import create_activity_router
from app.core.audit_writer import ActivityLedger, ActivityMutationError
from app.core.auth import AuthService, UserIdentity, hash_password
from app.core.rbac import Role


NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def append(ledger: ActivityLedger, index: int = 1) -> None:
    ledger.append(
        actor_id="auditor-1", action="CASE_TRANSITIONED", object_id="case-1",
        object_version=index, occurred_at=NOW, request_id=f"request-{index}",
        old_values={"state": "QUEUED"}, new_values={"state": "CLAIMED"},
    )


def test_activity_ledger_is_append_only_and_hash_chain_verifies() -> None:
    ledger = ActivityLedger()
    append(ledger)
    append(ledger, 2)
    assert ledger.verify()
    assert ledger.list()[1].previous_hash == ledger.list()[0].entry_hash
    with pytest.raises(ActivityMutationError):
        ledger.update("anything")
    with pytest.raises(ActivityMutationError):
        ledger.delete("anything")


def test_concurrent_appends_preserve_complete_valid_chain() -> None:
    ledger = ActivityLedger()
    with ThreadPoolExecutor(max_workers=25) as executor:
        list(executor.map(lambda index: append(ledger, index), range(1, 101)))
    assert len(ledger.list()) == 100
    assert ledger.verify()


def test_activity_api_returns_401_403_and_authorized_entries() -> None:
    ledger = ActivityLedger()
    append(ledger)
    auth = AuthService(
        (
            UserIdentity("viewer", "viewer", hash_password("viewer-password"), frozenset({Role.VIEWER})),
            UserIdentity("none", "none", hash_password("no-role-password"), frozenset()),
        ),
        clock=lambda: NOW,
    )
    app = FastAPI()
    app.include_router(create_activity_router(auth, ledger), prefix="/api/v1")
    client = TestClient(app)
    assert client.get("/api/v1/activity").status_code == 401
    forbidden = auth.login("none", "no-role-password")
    assert client.get("/api/v1/activity", headers={"Authorization": f"Bearer {forbidden.token}"}).status_code == 403
    allowed = auth.login("viewer", "viewer-password")
    response = client.get("/api/v1/activity", headers={"Authorization": f"Bearer {allowed.token}"})
    assert response.status_code == 200
    assert response.json()["data"][0]["action"] == "CASE_TRANSITIONED"
