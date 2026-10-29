"""Typed tokens emitted by the custom character-level lexer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .types import RuleScalar


class TokenKind(StrEnum):
    IDENTIFIER = "IDENTIFIER"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    LEFT_PAREN = "LEFT_PAREN"
    RIGHT_PAREN = "RIGHT_PAREN"
    GREATER = "GREATER"
    GREATER_EQUAL = "GREATER_EQUAL"
    LESS = "LESS"
    LESS_EQUAL = "LESS_EQUAL"
    EQUAL = "EQUAL"
    NOT_EQUAL = "NOT_EQUAL"
    EOF = "EOF"


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    lexeme: str
    literal: RuleScalar | None
    start_offset: int
    end_offset: int
    line: int
    column: int

    def __post_init__(self) -> None:
        if self.start_offset < 0 or self.end_offset < self.start_offset:
            raise ValueError("token offsets are invalid")
        if self.line < 1 or self.column < 1:
            raise ValueError("token line and column are one-based")
        if self.end_offset - self.start_offset != len(self.lexeme):
            raise ValueError("token offsets must span the lexeme")
