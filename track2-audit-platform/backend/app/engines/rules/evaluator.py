"""Pure, deterministic evaluator for typed audit-rule ASTs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Mapping, cast

from .ast_nodes import (
    AstNode,
    ComparisonNode,
    ComparisonOperator,
    IdentifierNode,
    LiteralNode,
    LogicalNode,
    LogicalOperator,
    NotNode,
    ast_to_dict,
)
from .types import RuleScalar, RuleValueType


class MissingMetricBehavior(StrEnum):
    ERROR = "ERROR"
    NO_MATCH = "NO_MATCH"


class MissingMetricError(KeyError):
    pass


class EvaluationTypeError(TypeError):
    pass


class _Missing:
    pass


MISSING = _Missing()
EvaluatedValue = RuleScalar | _Missing


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    matched: bool
    result: bool | str
    facts_snapshot: Mapping[str, object]
    explanation_tree: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _NodeResult:
    value: EvaluatedValue
    explanation: dict[str, object]


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    return value


def _result_value(value: EvaluatedValue) -> object:
    return "MISSING" if value is MISSING else _json_value(value)


def _identifier_names(root: AstNode) -> tuple[str, ...]:
    names: set[str] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, IdentifierNode):
            names.add(node.name)
        elif isinstance(node, NotNode):
            stack.append(node.operand)
        elif isinstance(node, (ComparisonNode, LogicalNode)):
            stack.extend((node.left, node.right))
    return tuple(sorted(names))


def _validate_value(name: str, value: object, expected: RuleValueType) -> RuleScalar:
    if expected is RuleValueType.BOOLEAN:
        if not isinstance(value, bool):
            raise EvaluationTypeError(
                f"metric {name!r} requires BOOLEAN, got {type(value).__name__}"
            )
        return value
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise EvaluationTypeError(
            f"metric {name!r} requires NUMBER (int or Decimal), "
            f"got {type(value).__name__}"
        )
    return value


def _compare(
    operator: ComparisonOperator, left: RuleScalar, right: RuleScalar
) -> bool:
    if operator is ComparisonOperator.EQUAL:
        return left == right
    if operator is ComparisonOperator.NOT_EQUAL:
        return left != right
    if operator is ComparisonOperator.GREATER:
        return left > right
    if operator is ComparisonOperator.GREATER_EQUAL:
        return left >= right
    if operator is ComparisonOperator.LESS:
        return left < right
    return left <= right


class Evaluator:
    def __init__(
        self,
        missing_metric_behavior: MissingMetricBehavior = MissingMetricBehavior.ERROR,
    ) -> None:
        self.missing_metric_behavior = MissingMetricBehavior(missing_metric_behavior)

    def evaluate(
        self, root: AstNode, context: Mapping[str, object]
    ) -> EvaluationResult:
        evaluated = self._evaluate_node(root, context)
        if evaluated.value is not MISSING and not isinstance(evaluated.value, bool):
            raise EvaluationTypeError("complete rule did not evaluate to BOOLEAN")
        matched = evaluated.value is True
        facts_snapshot = {
            name: _json_value(context[name]) if name in context else None
            for name in _identifier_names(root)
        }
        return EvaluationResult(
            matched=matched,
            result="MISSING" if evaluated.value is MISSING else matched,
            facts_snapshot=facts_snapshot,
            explanation_tree=evaluated.explanation,
        )

    def _evaluate_node(
        self, node: AstNode, context: Mapping[str, object]
    ) -> _NodeResult:
        if isinstance(node, LiteralNode):
            return _NodeResult(
                node.value,
                {
                    "node": "LITERAL",
                    "value_type": node.value_type.value,
                    "value": _json_value(node.value),
                    "result": _json_value(node.value),
                },
            )

        if isinstance(node, IdentifierNode):
            if node.name not in context or context[node.name] is None:
                if self.missing_metric_behavior is MissingMetricBehavior.ERROR:
                    raise MissingMetricError(f"required metric {node.name!r} is missing")
                return _NodeResult(
                    MISSING,
                    {
                        "node": "IDENTIFIER",
                        "name": node.name,
                        "value_type": node.value_type.value,
                        "result": "MISSING",
                    },
                )
            identifier_value = _validate_value(
                node.name, context[node.name], node.value_type
            )
            return _NodeResult(
                identifier_value,
                {
                    "node": "IDENTIFIER",
                    "name": node.name,
                    "value_type": node.value_type.value,
                    "result": _json_value(identifier_value),
                },
            )

        if isinstance(node, NotNode):
            operand = self._evaluate_node(node.operand, context)
            not_value: EvaluatedValue = (
                MISSING if operand.value is MISSING else not bool(operand.value)
            )
            return _NodeResult(
                not_value,
                {
                    "node": "NOT",
                    "result": _result_value(not_value),
                    "operand": operand.explanation,
                },
            )

        if isinstance(node, ComparisonNode):
            left = self._evaluate_node(node.left, context)
            right = self._evaluate_node(node.right, context)
            if left.value is MISSING or right.value is MISSING:
                comparison_value: EvaluatedValue = MISSING
            else:
                comparison_value = _compare(
                    node.operator,
                    cast(RuleScalar, left.value),
                    cast(RuleScalar, right.value),
                )
            return _NodeResult(
                comparison_value,
                {
                    "node": "COMPARISON",
                    "operator": node.operator.value,
                    "result": _result_value(comparison_value),
                    "left": left.explanation,
                    "right": right.explanation,
                },
            )

        return self._evaluate_logical(node, context)

    def _evaluate_logical(
        self, node: LogicalNode, context: Mapping[str, object]
    ) -> _NodeResult:
        left = self._evaluate_node(node.left, context)
        if node.operator is LogicalOperator.AND and left.value is False:
            return _NodeResult(
                False,
                {
                    "node": "AND",
                    "result": False,
                    "left": left.explanation,
                    "right": {
                        "node": "SKIPPED",
                        "reason": "AND_SHORT_CIRCUIT",
                        "ast": ast_to_dict(node.right),
                    },
                },
            )
        if node.operator is LogicalOperator.OR and left.value is True:
            return _NodeResult(
                True,
                {
                    "node": "OR",
                    "result": True,
                    "left": left.explanation,
                    "right": {
                        "node": "SKIPPED",
                        "reason": "OR_SHORT_CIRCUIT",
                        "ast": ast_to_dict(node.right),
                    },
                },
            )

        right = self._evaluate_node(node.right, context)
        if node.operator is LogicalOperator.AND:
            if right.value is False:
                value: EvaluatedValue = False
            elif left.value is MISSING or right.value is MISSING:
                value = MISSING
            else:
                value = bool(left.value) and bool(right.value)
        elif right.value is True:
            value = True
        elif left.value is MISSING or right.value is MISSING:
            value = MISSING
        else:
            value = bool(left.value) or bool(right.value)

        return _NodeResult(
            value,
            {
                "node": node.operator.value,
                "result": _result_value(value),
                "left": left.explanation,
                "right": right.explanation,
            },
        )


def evaluate_ast(
    root: AstNode,
    context: Mapping[str, object],
    missing_metric_behavior: MissingMetricBehavior = MissingMetricBehavior.ERROR,
) -> EvaluationResult:
    return Evaluator(missing_metric_behavior).evaluate(root, context)
