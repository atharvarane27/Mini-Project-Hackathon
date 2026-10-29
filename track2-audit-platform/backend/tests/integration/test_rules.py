"""P14 evaluator, rule lifecycle, priority, and API integration tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.rules import create_rules_router
from app.engines.rules.evaluator import (
    EvaluationTypeError,
    MissingMetricBehavior,
    MissingMetricError,
    evaluate_ast,
)
from app.engines.rules.lexer import tokenize
from app.engines.rules.parser import parse_tokens
from app.engines.rules.service import (
    InMemoryRuleRepository,
    PriorityInputs,
    PriorityPolicy,
    RuleActor,
    RuleAuthorizationError,
    RuleIdempotencyConflict,
    RuleService,
    RuleStateError,
    RuleStatus,
    calculate_priority,
)
from app.engines.rules.types import RuleValueType


NOW = datetime(2024, 2, 1, 12, 0, tzinfo=UTC)
FIELDS = {
    "Amount": RuleValueType.NUMBER,
    "Flag": RuleValueType.BOOLEAN,
    "Missing": RuleValueType.BOOLEAN,
    "Reconciliation_Variance_Minor": RuleValueType.NUMBER,
    "Allowed_Variance_Minor": RuleValueType.NUMBER,
    "Balance_Anomaly_Flag": RuleValueType.BOOLEAN,
    "Circular_Flow_Detected": RuleValueType.BOOLEAN,
    "Cycle_Length": RuleValueType.NUMBER,
    "Splitting_Window_Sum_Minor": RuleValueType.NUMBER,
    "Splitting_Window_Count": RuleValueType.NUMBER,
}
ADMIN = RuleActor("admin-1", frozenset({"ADMIN"}))
AUDITOR = RuleActor("auditor-1", frozenset({"AUDITOR"}))


def ast(expression: str):
    return parse_tokens(tokenize(expression), FIELDS)


def service(
    repository: InMemoryRuleRepository | None = None,
    *,
    missing: MissingMetricBehavior = MissingMetricBehavior.ERROR,
) -> RuleService:
    return RuleService(
        repository or InMemoryRuleRepository(),
        field_types=FIELDS,
        missing_metric_behavior=missing,
        clock=lambda: NOW,
    )


def test_pure_evaluator_returns_deterministic_explanation() -> None:
    rule_ast = ast("Flag AND Amount >= 10.50")

    result = evaluate_ast(rule_ast, {"Flag": True, "Amount": Decimal("10.50")})

    assert result.matched is True
    assert result.result is True
    assert result.facts_snapshot == {"Amount": "10.50", "Flag": True}
    assert result.explanation_tree["node"] == "AND"
    assert result.explanation_tree["result"] is True


def test_boolean_short_circuit_skips_irrelevant_missing_metric() -> None:
    result = evaluate_ast(ast("Flag OR Missing"), {"Flag": True})

    assert result.matched is True
    assert result.explanation_tree["right"]["node"] == "SKIPPED"  # type: ignore[index]


def test_missing_metric_behavior_is_explicit() -> None:
    rule_ast = ast("Flag OR Missing")

    with pytest.raises(MissingMetricError, match="Missing"):
        evaluate_ast(rule_ast, {"Flag": False})

    result = evaluate_ast(
        rule_ast,
        {"Flag": False},
        MissingMetricBehavior.NO_MATCH,
    )
    assert result.matched is False
    assert result.result == "MISSING"
    assert result.facts_snapshot == {"Flag": False, "Missing": None}


def test_runtime_context_rejects_float_and_wrong_boolean_types() -> None:
    with pytest.raises(EvaluationTypeError, match="NUMBER"):
        evaluate_ast(ast("Amount > 10"), {"Amount": 10.5})
    with pytest.raises(EvaluationTypeError, match="BOOLEAN"):
        evaluate_ast(ast("Flag"), {"Flag": 1})


def test_same_ast_engine_evaluates_all_three_detector_families() -> None:
    expression = (
        "(Reconciliation_Variance_Minor > Allowed_Variance_Minor AND "
        "Balance_Anomaly_Flag == TRUE) OR "
        "(Circular_Flow_Detected == TRUE AND Cycle_Length >= 3) OR "
        "(Splitting_Window_Sum_Minor >= 10000000 AND "
        "Splitting_Window_Count >= 3)"
    )
    rule_ast = ast(expression)
    contexts = [
        {
            "Reconciliation_Variance_Minor": 60_000,
            "Allowed_Variance_Minor": 50_000,
            "Balance_Anomaly_Flag": True,
        },
        {
            "Reconciliation_Variance_Minor": 0,
            "Allowed_Variance_Minor": 50_000,
            "Balance_Anomaly_Flag": False,
            "Circular_Flow_Detected": True,
            "Cycle_Length": 3,
        },
        {
            "Reconciliation_Variance_Minor": 0,
            "Allowed_Variance_Minor": 50_000,
            "Balance_Anomaly_Flag": False,
            "Circular_Flow_Detected": False,
            "Cycle_Length": 0,
            "Splitting_Window_Sum_Minor": 10_500_000,
            "Splitting_Window_Count": 3,
        },
    ]

    assert all(evaluate_ast(rule_ast, context).matched for context in contexts)


def test_priority_is_configurable_bounded_and_deterministic() -> None:
    inputs = PriorityInputs(True, True, True, aging_points=50)

    assert calculate_priority(inputs, PriorityPolicy()) == 100
    custom = PriorityPolicy(
        version=2,
        severe_reconciliation_points=10,
        circular_flow_points=20,
        splitting_pattern_points=30,
        maximum_aging_points=5,
        maximum_priority=80,
    )
    assert calculate_priority(inputs, custom) == 65


def test_priority_inputs_are_derived_from_detector_facts() -> None:
    facts = {
        "Reconciliation_Variance_Minor": 60_000,
        "Allowed_Variance_Minor": 50_000,
        "Balance_Anomaly_Flag": False,
        "Circular_Flow_Detected": True,
        "Splitting_Window_Sum_Minor": 10_500_000,
        "Splitting_Window_Count": 3,
    }

    inputs = PriorityInputs.from_facts(facts, aging_points=4)

    assert inputs == PriorityInputs(True, True, True, 4)


def test_admin_can_create_activate_and_evaluate_versioned_rule() -> None:
    repository = InMemoryRuleRepository()
    rules = service(repository)
    draft = rules.create_draft("amount-review", "Amount >= 100", ADMIN)

    assert draft.status is RuleStatus.DRAFT
    assert draft.version == 1
    active = rules.activate(draft.rule_id, ADMIN)
    evaluation = rules.evaluate(active.rule_id, {"Amount": 150})

    assert active.status is RuleStatus.ACTIVE
    assert active.activated_at == NOW
    assert evaluation.matched is True
    assert evaluation.rule_version_id == active.rule_id
    assert evaluation.facts_snapshot == {"Amount": 150}
    assert evaluation.matched_facts == {"Amount": 150}
    assert repository.list_evaluations() == (evaluation,)


def test_rule_change_requires_no_code_change_and_old_evidence_keeps_version() -> None:
    repository = InMemoryRuleRepository()
    rules = service(repository)
    first = rules.activate(
        rules.create_draft("threshold", "Amount >= 100", ADMIN).rule_id,
        ADMIN,
    )
    first_evaluation = rules.evaluate(first.rule_id, {"Amount": 150})

    second_draft = rules.create_draft("threshold", "Amount >= 200", ADMIN)
    second = rules.activate(second_draft.rule_id, ADMIN)
    second_evaluation = rules.evaluate(second.rule_id, {"Amount": 150})

    assert second.version == 2
    assert repository.get(first.rule_id).status is RuleStatus.RETIRED
    assert first_evaluation.matched is True
    assert first_evaluation.rule_version_id == first.rule_id
    assert second_evaluation.matched is False
    assert second_evaluation.rule_version_id == second.rule_id
    with pytest.raises(RuleStateError, match="ACTIVE"):
        rules.evaluate(first.rule_id, {"Amount": 150})


def test_non_admin_cannot_create_or_activate_rules() -> None:
    rules = service()

    with pytest.raises(RuleAuthorizationError, match="ADMIN"):
        rules.create_draft("denied", "Flag", AUDITOR)
    draft = rules.create_draft("allowed", "Flag", ADMIN)
    with pytest.raises(RuleAuthorizationError, match="ADMIN"):
        rules.activate(draft.rule_id, AUDITOR)


def test_activated_rule_is_immutable_and_cannot_be_reactivated() -> None:
    rules = service()
    active = rules.activate(
        rules.create_draft("immutable", "Flag", ADMIN).rule_id,
        ADMIN,
    )

    with pytest.raises(FrozenInstanceError):
        active.expression = "NOT Flag"  # type: ignore[misc]
    with pytest.raises(RuleStateError, match="DRAFT"):
        rules.activate(active.rule_id, ADMIN)


def test_draft_creation_is_idempotent_and_detects_payload_conflict() -> None:
    rules = service()
    first = rules.create_draft(
        "idempotent", "Flag", ADMIN, idempotency_key="rule-key-1"
    )
    replay = rules.create_draft(
        "idempotent", "Flag", ADMIN, idempotency_key="rule-key-1"
    )

    assert replay == first
    with pytest.raises(RuleIdempotencyConflict, match="different"):
        rules.create_draft(
            "idempotent", "NOT Flag", ADMIN, idempotency_key="rule-key-1"
        )


def test_unmatched_evaluation_persists_snapshot_but_no_matched_facts() -> None:
    repository = InMemoryRuleRepository()
    rules = service(repository)
    active = rules.activate(
        rules.create_draft("not-matched", "Amount > 100", ADMIN).rule_id,
        ADMIN,
    )

    evaluation = rules.evaluate(active.rule_id, {"Amount": 10})

    assert evaluation.matched is False
    assert evaluation.priority == 0
    assert evaluation.facts_snapshot == {"Amount": 10}
    assert evaluation.matched_facts == {}


def test_rule_lifecycle_api_enforces_role_and_exposes_versions() -> None:
    repository = InMemoryRuleRepository()
    rules = service(repository)
    app = FastAPI()
    app.include_router(create_rules_router(FIELDS, rules), prefix="/api/v1")
    client = TestClient(app)
    admin_headers = {
        "X-Actor-ID": "admin-api",
        "X-Roles": "ADMIN",
        "Idempotency-Key": "api-rule-key",
        "X-Request-ID": "api-request-1",
    }

    created = client.post(
        "/api/v1/rules",
        json={"name": "api-rule", "expression": "Amount >= 100"},
        headers=admin_headers,
    )
    assert created.status_code == 201
    assert created.json()["data"]["status"] == "DRAFT"
    assert created.json()["data"]["version"] == 1
    assert created.json()["request_id"] == "api-request-1"

    rule_id = created.json()["data"]["rule_id"]
    activated = client.post(
        f"/api/v1/rules/{rule_id}/activate",
        headers={"X-Actor-ID": "admin-api", "X-Roles": "ADMIN"},
    )
    assert activated.status_code == 200
    assert activated.json()["data"]["status"] == "ACTIVE"

    denied = client.post(
        "/api/v1/rules",
        json={"name": "denied", "expression": "Flag"},
        headers={"X-Actor-ID": "viewer", "X-Roles": "VIEWER"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN"


def test_rule_api_returns_validation_and_state_errors() -> None:
    rules = service()
    app = FastAPI()
    app.include_router(create_rules_router(FIELDS, rules), prefix="/api/v1")
    client = TestClient(app)
    headers = {"X-Actor-ID": "admin", "X-Roles": "ADMIN"}

    invalid = client.post(
        "/api/v1/rules",
        json={"name": "invalid", "expression": "Amount AND Flag"},
        headers=headers,
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "TYPE_MISMATCH"

    missing = client.post("/api/v1/rules/not-found/activate", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RULE_NOT_FOUND"
