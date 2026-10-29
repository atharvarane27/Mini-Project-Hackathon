"""Recursive-descent parser and static type validation for audit rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Mapping, NoReturn, Sequence

from .ast_nodes import (
    AstNode,
    ComparisonNode,
    ComparisonOperator,
    IdentifierNode,
    LiteralNode,
    LogicalNode,
    LogicalOperator,
    NotNode,
    SourceSpan,
    ast_depth,
    with_span,
)
from .tokens import Token, TokenKind
from .types import DEFAULT_FIELD_TYPES, RuleValueType, literal_type


class ParserErrorCode(StrEnum):
    EMPTY_EXPRESSION = "EMPTY_EXPRESSION"
    UNEXPECTED_TOKEN = "UNEXPECTED_TOKEN"
    UNEXPECTED_END = "UNEXPECTED_END"
    EXPECTED_TOKEN = "EXPECTED_TOKEN"
    TRAILING_TOKEN = "TRAILING_TOKEN"
    UNKNOWN_IDENTIFIER = "UNKNOWN_IDENTIFIER"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    INVALID_COMPARISON = "INVALID_COMPARISON"
    TOKEN_LIMIT_EXCEEDED = "TOKEN_LIMIT_EXCEEDED"
    AST_DEPTH_EXCEEDED = "AST_DEPTH_EXCEEDED"


@dataclass(frozen=True, slots=True)
class ParserDiagnostic:
    code: ParserErrorCode
    message: str
    offset: int
    line: int
    column: int
    length: int

    def as_dict(self) -> dict[str, int | str]:
        return {
            "code": self.code.value,
            "message": self.message,
            "offset": self.offset,
            "line": self.line,
            "column": self.column,
            "length": self.length,
        }


class ParserError(ValueError):
    def __init__(self, diagnostic: ParserDiagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(
            f"{diagnostic.code.value} at {diagnostic.line}:{diagnostic.column}: "
            f"{diagnostic.message}"
        )


@dataclass(frozen=True, slots=True)
class ParserConfig:
    max_tokens: int = 2_048
    max_ast_depth: int = 64

    def __post_init__(self) -> None:
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.max_ast_depth <= 0:
            raise ValueError("max_ast_depth must be positive")


COMPARISONS: dict[TokenKind, ComparisonOperator] = {
    TokenKind.GREATER: ComparisonOperator.GREATER,
    TokenKind.GREATER_EQUAL: ComparisonOperator.GREATER_EQUAL,
    TokenKind.LESS: ComparisonOperator.LESS,
    TokenKind.LESS_EQUAL: ComparisonOperator.LESS_EQUAL,
    TokenKind.EQUAL: ComparisonOperator.EQUAL,
    TokenKind.NOT_EQUAL: ComparisonOperator.NOT_EQUAL,
}


class Parser:
    def __init__(
        self,
        tokens: Sequence[Token],
        field_types: Mapping[str, RuleValueType] | None = None,
        config: ParserConfig | None = None,
    ) -> None:
        if not tokens or tokens[-1].kind is not TokenKind.EOF:
            raise ValueError("token stream must end with EOF")
        self.tokens = tuple(tokens)
        self.field_types = dict(
            DEFAULT_FIELD_TYPES if field_types is None else field_types
        )
        self.config = config or ParserConfig()
        self.current = 0

    def parse(self) -> AstNode:
        if len(self.tokens) > self.config.max_tokens:
            self._raise(
                ParserErrorCode.TOKEN_LIMIT_EXCEEDED,
                f"token count {len(self.tokens)} exceeds {self.config.max_tokens}",
                self.tokens[self.config.max_tokens],
            )
        if self._peek().kind is TokenKind.EOF:
            self._raise(
                ParserErrorCode.EMPTY_EXPRESSION,
                "rule expression must not be empty",
                self._peek(),
            )

        expression = self._parse_or()
        if self._peek().kind is not TokenKind.EOF:
            self._raise(
                ParserErrorCode.TRAILING_TOKEN,
                f"unexpected trailing token {self._peek().lexeme!r}",
                self._peek(),
            )
        self._require_boolean(expression, self._peek(), "complete rule")
        depth = ast_depth(expression)
        if depth > self.config.max_ast_depth:
            self._raise(
                ParserErrorCode.AST_DEPTH_EXCEEDED,
                f"AST depth {depth} exceeds {self.config.max_ast_depth}",
                self.tokens[0],
            )
        return expression

    def _parse_or(self) -> AstNode:
        node = self._parse_and()
        while self._match(TokenKind.OR):
            operator = self._previous()
            right = self._parse_and()
            self._require_boolean(node, operator, "left operand of OR")
            self._require_boolean(right, operator, "right operand of OR")
            node = LogicalNode(
                LogicalOperator.OR,
                node,
                right,
                SourceSpan.covering(node.span, right.span),
            )
        return node

    def _parse_and(self) -> AstNode:
        node = self._parse_comparison()
        while self._match(TokenKind.AND):
            operator = self._previous()
            right = self._parse_comparison()
            self._require_boolean(node, operator, "left operand of AND")
            self._require_boolean(right, operator, "right operand of AND")
            node = LogicalNode(
                LogicalOperator.AND,
                node,
                right,
                SourceSpan.covering(node.span, right.span),
            )
        return node

    def _parse_comparison(self) -> AstNode:
        left = self._parse_not(1)
        operator = COMPARISONS.get(self._peek().kind)
        if operator is None:
            return left

        operator_token = self._advance()
        right = self._parse_not(1)
        if left.value_type is not right.value_type:
            self._raise(
                ParserErrorCode.TYPE_MISMATCH,
                f"cannot compare {left.value_type.value} with {right.value_type.value}",
                operator_token,
            )
        if (
            left.value_type is RuleValueType.BOOLEAN
            and operator not in {ComparisonOperator.EQUAL, ComparisonOperator.NOT_EQUAL}
        ):
            self._raise(
                ParserErrorCode.INVALID_COMPARISON,
                f"operator {operator.value} is not valid for BOOLEAN values",
                operator_token,
            )
        return ComparisonNode(
            operator,
            left,
            right,
            SourceSpan.covering(left.span, right.span),
        )

    def _parse_not(self, depth: int) -> AstNode:
        if depth > self.config.max_ast_depth:
            self._raise(
                ParserErrorCode.AST_DEPTH_EXCEEDED,
                f"AST depth exceeds {self.config.max_ast_depth}",
                self._peek(),
            )
        if self._match(TokenKind.NOT):
            operator = self._previous()
            operand = self._parse_not(depth + 1)
            self._require_boolean(operand, operator, "operand of NOT")
            return NotNode(
                operand,
                SourceSpan.covering(SourceSpan.from_token(operator), operand.span),
            )
        return self._parse_primary(depth)

    def _parse_primary(self, depth: int) -> AstNode:
        token = self._peek()
        if self._match(TokenKind.BOOLEAN):
            if not isinstance(token.literal, bool):
                raise TypeError("BOOLEAN token must contain bool")
            return LiteralNode(
                token.literal,
                RuleValueType.BOOLEAN,
                SourceSpan.from_token(token),
            )
        if self._match(TokenKind.NUMBER):
            if isinstance(token.literal, bool) or not isinstance(
                token.literal, (int, Decimal)
            ):
                raise TypeError("NUMBER token must contain int or Decimal")
            return LiteralNode(
                token.literal,
                literal_type(token.literal),
                SourceSpan.from_token(token),
            )
        if self._match(TokenKind.IDENTIFIER):
            value_type = self.field_types.get(token.lexeme)
            if value_type is None:
                self._raise(
                    ParserErrorCode.UNKNOWN_IDENTIFIER,
                    f"unknown rule field {token.lexeme!r}",
                    token,
                )
            return IdentifierNode(token.lexeme, value_type, SourceSpan.from_token(token))
        if self._match(TokenKind.LEFT_PAREN):
            opening = token
            expression = self._parse_or()
            closing = self._consume(
                TokenKind.RIGHT_PAREN,
                "expected ')' after grouped expression",
            )
            return with_span(
                expression,
                SourceSpan(
                    opening.start_offset,
                    closing.end_offset,
                    opening.line,
                    opening.column,
                ),
            )
        if token.kind is TokenKind.EOF:
            self._raise(
                ParserErrorCode.UNEXPECTED_END,
                "expected identifier, literal, NOT, or '('",
                token,
            )
        self._raise(
            ParserErrorCode.UNEXPECTED_TOKEN,
            f"unexpected token {token.lexeme!r}",
            token,
        )

    def _require_boolean(self, node: AstNode, token: Token, context: str) -> None:
        if node.value_type is not RuleValueType.BOOLEAN:
            self._raise(
                ParserErrorCode.TYPE_MISMATCH,
                f"{context} must be BOOLEAN, got {node.value_type.value}",
                token,
            )

    def _consume(self, kind: TokenKind, message: str) -> Token:
        if self._peek().kind is kind:
            return self._advance()
        self._raise(ParserErrorCode.EXPECTED_TOKEN, message, self._peek())

    def _match(self, kind: TokenKind) -> bool:
        if self._peek().kind is not kind:
            return False
        self._advance()
        return True

    def _advance(self) -> Token:
        token = self.tokens[self.current]
        if token.kind is not TokenKind.EOF:
            self.current += 1
        return token

    def _peek(self) -> Token:
        return self.tokens[self.current]

    def _previous(self) -> Token:
        return self.tokens[self.current - 1]

    def _raise(
        self, code: ParserErrorCode, message: str, token: Token
    ) -> NoReturn:
        raise ParserError(
            ParserDiagnostic(
                code=code,
                message=message,
                offset=token.start_offset,
                line=token.line,
                column=token.column,
                length=len(token.lexeme),
            )
        )


def parse_tokens(
    tokens: Sequence[Token],
    field_types: Mapping[str, RuleValueType] | None = None,
    config: ParserConfig | None = None,
) -> AstNode:
    return Parser(tokens, field_types, config).parse()
