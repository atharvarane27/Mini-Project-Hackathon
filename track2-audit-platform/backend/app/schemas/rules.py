"""Pydantic v2 schemas for the custom rule engine (lexer/parser/AST/evaluator).

Rules are versioned, immutable after activation, and evaluated against
FindingFacts. All models are frozen per P01 contract specification.

Finding fact names (frozen per PRD section 5 M06):
  Reconciliation_Variance_Minor, Allowed_Variance_Minor, Balance_Anomaly_Flag,
  Transaction_Velocity, Circular_Flow_Detected, Cycle_Length,
  Cycle_Duration_Minutes, Splitting_Window_Sum_Minor, Splitting_Window_Count,
  Duplicate_Candidate_Flag, Severity.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

# ---------------------------------------------------------------------------
# Rule lifecycle
# ---------------------------------------------------------------------------


class RuleStatus(StrEnum):
    """Lifecycle state of a versioned rule."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


# ---------------------------------------------------------------------------
# Lexer token types
# ---------------------------------------------------------------------------


class TokenKind(StrEnum):
    """Token types produced by the rule lexer."""

    # Literals
    INTEGER = "INTEGER"
    BOOLEAN = "BOOLEAN"
    STRING = "STRING"
    IDENTIFIER = "IDENTIFIER"

    # Comparison operators
    EQ = "EQ"  # ==
    NEQ = "NEQ"  # !=
    LT = "LT"  # <
    LTE = "LTE"  # <=
    GT = "GT"  # >
    GTE = "GTE"  # >=

    # Logical operators
    AND = "AND"
    OR = "OR"
    NOT = "NOT"

    # Grouping
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"

    # Structural
    EOF = "EOF"
    UNKNOWN = "UNKNOWN"


class Token(BaseModel):
    """Lexer token with source position for diagnostic reporting."""

    model_config = ConfigDict(frozen=True)

    kind: TokenKind
    value: str
    position: StrictInt = 0  # byte offset in source expression


# ---------------------------------------------------------------------------
# AST node types
# ---------------------------------------------------------------------------


class AstNodeKind(StrEnum):
    """AST node discriminator for the rule expression tree."""

    LITERAL = "LITERAL"
    IDENTIFIER = "IDENTIFIER"
    COMPARISON = "COMPARISON"
    LOGICAL_AND = "LOGICAL_AND"
    LOGICAL_OR = "LOGICAL_OR"
    LOGICAL_NOT = "LOGICAL_NOT"


class AstNode(BaseModel):
    """A node in the parsed rule expression AST.

    children is empty for leaf nodes (LITERAL, IDENTIFIER).
    operator carries the comparison/logical operator token for COMPARISON nodes.
    """

    model_config = ConfigDict(frozen=True)

    kind: AstNodeKind
    value: str | int | bool | None = None
    operator: str | None = None
    children: tuple[AstNode, ...] = Field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Validation diagnostics
# ---------------------------------------------------------------------------


class DiagnosticSeverity(StrEnum):
    """Severity level for rule validation diagnostics."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class RuleDiagnostic(BaseModel):
    """Typed diagnostic message from lexer, parser, or type checker."""

    model_config = ConfigDict(frozen=True)

    severity: DiagnosticSeverity
    code: str
    message: str
    position: StrictInt | None = None
    token: str | None = None


class RuleValidationResult(BaseModel):
    """Response from POST /rules/validate — tokens, AST, and diagnostics."""

    model_config = ConfigDict(frozen=True)

    expression: str
    tokens: tuple[Token, ...] = Field(default_factory=tuple)
    ast: AstNode | None = None
    diagnostics: tuple[RuleDiagnostic, ...] = Field(default_factory=tuple)
    is_valid: bool = False


# ---------------------------------------------------------------------------
# Rule entity
# ---------------------------------------------------------------------------


class RuleCreate(BaseModel):
    """Request body for POST /rules (creates DRAFT version)."""

    model_config = ConfigDict(frozen=True)

    name: str
    expression: str
    description: str | None = None


class Rule(BaseModel):
    """Persisted rule entity — immutable after activation.

    Maps to rules table: (id PK, name, version, expression, status,
    created_by FK, activated_at, UNIQUE(name,version)).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    version: StrictInt = 1
    expression: str
    status: RuleStatus = RuleStatus.DRAFT
    description: str | None = None
    created_by: str | None = None
    activated_at: Any | None = None  # UtcDatetime | None

    @model_validator(mode="after")
    def validate_version_positive(self) -> Rule:
        if self.version < 1:
            raise ValueError(f"Rule version must be >= 1, got {self.version}")
        return self


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------


class RuleEvaluationInput(BaseModel):
    """Input payload for evaluating a rule against a set of finding facts."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    facts: dict[str, Any]


class ExplanationNode(BaseModel):
    """Recursive explanation tree node for rule evaluation result."""

    model_config = ConfigDict(frozen=True)

    expression: str
    result: bool
    children: tuple[ExplanationNode, ...] = Field(default_factory=tuple)


class RuleEvaluationResult(BaseModel):
    """Result from evaluating a rule against FindingFacts.

    Maps to PRD section 10: evaluator returns {matched, expression_version,
    explanation_tree}.
    """

    model_config = ConfigDict(frozen=True)

    rule_id: str
    rule_name: str
    matched: bool
    expression_version: StrictInt
    explanation_tree: ExplanationNode | None = None
    error: str | None = None
