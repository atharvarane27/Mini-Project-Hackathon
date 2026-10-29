"""P12 tests for the custom character-level audit rule lexer."""

from __future__ import annotations

import inspect
import json
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path

import pytest

import app.engines.rules.lexer as lexer_module
from app.engines.rules.lexer import (
    Lexer,
    LexerConfig,
    LexerError,
    LexerErrorCode,
    tokenize,
)
from app.engines.rules.tokens import TokenKind
from app.engines.rules.types import (
    DEFAULT_FIELD_TYPES,
    FieldDefinition,
    RuleValueType,
    literal_type,
)


FIXTURE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "rule_lexer_cases.json"


def fixture_cases() -> dict[str, list[dict[str, object]]]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as fixture_file:
        return json.load(fixture_file)  # type: ignore[no-any-return]


@pytest.mark.parametrize("case", fixture_cases()["valid"])
def test_valid_lexer_fixtures(case: dict[str, object]) -> None:
    tokens = tokenize(str(case["expression"]))

    assert [token.kind.value for token in tokens] == case["kinds"]


@pytest.mark.parametrize("case", fixture_cases()["invalid"])
def test_invalid_lexer_fixtures_have_stable_codes(case: dict[str, object]) -> None:
    with pytest.raises(LexerError) as captured:
        tokenize(str(case["expression"]))

    assert captured.value.diagnostic.code.value == case["code"]


def test_tokens_include_exact_values_offsets_and_locations() -> None:
    expression = "Amount >= 10.50\r\nAND Enabled == FALSE"

    tokens = tokenize(expression)

    assert tokens[0].kind is TokenKind.IDENTIFIER
    assert (tokens[0].lexeme, tokens[0].start_offset, tokens[0].end_offset) == (
        "Amount",
        0,
        6,
    )
    assert (tokens[0].line, tokens[0].column) == (1, 1)
    assert tokens[2].literal == Decimal("10.50")
    assert (tokens[3].lexeme, tokens[3].line, tokens[3].column) == ("AND", 2, 1)
    assert tokens[6].literal is False
    assert tokens[-1].kind is TokenKind.EOF
    assert tokens[-1].start_offset == len(expression)


def test_integer_and_decimal_literals_never_use_float() -> None:
    tokens = tokenize("Large == 999999999999999999999 AND Ratio == 0.10")
    numbers = [token.literal for token in tokens if token.kind is TokenKind.NUMBER]

    assert numbers == [999999999999999999999, Decimal("0.10")]
    assert not any(isinstance(number, float) for number in numbers)


def test_keywords_and_booleans_are_case_insensitive_but_identifiers_are_preserved() -> None:
    tokens = tokenize("not Flag and true OR falseValue")

    assert [token.kind for token in tokens] == [
        TokenKind.NOT,
        TokenKind.IDENTIFIER,
        TokenKind.AND,
        TokenKind.BOOLEAN,
        TokenKind.OR,
        TokenKind.IDENTIFIER,
        TokenKind.EOF,
    ]
    assert tokens[1].lexeme == "Flag"
    assert tokens[3].literal is True
    assert tokens[5].lexeme == "falseValue"


def test_all_comparison_operators_are_tokenized_without_whitespace() -> None:
    tokens = tokenize("A>1 AND B>=2 AND C<3 AND D<=4 AND E==5 AND F!=6")

    comparisons = [
        token.kind
        for token in tokens
        if token.kind
        in {
            TokenKind.GREATER,
            TokenKind.GREATER_EQUAL,
            TokenKind.LESS,
            TokenKind.LESS_EQUAL,
            TokenKind.EQUAL,
            TokenKind.NOT_EQUAL,
        }
    ]
    assert comparisons == [
        TokenKind.GREATER,
        TokenKind.GREATER_EQUAL,
        TokenKind.LESS,
        TokenKind.LESS_EQUAL,
        TokenKind.EQUAL,
        TokenKind.NOT_EQUAL,
    ]


def test_expression_length_limit_reports_multiline_location() -> None:
    lexer = Lexer(LexerConfig(max_expression_length=4, max_nesting=8))

    with pytest.raises(LexerError) as captured:
        lexer.tokenize("A\nB\nC")

    diagnostic = captured.value.diagnostic
    assert diagnostic.code is LexerErrorCode.EXPRESSION_TOO_LONG
    assert (diagnostic.offset, diagnostic.line, diagnostic.column) == (4, 3, 1)
    assert diagnostic.length == 1


def test_nesting_limit_and_unbalanced_parentheses_have_locations() -> None:
    lexer = Lexer(LexerConfig(max_expression_length=100, max_nesting=2))

    with pytest.raises(LexerError) as captured:
        lexer.tokenize("(((A)))")
    assert captured.value.diagnostic.code is LexerErrorCode.NESTING_LIMIT_EXCEEDED
    assert (captured.value.diagnostic.offset, captured.value.diagnostic.column) == (2, 3)

    with pytest.raises(LexerError) as captured:
        tokenize("A)")
    assert captured.value.diagnostic.code is LexerErrorCode.UNBALANCED_PARENTHESIS
    assert captured.value.diagnostic.offset == 1


def test_empty_or_whitespace_expression_only_emits_eof() -> None:
    assert [token.kind for token in tokenize("")] == [TokenKind.EOF]
    eof = tokenize(" \t\n")
    assert [token.kind for token in eof] == [TokenKind.EOF]
    assert (eof[0].line, eof[0].column) == (2, 1)


def test_injection_syntax_is_rejected_and_lexer_contains_no_dynamic_execution() -> None:
    with pytest.raises(LexerError) as captured:
        tokenize("__import__('os').system('echo unsafe')")

    assert captured.value.diagnostic.code is LexerErrorCode.UNKNOWN_CHARACTER
    source = inspect.getsource(lexer_module)
    assert "eval(" not in source
    assert "exec(" not in source


def test_diagnostics_are_serializable_and_tokens_are_immutable() -> None:
    with pytest.raises(LexerError) as captured:
        tokenize("A @ B")
    assert captured.value.diagnostic.as_dict() == {
        "code": "UNKNOWN_CHARACTER",
        "message": "unsupported character '@'",
        "offset": 2,
        "line": 1,
        "column": 3,
        "length": 1,
    }

    token = tokenize("A")[0]
    with pytest.raises(FrozenInstanceError):
        token.lexeme = "B"  # type: ignore[misc]


def test_rule_value_types_cover_required_track_two_fields() -> None:
    assert DEFAULT_FIELD_TYPES["Balance_Anomaly_Flag"] is RuleValueType.BOOLEAN
    assert DEFAULT_FIELD_TYPES["Splitting_Window_Sum_Minor"] is RuleValueType.NUMBER
    assert DEFAULT_FIELD_TYPES["Transaction_Velocity"] is RuleValueType.NUMBER
    assert literal_type(True) is RuleValueType.BOOLEAN
    assert literal_type(Decimal("1.0")) is RuleValueType.NUMBER
    assert FieldDefinition("Custom_Field_2", RuleValueType.NUMBER).name == "Custom_Field_2"


@pytest.mark.parametrize("name", ["", "2Bad", "bad-name", "Nämé"])
def test_field_definition_rejects_invalid_identifier(name: str) -> None:
    with pytest.raises(ValueError, match="identifier"):
        FieldDefinition(name, RuleValueType.NUMBER)


@pytest.mark.parametrize(
    "changes",
    [
        {"max_expression_length": 0},
        {"max_nesting": 0},
    ],
)
def test_lexer_config_requires_positive_limits(changes: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        LexerConfig(**changes)
