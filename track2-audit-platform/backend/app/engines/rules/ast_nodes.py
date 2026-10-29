"""Immutable typed AST nodes for the custom audit rule language."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import TypeAlias

from .tokens import Token
from .types import RuleScalar, RuleValueType


@dataclass(frozen=True, slots=True)
class SourceSpan:
    start_offset: int
    end_offset: int
    line: int
    column: int

    def __post_init__(self) -> None:
        if self.start_offset < 0 or self.end_offset < self.start_offset:
            raise ValueError("source span offsets are invalid")
        if self.line < 1 or self.column < 1:
            raise ValueError("source span line and column are one-based")

    @classmethod
    def from_token(cls, token: Token) -> SourceSpan:
        return cls(token.start_offset, token.end_offset, token.line, token.column)

    @classmethod
    def covering(cls, left: SourceSpan, right: SourceSpan) -> SourceSpan:
        return cls(left.start_offset, right.end_offset, left.line, left.column)

    def as_dict(self) -> dict[str, int]:
        return {
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "line": self.line,
            "column": self.column,
        }


class ComparisonOperator(StrEnum):
    GREATER = ">"
    GREATER_EQUAL = ">="
    LESS = "<"
    LESS_EQUAL = "<="
    EQUAL = "=="
    NOT_EQUAL = "!="


class LogicalOperator(StrEnum):
    AND = "AND"
    OR = "OR"


@dataclass(frozen=True, slots=True)
class LiteralNode:
    value: RuleScalar
    value_type: RuleValueType
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class IdentifierNode:
    name: str
    value_type: RuleValueType
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class NotNode:
    operand: AstNode
    span: SourceSpan
    value_type: RuleValueType = RuleValueType.BOOLEAN


@dataclass(frozen=True, slots=True)
class ComparisonNode:
    operator: ComparisonOperator
    left: AstNode
    right: AstNode
    span: SourceSpan
    value_type: RuleValueType = RuleValueType.BOOLEAN


@dataclass(frozen=True, slots=True)
class LogicalNode:
    operator: LogicalOperator
    left: AstNode
    right: AstNode
    span: SourceSpan
    value_type: RuleValueType = RuleValueType.BOOLEAN


AstNode: TypeAlias = (
    LiteralNode | IdentifierNode | NotNode | ComparisonNode | LogicalNode
)


def with_span(node: AstNode, span: SourceSpan) -> AstNode:
    """Return the same immutable semantic node with a wider grouped span."""

    return replace(node, span=span)


def ast_depth(root: AstNode) -> int:
    """Calculate depth iteratively so hostile trees cannot recurse Python."""

    maximum = 0
    stack: list[tuple[AstNode, int]] = [(root, 1)]
    while stack:
        node, depth = stack.pop()
        maximum = max(maximum, depth)
        if isinstance(node, NotNode):
            stack.append((node.operand, depth + 1))
        elif isinstance(node, (ComparisonNode, LogicalNode)):
            stack.append((node.left, depth + 1))
            stack.append((node.right, depth + 1))
    return maximum


def _literal_json_value(value: RuleScalar) -> int | bool | str:
    if isinstance(value, Decimal):
        return str(value)
    return value


def ast_to_dict(node: AstNode) -> dict[str, object]:
    """Serialize the typed AST without losing decimal precision."""

    common: dict[str, object] = {
        "value_type": node.value_type.value,
        "span": node.span.as_dict(),
    }
    if isinstance(node, LiteralNode):
        return {
            "node": "LITERAL",
            "value": _literal_json_value(node.value),
            **common,
        }
    if isinstance(node, IdentifierNode):
        return {"node": "IDENTIFIER", "name": node.name, **common}
    if isinstance(node, NotNode):
        return {"node": "NOT", "operand": ast_to_dict(node.operand), **common}
    if isinstance(node, ComparisonNode):
        return {
            "node": "COMPARISON",
            "operator": node.operator.value,
            "left": ast_to_dict(node.left),
            "right": ast_to_dict(node.right),
            **common,
        }
    return {
        "node": node.operator.value,
        "left": ast_to_dict(node.left),
        "right": ast_to_dict(node.right),
        **common,
    }
