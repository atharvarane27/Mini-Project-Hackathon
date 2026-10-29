"""P14 rule lifecycle, evaluation persistence, and deterministic priority."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from threading import Lock
from typing import Protocol
from uuid import uuid4

from .ast_nodes import AstNode
from .evaluator import EvaluationResult, Evaluator, MissingMetricBehavior
from .lexer import tokenize
from .parser import parse_tokens
from .tokens import Token
from .types import DEFAULT_FIELD_TYPES, RuleValueType


class RuleStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RuleAuthorizationError(PermissionError):
    pass


class RuleNotFoundError(KeyError):
    pass


class RuleStateError(ValueError):
    pass


class RuleIdempotencyConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RuleActor:
    user_id: str
    roles: frozenset[str]

    def __post_init__(self) -> None:
        if not self.user_id.strip():
            raise ValueError("user_id must not be empty")
        object.__setattr__(self, "user_id", self.user_id.strip())
        object.__setattr__(
            self,
            "roles",
            frozenset(role.strip().upper() for role in self.roles if role.strip()),
        )


@dataclass(frozen=True, slots=True)
class CompiledRule:
    expression: str
    tokens: tuple[Token, ...]
    ast: AstNode


@dataclass(frozen=True, slots=True)
class RuleVersion:
    rule_id: str
    name: str
    version: int
    expression: str
    status: RuleStatus
    created_by: str
    created_at: datetime
    compiled_ast: AstNode
    activated_by: str | None = None
    activated_at: datetime | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "version": self.version,
            "expression": self.expression,
            "status": self.status.value,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "activated_by": self.activated_by,
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
        }


@dataclass(frozen=True, slots=True)
class PriorityPolicy:
    version: int = 1
    severe_reconciliation_points: int = 40
    circular_flow_points: int = 35
    splitting_pattern_points: int = 25
    maximum_aging_points: int = 20
    maximum_priority: int = 100

    def __post_init__(self) -> None:
        for name in (
            "version",
            "severe_reconciliation_points",
            "circular_flow_points",
            "splitting_pattern_points",
            "maximum_aging_points",
            "maximum_priority",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.version <= 0 or self.maximum_priority <= 0:
            raise ValueError("version and maximum_priority must be positive")


@dataclass(frozen=True, slots=True)
class PriorityInputs:
    severe_reconciliation_mismatch: bool = False
    circular_flow: bool = False
    splitting_pattern: bool = False
    aging_points: int = 0

    def __post_init__(self) -> None:
        for name in (
            "severe_reconciliation_mismatch",
            "circular_flow",
            "splitting_pattern",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be bool")
        if isinstance(self.aging_points, bool) or not isinstance(self.aging_points, int):
            raise TypeError("aging_points must be an integer")
        if self.aging_points < 0:
            raise ValueError("aging_points must not be negative")

    @classmethod
    def from_facts(
        cls, facts: Mapping[str, object], aging_points: int = 0
    ) -> PriorityInputs:
        balance_anomaly = facts.get("Balance_Anomaly_Flag", False)
        circular = facts.get("Circular_Flow_Detected", False)
        if not isinstance(balance_anomaly, bool) or not isinstance(circular, bool):
            raise TypeError("priority Boolean facts must contain bool values")

        variance = facts.get("Reconciliation_Variance_Minor", 0)
        allowed = facts.get("Allowed_Variance_Minor", 0)
        if (
            isinstance(variance, bool)
            or not isinstance(variance, (int, Decimal))
            or isinstance(allowed, bool)
            or not isinstance(allowed, (int, Decimal))
        ):
            raise TypeError("reconciliation variance priority facts must be numeric")

        split_count = facts.get("Splitting_Window_Count", 0)
        split_sum = facts.get("Splitting_Window_Sum_Minor", 0)
        if (
            isinstance(split_count, bool)
            or not isinstance(split_count, (int, Decimal))
            or isinstance(split_sum, bool)
            or not isinstance(split_sum, (int, Decimal))
        ):
            raise TypeError("splitting priority facts must be numeric")

        return cls(
            severe_reconciliation_mismatch=balance_anomaly or variance > allowed,
            circular_flow=circular,
            splitting_pattern=split_count >= 3 and split_sum > 0,
            aging_points=aging_points,
        )


def calculate_priority(inputs: PriorityInputs, policy: PriorityPolicy) -> int:
    value = (
        policy.severe_reconciliation_points
        * int(inputs.severe_reconciliation_mismatch)
        + policy.circular_flow_points * int(inputs.circular_flow)
        + policy.splitting_pattern_points * int(inputs.splitting_pattern)
        + min(policy.maximum_aging_points, inputs.aging_points)
    )
    return min(policy.maximum_priority, value)


@dataclass(frozen=True, slots=True)
class RuleEvaluationRecord:
    evaluation_id: str
    rule_version_id: str
    matched: bool
    result: bool | str
    facts_snapshot: Mapping[str, object]
    matched_facts: Mapping[str, object]
    explanation_tree: Mapping[str, object]
    priority: int
    priority_policy_version: int
    evaluated_at: datetime


class RuleRepository(Protocol):
    def create_draft(
        self,
        *,
        name: str,
        expression: str,
        compiled_ast: AstNode,
        actor_id: str,
        created_at: datetime,
        idempotency_key: str | None,
    ) -> RuleVersion: ...

    def get(self, rule_id: str) -> RuleVersion: ...

    def activate(
        self,
        *,
        rule_id: str,
        compiled_ast: AstNode,
        actor_id: str,
        activated_at: datetime,
    ) -> RuleVersion: ...

    def save_evaluation(
        self, record: RuleEvaluationRecord
    ) -> RuleEvaluationRecord: ...

    def list_evaluations(self) -> tuple[RuleEvaluationRecord, ...]: ...


def _payload_digest(name: str, expression: str) -> str:
    payload = json.dumps(
        {"name": name, "expression": expression},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class InMemoryRuleRepository:
    """Thread-safe adapter that models required database transactions."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._rules: dict[str, RuleVersion] = {}
        self._rule_ids_by_name: dict[str, list[str]] = {}
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._evaluations: list[RuleEvaluationRecord] = []

    def create_draft(
        self,
        *,
        name: str,
        expression: str,
        compiled_ast: AstNode,
        actor_id: str,
        created_at: datetime,
        idempotency_key: str | None,
    ) -> RuleVersion:
        digest = _payload_digest(name, expression)
        with self._lock:
            if idempotency_key is not None and idempotency_key in self._idempotency:
                saved_digest, rule_id = self._idempotency[idempotency_key]
                if saved_digest != digest:
                    raise RuleIdempotencyConflict(
                        "idempotency key was already used for a different rule payload"
                    )
                return self._rules[rule_id]

            version = len(self._rule_ids_by_name.get(name, [])) + 1
            rule = RuleVersion(
                rule_id=str(uuid4()),
                name=name,
                version=version,
                expression=expression,
                status=RuleStatus.DRAFT,
                created_by=actor_id,
                created_at=created_at,
                compiled_ast=compiled_ast,
            )
            self._rules[rule.rule_id] = rule
            self._rule_ids_by_name.setdefault(name, []).append(rule.rule_id)
            if idempotency_key is not None:
                self._idempotency[idempotency_key] = (digest, rule.rule_id)
            return rule

    def get(self, rule_id: str) -> RuleVersion:
        with self._lock:
            try:
                return self._rules[rule_id]
            except KeyError as error:
                raise RuleNotFoundError(f"rule {rule_id!r} was not found") from error

    def activate(
        self,
        *,
        rule_id: str,
        compiled_ast: AstNode,
        actor_id: str,
        activated_at: datetime,
    ) -> RuleVersion:
        with self._lock:
            try:
                current = self._rules[rule_id]
            except KeyError as error:
                raise RuleNotFoundError(f"rule {rule_id!r} was not found") from error
            if current.status is not RuleStatus.DRAFT:
                raise RuleStateError("only a DRAFT rule version can be activated")

            for other_id in self._rule_ids_by_name[current.name]:
                other = self._rules[other_id]
                if other.status is RuleStatus.ACTIVE:
                    self._rules[other_id] = replace(other, status=RuleStatus.RETIRED)

            activated = replace(
                current,
                status=RuleStatus.ACTIVE,
                compiled_ast=compiled_ast,
                activated_by=actor_id,
                activated_at=activated_at,
            )
            self._rules[rule_id] = activated
            return activated

    def save_evaluation(
        self, record: RuleEvaluationRecord
    ) -> RuleEvaluationRecord:
        with self._lock:
            self._evaluations.append(record)
            return record

    def list_evaluations(self) -> tuple[RuleEvaluationRecord, ...]:
        with self._lock:
            return tuple(self._evaluations)


