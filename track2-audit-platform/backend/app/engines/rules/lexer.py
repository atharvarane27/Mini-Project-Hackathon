"""Custom character-level lexer for administrator-entered audit rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from .tokens import Token, TokenKind


class LexerErrorCode(StrEnum):
    EXPRESSION_TOO_LONG = "EXPRESSION_TOO_LONG"
    UNKNOWN_CHARACTER = "UNKNOWN_CHARACTER"
    INVALID_NUMBER = "INVALID_NUMBER"
    INVALID_OPERATOR = "INVALID_OPERATOR"
    NESTING_LIMIT_EXCEEDED = "NESTING_LIMIT_EXCEEDED"
    UNBALANCED_PARENTHESIS = "UNBALANCED_PARENTHESIS"


@dataclass(frozen=True, slots=True)
class LexerDiagnostic:
    code: LexerErrorCode
    message: str
    offset: int
    line: int
    column: int
    length: int = 1

    def as_dict(self) -> dict[str, int | str]:
        return {
            "code": self.code.value,
            "message": self.message,
            "offset": self.offset,
            "line": self.line,
            "column": self.column,
            "length": self.length,
        }


class LexerError(ValueError):
    def __init__(self, diagnostic: LexerDiagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(
            f"{diagnostic.code.value} at {diagnostic.line}:{diagnostic.column}: "
            f"{diagnostic.message}"
        )


@dataclass(frozen=True, slots=True)
class LexerConfig:
    max_expression_length: int = 4_096
    max_nesting: int = 64

    def __post_init__(self) -> None:
        if self.max_expression_length <= 0:
            raise ValueError("max_expression_length must be positive")
        if self.max_nesting <= 0:
            raise ValueError("max_nesting must be positive")


KEYWORDS: dict[str, tuple[TokenKind, bool | None]] = {
    "AND": (TokenKind.AND, None),
    "OR": (TokenKind.OR, None),
    "NOT": (TokenKind.NOT, None),
    "TRUE": (TokenKind.BOOLEAN, True),
    "FALSE": (TokenKind.BOOLEAN, False),
}


def _is_ascii_letter(character: str) -> bool:
    return "A" <= character <= "Z" or "a" <= character <= "z"


def _is_identifier_start(character: str) -> bool:
    return _is_ascii_letter(character) or character == "_"


def _is_identifier_part(character: str) -> bool:
    return _is_identifier_start(character) or "0" <= character <= "9"


def _line_column_at(expression: str, offset: int) -> tuple[int, int]:
    line, column, index = 1, 1, 0
    while index < offset:
        if expression[index] == "\r":
            index += 1
            if index < offset and expression[index] == "\n":
                index += 1
            line += 1
            column = 1
        elif expression[index] == "\n":
            index += 1
            line += 1
            column = 1
        else:
            index += 1
            column += 1
    return line, column


class Lexer:
    """Single-pass lexer with deterministic offsets and bounded input."""

    def __init__(self, config: LexerConfig | None = None) -> None:
        self.config = config or LexerConfig()

    def tokenize(self, expression: str) -> tuple[Token, ...]:
        if len(expression) > self.config.max_expression_length:
            error_line, error_column = _line_column_at(
                expression, self.config.max_expression_length
            )
            raise LexerError(
                LexerDiagnostic(
                    code=LexerErrorCode.EXPRESSION_TOO_LONG,
                    message=(
                        f"expression length {len(expression)} exceeds "
                        f"{self.config.max_expression_length}"
                    ),
                    offset=self.config.max_expression_length,
                    line=error_line,
                    column=error_column,
                    length=max(0, len(expression) - self.config.max_expression_length),
                )
            )

        tokens: list[Token] = []
        index = 0
        line = 1
        column = 1
        nesting = 0

        def diagnostic(
            code: LexerErrorCode,
            message: str,
            *,
            offset: int = index,
            diagnostic_line: int = line,
            diagnostic_column: int = column,
            length: int = 1,
        ) -> LexerError:
            return LexerError(
                LexerDiagnostic(
                    code=code,
                    message=message,
                    offset=offset,
                    line=diagnostic_line,
                    column=diagnostic_column,
                    length=length,
                )
            )

        def add_token(
            kind: TokenKind,
            start: int,
            start_line: int,
            start_column: int,
            literal: int | Decimal | bool | None = None,
        ) -> None:
            tokens.append(
                Token(
                    kind=kind,
                    lexeme=expression[start:index],
                    literal=literal,
                    start_offset=start,
                    end_offset=index,
                    line=start_line,
                    column=start_column,
                )
            )

        while index < len(expression):
            character = expression[index]

            if character in " \t\v\f":
                index += 1
                column += 1
                continue
            if character == "\n":
                index += 1
                line += 1
                column = 1
                continue
            if character == "\r":
                index += 1
                if index < len(expression) and expression[index] == "\n":
                    index += 1
                line += 1
                column = 1
                continue

            start, start_line, start_column = index, line, column

            if _is_identifier_start(character):
                index += 1
                column += 1
                while index < len(expression) and _is_identifier_part(expression[index]):
                    index += 1
                    column += 1
                lexeme = expression[start:index]
                keyword = KEYWORDS.get(lexeme.upper())
                if keyword is None:
                    add_token(TokenKind.IDENTIFIER, start, start_line, start_column)
                else:
                    kind, keyword_literal = keyword
                    add_token(kind, start, start_line, start_column, keyword_literal)
                continue

            if "0" <= character <= "9":
                index += 1
                column += 1
                while index < len(expression) and "0" <= expression[index] <= "9":
                    index += 1
                    column += 1

                is_decimal = False
                if index < len(expression) and expression[index] == ".":
                    is_decimal = True
                    index += 1
                    column += 1
                    decimal_start = index
                    while index < len(expression) and "0" <= expression[index] <= "9":
                        index += 1
                        column += 1
                    if index == decimal_start:
                        while index < len(expression) and (
                            _is_identifier_part(expression[index])
                            or expression[index] == "."
                        ):
                            index += 1
                            column += 1
                        raise diagnostic(
                            LexerErrorCode.INVALID_NUMBER,
                            f"invalid numeric literal {expression[start:index]!r}",
                            offset=start,
                            diagnostic_line=start_line,
                            diagnostic_column=start_column,
                            length=index - start,
                        )

                if index < len(expression) and (
                    _is_identifier_part(expression[index]) or expression[index] == "."
                ):
                    while index < len(expression) and (
                        _is_identifier_part(expression[index]) or expression[index] == "."
                    ):
                        index += 1
                        column += 1
                    raise diagnostic(
                        LexerErrorCode.INVALID_NUMBER,
                        f"invalid numeric literal {expression[start:index]!r}",
                        offset=start,
                        diagnostic_line=start_line,
                        diagnostic_column=start_column,
                        length=index - start,
                    )

                lexeme = expression[start:index]
                numeric_literal: int | Decimal = (
                    Decimal(lexeme) if is_decimal else int(lexeme)
                )
                add_token(
                    TokenKind.NUMBER,
                    start,
                    start_line,
                    start_column,
                    numeric_literal,
                )
                continue

            if (
                character == "."
                and index + 1 < len(expression)
                and "0" <= expression[index + 1] <= "9"
            ):
                index += 1
                column += 1
                while index < len(expression) and (
                    _is_identifier_part(expression[index]) or expression[index] == "."
                ):
                    index += 1
                    column += 1
                raise diagnostic(
                    LexerErrorCode.INVALID_NUMBER,
                    f"invalid numeric literal {expression[start:index]!r}",
                    offset=start,
                    diagnostic_line=start_line,
                    diagnostic_column=start_column,
                    length=index - start,
                )

            if character == "(":
                index += 1
                column += 1
                nesting += 1
                if nesting > self.config.max_nesting:
                    raise diagnostic(
                        LexerErrorCode.NESTING_LIMIT_EXCEEDED,
                        f"parenthesis nesting exceeds {self.config.max_nesting}",
                        offset=start,
                        diagnostic_line=start_line,
                        diagnostic_column=start_column,
                    )
                add_token(TokenKind.LEFT_PAREN, start, start_line, start_column)
                continue

            if character == ")":
                index += 1
                column += 1
                if nesting == 0:
                    raise diagnostic(
                        LexerErrorCode.UNBALANCED_PARENTHESIS,
                        "closing parenthesis has no matching opening parenthesis",
                        offset=start,
                        diagnostic_line=start_line,
                        diagnostic_column=start_column,
                    )
                nesting -= 1
                add_token(TokenKind.RIGHT_PAREN, start, start_line, start_column)
                continue

            single_or_equal = {
                ">": (TokenKind.GREATER, TokenKind.GREATER_EQUAL),
                "<": (TokenKind.LESS, TokenKind.LESS_EQUAL),
            }
            if character in single_or_equal:
                index += 1
                column += 1
                single_kind, equal_kind = single_or_equal[character]
                if index < len(expression) and expression[index] == "=":
                    index += 1
                    column += 1
                    add_token(equal_kind, start, start_line, start_column)
                else:
                    add_token(single_kind, start, start_line, start_column)
                continue

            if character in "=!":
                index += 1
                column += 1
                if index < len(expression) and expression[index] == "=":
                    index += 1
                    column += 1
                    add_token(
                        TokenKind.EQUAL if character == "=" else TokenKind.NOT_EQUAL,
                        start,
                        start_line,
                        start_column,
                    )
                    continue
                raise diagnostic(
                    LexerErrorCode.INVALID_OPERATOR,
                    f"operator {character!r} must be followed by '='",
                    offset=start,
                    diagnostic_line=start_line,
                    diagnostic_column=start_column,
                )

            raise diagnostic(
                LexerErrorCode.UNKNOWN_CHARACTER,
                f"unsupported character {character!r}",
                offset=start,
                diagnostic_line=start_line,
                diagnostic_column=start_column,
            )

        if nesting:
            raise diagnostic(
                LexerErrorCode.UNBALANCED_PARENTHESIS,
                f"{nesting} opening parenthesis is not closed",
                offset=len(expression),
                length=0,
            )

        tokens.append(
            Token(
                kind=TokenKind.EOF,
                lexeme="",
                literal=None,
                start_offset=len(expression),
                end_offset=len(expression),
                line=line,
                column=column,
            )
        )
        return tuple(tokens)


def tokenize(expression: str, config: LexerConfig | None = None) -> tuple[Token, ...]:
    """Convenience entry point used by P13 and API adapters."""

    return Lexer(config).tokenize(expression)
