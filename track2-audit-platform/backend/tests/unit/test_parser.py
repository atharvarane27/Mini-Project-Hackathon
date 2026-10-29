"""P13 parser, typed AST, diagnostics, and validation API tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.rules import create_rules_router
from app.engines.rules.ast_nodes import (
    ComparisonNode,
    ComparisonOperator,
    IdentifierNode,
    LiteralNode,
    LogicalNode,
    LogicalOperator,
    NotNode,
    ast_to_dict,
)
from app.engines.rules.lexer import tokenize
from app.engines.rules.parser import (
    Parser,
    ParserConfig,
    ParserError,
    ParserErrorCode,
    parse_tokens,
)
from app.engines.rules.tokens import TokenKind
from app.engines.rules.types import RuleValueType


FIELDS = {
    "A": RuleValueType.BOOLEAN,
    "B": RuleValueType.BOOLEAN,
    "C": RuleValueType.BOOLEAN,
    "Flag": RuleValueType.BOOLEAN,
    "Amount": RuleValueType.NUMBER,
    "Count": RuleValueType.NUMBER,
}


def parse(expression: str, config: ParserConfig | None = None):
    return parse_tokens(tokenize(expression), FIELDS, config)


def test_and_has_higher_precedence_than_or() -> None:
    ast = parse("A OR B AND C")

    assert isinstance(ast, LogicalNode)
    assert ast.operator is LogicalOperator.OR
    assert isinstance(ast.left, IdentifierNode)
    assert isinstance(ast.right, LogicalNode)
    assert ast.right.operator is LogicalOperator.AND


def test_parentheses_override_precedence_and_expand_span() -> None:
    ast = parse("(A OR B) AND C")

    assert isinstance(ast, LogicalNode)
    assert ast.operator is LogicalOperator.AND
    assert isinstance(ast.left, LogicalNode)
    assert ast.left.operator is LogicalOperator.OR
    assert (ast.left.span.start_offset, ast.left.span.end_offset) == (0, 8)


def test_not_binds_more_tightly_than_comparison() -> None:
    ast = parse("NOT Flag == TRUE")

    assert isinstance(ast, ComparisonNode)
    assert ast.operator is ComparisonOperator.EQUAL
    assert isinstance(ast.left, NotNode)
    assert isinstance(ast.right, LiteralNode)


def test_parenthesized_comparison_can_be_negated() -> None:
    ast = parse("NOT (Amount > 10)")

    assert isinstance(ast, NotNode)
    assert isinstance(ast.operand, ComparisonNode)
    assert ast.operand.operator is ComparisonOperator.GREATER


def test_prd_rule_builds_one_typed_boolean_ast() -> None:
    expression = (
        "(Reconciliation_Variance_Minor > 50000 AND Balance_Anomaly_Flag == TRUE) "
        "OR (Circular_Flow_Detected == TRUE AND Cycle_Length >= 3) "
        "OR (Splitting_Window_Sum_Minor >= 10000000 AND Splitting_Window_Count >= 3)"
    )

    ast = parse_tokens(tokenize(expression))

    assert ast.value_type is RuleValueType.BOOLEAN
    serialized = ast_to_dict(ast)
    assert serialized["node"] == "OR"
    assert serialized["value_type"] == "BOOLEAN"


def test_unknown_identifier_has_precise_diagnostic() -> None:
    with pytest.raises(ParserError) as captured:
        parse("Missing_Field == TRUE")

    diagnostic = captured.value.diagnostic
    assert diagnostic.code is ParserErrorCode.UNKNOWN_IDENTIFIER
    assert (diagnostic.offset, diagnostic.line, diagnostic.column) == (0, 1, 1)
    assert diagnostic.length == len("Missing_Field")


@pytest.mark.parametrize(
    ("expression", "code"),
    [
        ("Amount AND Flag", ParserErrorCode.TYPE_MISMATCH),
        ("Amount == TRUE", ParserErrorCode.TYPE_MISMATCH),
        ("Flag > FALSE", ParserErrorCode.INVALID_COMPARISON),
        ("NOT Amount", ParserErrorCode.TYPE_MISMATCH),
        ("Amount", ParserErrorCode.TYPE_MISMATCH),
    ],
)
def test_static_type_errors_are_rejected(
    expression: str, code: ParserErrorCode
) -> None:
    with pytest.raises(ParserError) as captured:
        parse(expression)

    assert captured.value.diagnostic.code is code


def test_boolean_equality_and_bare_boolean_field_are_valid() -> None:
    comparison = parse("Flag != FALSE")
    bare = parse("Flag")

    assert isinstance(comparison, ComparisonNode)
    assert isinstance(bare, IdentifierNode)
    assert bare.value_type is RuleValueType.BOOLEAN


@pytest.mark.parametrize(
    ("expression", "code"),
    [
        ("", ParserErrorCode.EMPTY_EXPRESSION),
        ("Amount >", ParserErrorCode.UNEXPECTED_END),
        ("Amount >>> 10", ParserErrorCode.UNEXPECTED_TOKEN),
        ("Amount > 10 > 1", ParserErrorCode.TRAILING_TOKEN),
        ("Flag TRUE", ParserErrorCode.TRAILING_TOKEN),
    ],
)
def test_malformed_syntax_has_stable_parser_codes(
    expression: str, code: ParserErrorCode
) -> None:
    with pytest.raises(ParserError) as captured:
        parse(expression)

    assert captured.value.diagnostic.code is code


def test_parser_enforces_token_and_ast_depth_limits() -> None:
    with pytest.raises(ParserError) as captured:
        parse("A AND B", ParserConfig(max_tokens=3, max_ast_depth=10))
    assert captured.value.diagnostic.code is ParserErrorCode.TOKEN_LIMIT_EXCEEDED

    with pytest.raises(ParserError) as captured:
        parse("NOT NOT NOT NOT Flag", ParserConfig(max_tokens=100, max_ast_depth=3))
    assert captured.value.diagnostic.code is ParserErrorCode.AST_DEPTH_EXCEEDED

    with pytest.raises(ParserError) as captured:
        parse(
            "A AND B AND C",
            ParserConfig(max_tokens=100, max_ast_depth=2),
        )
    assert captured.value.diagnostic.code is ParserErrorCode.AST_DEPTH_EXCEEDED


def test_parser_requires_eof_terminated_tokens() -> None:
    tokens = tokenize("Flag")

    with pytest.raises(ValueError, match="end with EOF"):
        Parser(tokens[:-1], FIELDS)


def test_decimal_ast_serialization_preserves_text_precision() -> None:
    ast = parse("Amount >= 10.50")

    assert isinstance(ast, ComparisonNode)
    assert isinstance(ast.right, LiteralNode)
    assert ast.right.value == Decimal("10.50")
    assert ast_to_dict(ast)["right"]["value"] == "10.50"  # type: ignore[index]


def test_ast_nodes_are_immutable() -> None:
    ast = parse("Flag")

    with pytest.raises(FrozenInstanceError):
        ast.name = "Changed"  # type: ignore[union-attr,misc]


def test_empty_field_registry_rejects_every_identifier() -> None:
    with pytest.raises(ParserError) as captured:
        parse_tokens(tokenize("Flag"), {})

    assert captured.value.diagnostic.code is ParserErrorCode.UNKNOWN_IDENTIFIER


@pytest.mark.parametrize("value", [0, -1])
def test_parser_config_requires_positive_limits(value: int) -> None:
    with pytest.raises(ValueError):
        ParserConfig(max_tokens=value)
    with pytest.raises(ValueError):
        ParserConfig(max_ast_depth=value)


def test_validation_api_returns_tokens_typed_ast_and_request_id() -> None:
    app = FastAPI()
    app.include_router(create_rules_router(FIELDS), prefix="/api/v1")
    client = TestClient(app)

    response = client.post(
        "/api/v1/rules/validate",
        json={"expression": "Flag AND Amount >= 10.50"},
        headers={"X-Request-ID": "rule-request-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == "rule-request-1"
    assert payload["data"]["valid"] is True
    assert payload["data"]["result_type"] == "BOOLEAN"
    assert payload["data"]["ast"]["node"] == "AND"
    number_tokens = [
        token for token in payload["data"]["tokens"] if token["kind"] == "NUMBER"
    ]
    assert number_tokens[0]["literal"] == "10.50"
    assert payload["data"]["tokens"][-1]["kind"] == TokenKind.EOF.value


def test_validation_api_returns_typed_parser_and_lexer_diagnostics() -> None:
    app = FastAPI()
    app.include_router(create_rules_router(FIELDS), prefix="/api/v1")
    client = TestClient(app)

    parser_error = client.post(
        "/api/v1/rules/validate",
        json={"expression": "Unknown == TRUE"},
    )
    assert parser_error.status_code == 422
    assert parser_error.json()["error"]["code"] == "UNKNOWN_IDENTIFIER"
    assert parser_error.json()["error"]["details"]["phase"] == "PARSER"
    assert parser_error.json()["error"]["details"]["offset"] == 0

    lexer_error = client.post(
        "/api/v1/rules/validate",
        json={"expression": "Flag @ TRUE"},
    )
    assert lexer_error.status_code == 422
    assert lexer_error.json()["error"]["code"] == "UNKNOWN_CHARACTER"
    assert lexer_error.json()["error"]["details"]["phase"] == "LEXER"


def test_validation_api_rejects_empty_expression() -> None:
    app = FastAPI()
    app.include_router(create_rules_router(FIELDS), prefix="/api/v1")

    response = TestClient(app).post(
        "/api/v1/rules/validate", json={"expression": ""}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EMPTY_EXPRESSION"