class RuleService:
    def __init__(
        self,
        repository: RuleRepository,
        *,
        field_types: Mapping[str, RuleValueType] | None = None,
        missing_metric_behavior: MissingMetricBehavior = MissingMetricBehavior.ERROR,
        priority_policy: PriorityPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.field_types = dict(
            DEFAULT_FIELD_TYPES if field_types is None else field_types
        )
        self.evaluator = Evaluator(missing_metric_behavior)
        self.priority_policy = priority_policy or PriorityPolicy()
        self.clock = clock or (lambda: datetime.now(UTC))

    def _authorize_admin(self, actor: RuleActor) -> None:
        if "ADMIN" not in actor.roles:
            raise RuleAuthorizationError("ADMIN role is required")

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("rule service clock must return a timezone-aware value")
        return value.astimezone(UTC)

    def compile(self, expression: str) -> CompiledRule:
        tokens = tokenize(expression)
        ast = parse_tokens(tokens, self.field_types)
        return CompiledRule(expression, tokens, ast)

    def create_draft(
        self,
        name: str,
        expression: str,
        actor: RuleActor,
        idempotency_key: str | None = None,
    ) -> RuleVersion:
        self._authorize_admin(actor)
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("rule name must not be empty")
        normalized_key = idempotency_key.strip() if idempotency_key else None
        if idempotency_key is not None and not normalized_key:
            raise ValueError("idempotency key must not be blank")
        compiled = self.compile(expression)
        return self.repository.create_draft(
            name=normalized_name,
            expression=expression,
            compiled_ast=compiled.ast,
            actor_id=actor.user_id,
            created_at=self._now(),
            idempotency_key=normalized_key,
        )

    def activate(self, rule_id: str, actor: RuleActor) -> RuleVersion:
        self._authorize_admin(actor)
        current = self.repository.get(rule_id)
        compiled = self.compile(current.expression)
        return self.repository.activate(
            rule_id=rule_id,
            compiled_ast=compiled.ast,
            actor_id=actor.user_id,
            activated_at=self._now(),
        )

    def evaluate(
        self,
        rule_id: str,
        facts: Mapping[str, object],
        *,
        aging_points: int = 0,
    ) -> RuleEvaluationRecord:
        rule = self.repository.get(rule_id)
        if rule.status is not RuleStatus.ACTIVE:
            raise RuleStateError("only an ACTIVE rule version can be evaluated")
        evaluation: EvaluationResult = self.evaluator.evaluate(
            rule.compiled_ast, facts
        )
        priority_inputs = PriorityInputs.from_facts(facts, aging_points)
        priority = (
            calculate_priority(priority_inputs, self.priority_policy)
            if evaluation.matched
            else 0
        )
        record = RuleEvaluationRecord(
            evaluation_id=str(uuid4()),
            rule_version_id=rule.rule_id,
            matched=evaluation.matched,
            result=evaluation.result,
            facts_snapshot=dict(evaluation.facts_snapshot),
            matched_facts=dict(evaluation.facts_snapshot) if evaluation.matched else {},
            explanation_tree=dict(evaluation.explanation_tree),
            priority=priority,
            priority_policy_version=self.priority_policy.version,
            evaluated_at=self._now(),
        )
        return self.repository.save_evaluation(record)
