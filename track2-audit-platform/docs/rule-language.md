# Audit rule language

P12 defines lexical structure only. P13 owns parsing, precedence enforcement,
AST construction, field lookup, type compatibility, and syntax diagnostics.
P14 owns evaluation and rule version persistence. No phase may use Python
`eval` or `exec`.

## Grammar

```text
expr        := or_expr
or_expr     := and_expr ("OR" and_expr)*
and_expr    := not_expr ("AND" not_expr)*
not_expr    := "NOT" not_expr | comparison
comparison  := primary ((">" | ">=" | "<" | "<=" | "==" | "!=") primary)?
primary     := IDENTIFIER | NUMBER | BOOLEAN | "(" expr ")"
```

Intended precedence from highest to lowest is parentheses, `NOT`, comparison,
`AND`, and `OR`. The P12 lexer emits tokens without applying precedence.

## Lexical rules

- Identifiers use ASCII letters or `_` initially, followed by ASCII letters,
  digits, or `_`. Case is preserved for later field-registry validation.
- `AND`, `OR`, `NOT`, `TRUE`, and `FALSE` are case-insensitive reserved words.
- Integers contain one or more digits and are stored as arbitrary-size integers.
- Decimal literals require digits on both sides of one decimal point and use
  `Decimal`; floating-point values are never created.
- Scientific notation, signed literals, strings, arithmetic, member access,
  function calls, comments, and collection literals are outside the MVP.
- Valid comparisons are `>`, `>=`, `<`, `<=`, `==`, and `!=`. Single `=` and
  `!` are lexical errors.
- Spaces, tabs, CRLF, CR, and LF separate tokens. Newlines update diagnostic
  locations but do not otherwise affect the token stream.
- Every stream ends with one `EOF` token, including an empty expression. P13
  rejects an empty expression as invalid syntax.

Each token contains its source lexeme, typed literal where applicable,
zero-based start/end offsets (`end` exclusive), and one-based line/column of the
first character. Boolean literals carry `bool`; numbers carry `int` or
`Decimal`; other tokens have no literal value.

## Limits and diagnostics

Default limits are 4,096 characters and 64 nested parentheses. They are
configurable through `LexerConfig` but must remain positive. The lexer reports
one of these stable codes with offset, line, column, and source length:

| Code | Meaning |
| --- | --- |
| `EXPRESSION_TOO_LONG` | Input exceeds the configured character limit. |
| `UNKNOWN_CHARACTER` | Character is not part of the language. |
| `INVALID_NUMBER` | Decimal/exponent/adjacent identifier format is unsupported. |
| `INVALID_OPERATOR` | A single `=` or `!` was supplied. |
| `NESTING_LIMIT_EXCEEDED` | Parenthesis depth exceeds the configured limit. |
| `UNBALANCED_PARENTHESIS` | Opening or closing parenthesis has no match. |

Examples of invalid numeric text are `.5`, `10.`, `1e3`, `12abc`, and
`1.2.3`. Rejection happens before parsing and never attempts dynamic execution.

## Field types

The MVP has `NUMBER` and `BOOLEAN` values. The default registry declares the
required Track 2 names, including `Reconciliation_Variance_Minor`,
`Balance_Anomaly_Flag`, `Transaction_Velocity`, `Circular_Flow_Detected`,
`Cycle_Length`, `Splitting_Window_Sum_Minor`, and
`Splitting_Window_Count`. P13 will reject unknown fields and incompatible
comparisons; the lexer deliberately treats every non-keyword identifier alike.

## Example

```text
(Reconciliation_Variance_Minor > 50000 AND Balance_Anomaly_Flag == TRUE)
OR (Circular_Flow_Detected == TRUE AND Cycle_Length >= 3)
OR (Splitting_Window_Sum_Minor >= 10000000 AND Splitting_Window_Count >= 3)
```

The deterministic valid and invalid lexer corpus is stored in
`fixtures/rule_lexer_cases.json`.

## P13 parsing and static validation

The recursive-descent parser applies precedence in this order: grouped
expressions, `NOT`, comparisons, `AND`, then `OR`. Consequently,
`A OR B AND C` becomes `A OR (B AND C)`, while parentheses can override the
default. A complete rule must have Boolean type.

Identifiers are resolved case-sensitively against the field registry. Logical
operators and `NOT` require Boolean operands. Comparisons require matching
types; numeric values support all comparison operators, while Boolean values
support only `==` and `!=`. Chained comparisons are outside the grammar.

AST nodes are immutable and typed: literal, identifier, `NOT`, comparison, and
logical `AND`/`OR`. Each node carries a source span. The API serializes decimal
literals as strings so their exact value survives JSON transport.

Parser diagnostics use these stable codes:

| Code | Meaning |
| --- | --- |
| `EMPTY_EXPRESSION` | No rule expression was supplied. |
| `UNEXPECTED_TOKEN` | Token cannot begin the required expression. |
| `UNEXPECTED_END` | Input ended while an operand was required. |
| `EXPECTED_TOKEN` | A required closing/syntactic token is missing. |
| `TRAILING_TOKEN` | Valid expression is followed by extra tokens. |
| `UNKNOWN_IDENTIFIER` | Field is absent from the registry. |
| `TYPE_MISMATCH` | Operand or complete-rule types are incompatible. |
| `INVALID_COMPARISON` | Operator is unavailable for the operand type. |
| `TOKEN_LIMIT_EXCEEDED` | Token stream exceeds the configured bound. |
| `AST_DEPTH_EXCEEDED` | Typed syntax tree exceeds the configured bound. |

The default parser bounds are 2,048 tokens and AST depth 64. P14 will evaluate
these nodes; P13 performs no rule execution or persistence.

## P14 evaluation and lifecycle

The evaluator walks the typed AST directly and never evaluates source text.
Runtime values must match the parser registry: Boolean fields require `bool`,
and numeric fields require `int` or `Decimal`; floats are rejected. Logical
operators short-circuit and produce a deterministic explanation tree including
explicitly skipped branches.

Missing fields use an explicit policy. `ERROR` raises `MissingMetricError` when
a required branch is evaluated. `NO_MATCH` propagates a three-valued `MISSING`
result through `NOT`, comparisons, `AND`, and `OR`; a final missing result does
not match. A branch skipped by normal Boolean short-circuiting does not require
its fields.

Rule versions are created as immutable drafts and recompiled before atomic
activation. Activating a newer version retires the prior active version of the
same rule name. Each evaluation records the exact rule-version ID, relevant
facts snapshot, matched facts, explanation tree, priority-policy version, UTC
time, and deterministic priority. Historical evaluation records retain their
original version when a new expression is activated.

The default priority example follows the PRD: 40 points for severe
reconciliation mismatch, 35 for circular flow, 25 for splitting, plus up to 20
aging points, capped at 100. All weights and caps are versioned configuration,
not a trained score.
