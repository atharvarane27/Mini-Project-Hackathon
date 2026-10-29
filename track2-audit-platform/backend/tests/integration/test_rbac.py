"""P18 authentication, RBAC, and workflow conflict tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.auth import create_auth_router
from app.core.auth import (
    AuthenticationError,
    AuthService,
    UserIdentity,
    hash_password,
)
from app.core.rbac import AuthorizationError, Permission, Role, authorize
from app.engines.workflow.dag import TaskNode
from app.engines.workflow.service import (
    InMemoryWorkflowRepository,
    WorkflowConflictError,
    WorkflowService,
)


NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def test_password_session_login_logout_and_expiry() -> None:
    clock = [NOW]
    auth = AuthService(
        (UserIdentity("u1", "auditor", hash_password("safe-password"), frozenset({Role.AUDITOR})),),
        clock=lambda: clock[0],
        session_ttl=timedelta(minutes=5),
    )
    session = auth.login("AUDITOR", "safe-password")
    assert auth.authenticate(session.token).user_id == "u1"
    with pytest.raises(AuthenticationError):
        auth.login("auditor", "wrong-password")
    clock[0] += timedelta(minutes=6)
    with pytest.raises(AuthenticationError, match="expired"):
        auth.authenticate(session.token)


def test_role_permissions_and_maker_checker_are_enforced() -> None:
    authorize(frozenset({Role.AUDITOR}), Permission.CASE_CLAIM, actor_id="u1")
    with pytest.raises(AuthorizationError, match="WORKFLOW_MANAGE"):
        authorize(frozenset({Role.VIEWER}), Permission.WORKFLOW_MANAGE, actor_id="u1")
    with pytest.raises(AuthorizationError, match="own"):
        authorize(
            frozenset({Role.REVIEWER}), Permission.CASE_TRANSITION,
            actor_id="maker", object_owner_id="maker", require_different_actor=True,
        )


def test_auth_api_returns_401_and_invalidates_logout_token() -> None:
    auth = AuthService(
        (UserIdentity("u1", "admin", hash_password("admin-password"), frozenset({Role.ADMIN})),),
        clock=lambda: NOW,
    )
    app = FastAPI()
    app.include_router(create_auth_router(auth), prefix="/api/v1")
    client = TestClient(app)
    denied = client.post("/api/v1/auth/login", json={"username": "admin", "password": "bad"})
    assert denied.status_code == 401
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-password"})
    token = login.json()["data"]["access_token"]
    assert client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}).status_code == 204
    with pytest.raises(AuthenticationError):
        auth.authenticate(token)


def test_concurrent_workflow_updates_with_same_version_have_one_winner() -> None:
    service = WorkflowService(InMemoryWorkflowRepository())
    nodes = (TaskNode("a", "A"), TaskNode("b", "B"))
    template = service.create_template("conflict", nodes, (), activate=True)
    service.start("case-1", template.template_id)

    def complete(task_id: str) -> str:
        try:
            service.complete_task("case-1", task_id, expected_instance_version=1)
            return "OK"
        except WorkflowConflictError:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(complete, ("a", "b")))
    assert sorted(results) == ["CONFLICT", "OK"]
