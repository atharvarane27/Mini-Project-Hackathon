"""Strict row normalization into the P04 accepted-transfer boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from app.ingestion.canonicalizer import AcceptedSourceTransfer


class DiagnosticCode(StrEnum):
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_AMOUNT = "INVALID_AMOUNT"
    NEGATIVE_AMOUNT = "NEGATIVE_AMOUNT"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    INVALID_CURRENCY = "INVALID_CURRENCY"
    INVALID_REVISION = "INVALID_REVISION"
    INVALID_POSTING_DIRECTION = "INVALID_POSTING_DIRECTION"
    UNKNOWN_BRANCH = "UNKNOWN_BRANCH"
    UNKNOWN_ACCOUNT = "UNKNOWN_ACCOUNT"
    SOURCE_REVISION_CONFLICT = "SOURCE_REVISION_CONFLICT"


@dataclass(frozen=True, slots=True)
class RowDiagnostic:
    code: DiagnosticCode
    message: str


@dataclass(frozen=True, slots=True)
class NormalizedRow:
    transfer: AcceptedSourceTransfer | None
    diagnostic: RowDiagnostic | None


REQUIRED_COLUMNS = frozenset(
    {
        "external_id", "transaction_reference", "sender_account_id",
        "receiver_account_id", "amount", "currency", "occurred_at",
    }
)


def _minor_units(value: str) -> int:
    try:
        amount = Decimal(value.strip())
    except InvalidOperation as error:
        raise ValueError("amount is malformed") from error
    if not amount.is_finite():
        raise ValueError("amount is malformed")
    if amount < 0:
        raise ArithmeticError("amount is negative")
    if amount == 0:
        raise ValueError("amount must be positive")
    minor = amount * 100
    if minor != minor.to_integral_value():
        raise ValueError("amount has more than two decimal places")
    return int(minor)


def normalize_row(
    values: dict[str, str],
    *,
    source_record_id: str,
    source_system: str,
    known_accounts: frozenset[str] | None = None,
    known_branches: frozenset[str] | None = None,
) -> NormalizedRow:
    missing = [name for name in REQUIRED_COLUMNS if not values.get(name, "").strip()]
    if missing:
        return NormalizedRow(None, RowDiagnostic(
            DiagnosticCode.MISSING_REQUIRED_FIELD,
            f"missing values: {sorted(missing)}",
        ))
    try:
        amount_minor = _minor_units(values["amount"])
    except ArithmeticError as error:
        return NormalizedRow(None, RowDiagnostic(DiagnosticCode.NEGATIVE_AMOUNT, str(error)))
    except ValueError as error:
        return NormalizedRow(None, RowDiagnostic(DiagnosticCode.INVALID_AMOUNT, str(error)))
    try:
        occurred_at = datetime.fromisoformat(values["occurred_at"].strip().replace("Z", "+00:00"))
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError
        occurred_at = occurred_at.astimezone(UTC)
    except ValueError:
        return NormalizedRow(None, RowDiagnostic(
            DiagnosticCode.INVALID_TIMESTAMP, "timestamp must include a timezone",
        ))
    currency = values["currency"].strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        return NormalizedRow(None, RowDiagnostic(DiagnosticCode.INVALID_CURRENCY, "invalid ISO currency"))
    try:
        revision = int(values.get("revision", "1").strip() or "1")
        if revision <= 0:
            raise ValueError
    except ValueError:
        return NormalizedRow(None, RowDiagnostic(DiagnosticCode.INVALID_REVISION, "revision must be positive"))
    direction = values.get("direction", "DEBIT").strip().upper() or "DEBIT"
    if direction not in {"DEBIT", "CREDIT"}:
        return NormalizedRow(None, RowDiagnostic(DiagnosticCode.INVALID_POSTING_DIRECTION, "direction must be DEBIT or CREDIT"))
    sender = values["sender_account_id"].strip()
    receiver = values["receiver_account_id"].strip()
    if known_accounts is not None:
        unknown = next((item for item in (sender, receiver) if item not in known_accounts), None)
        if unknown is not None:
            return NormalizedRow(None, RowDiagnostic(DiagnosticCode.UNKNOWN_ACCOUNT, f"unknown account {unknown}"))
    branch = values.get("branch_code", "").strip()
    if branch and known_branches is not None and branch not in known_branches:
        return NormalizedRow(None, RowDiagnostic(DiagnosticCode.UNKNOWN_BRANCH, f"unknown branch {branch}"))
    transfer = AcceptedSourceTransfer(
        source_record_id=source_record_id,
        source_system=source_system.strip(),
        external_id=values["external_id"].strip(),
        revision=revision,
        transaction_reference=values["transaction_reference"].strip(),
        sender_account_id=sender,
        receiver_account_id=receiver,
        amount_minor=amount_minor,
        currency=currency,
        occurred_at=occurred_at,
        transaction_type=values.get("transaction_type", "TRANSFER").strip() or "TRANSFER",
        correction_of_reference=values.get("correction_of_reference", "").strip() or None,
    )
    return NormalizedRow(transfer, None)
