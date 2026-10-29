from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import (
    CurrencyCode,
    MoneyMinor,
    UtcDatetime,
    compute_source_record_fingerprint,
)


class RecordStatus(StrEnum):
    """Raw ingestion row status."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CONFLICT = "CONFLICT"
    PENDING_REVIEW = "PENDING_REVIEW"


class TransactionStatus(StrEnum):
    """Canonical economic transfer status."""

    POSTED = "POSTED"
    PENDING = "PENDING"
    REVERSED = "REVERSED"


class TransferKind(StrEnum):
    """Economic transaction classification."""

    EXTERNAL_TRANSFER = "EXTERNAL_TRANSFER"
    INTERNAL_TRANSFER = "INTERNAL_TRANSFER"
    REVERSAL = "REVERSAL"
    FEE = "FEE"


class EntryDirection(StrEnum):
    """Journal entry debit/credit direction."""

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class SourceRecord(BaseModel):
    """Raw inbound source ingestion row."""

    model_config = ConfigDict(frozen=True)

    id: str
    ingestion_job_id: str
    source_system: str
    external_ref: str
    source_revision: int = 1
    payload_json: dict[str, Any]
    payload_hash: str
    received_at: UtcDatetime
    record_status: RecordStatus = RecordStatus.ACCEPTED

    def fingerprint(self) -> str:
        """Deterministic fingerprint for idempotency & collision checks."""
        return compute_source_record_fingerprint(
            self.source_system, self.external_ref, self.source_revision
        )


class CanonicalTransaction(BaseModel):
    """Single canonical economic transfer entity."""

    model_config = ConfigDict(frozen=True)

    id: str
    external_canonical_ref: str | None = None
    sender_account_id: str
    receiver_account_id: str
    amount_minor: MoneyMinor
    currency: CurrencyCode
    occurred_at: UtcDatetime
    posted_at: UtcDatetime
    txn_type: str
    status: TransactionStatus = TransactionStatus.POSTED

    @model_validator(mode="after")
    def validate_positive_amount(self) -> "CanonicalTransaction":
        if self.amount_minor <= 0:
            raise ValueError(
                f"Canonical transaction amount_minor must be strictly positive, got {self.amount_minor}"
            )
        return self


class JournalLine(BaseModel):
    """Double-entry accounting journal line."""

    model_config = ConfigDict(frozen=True)

    id: str
    journal_id: str
    account_id: str
    debit_minor: MoneyMinor = 0
    credit_minor: MoneyMinor = 0
    currency: CurrencyCode

    @model_validator(mode="after")
    def validate_journal_line_integrity(self) -> "JournalLine":
        if self.debit_minor < 0 or self.credit_minor < 0:
            raise ValueError("Debit and credit amounts cannot be negative")
        is_debit = self.debit_minor > 0 and self.credit_minor == 0
        is_credit = self.credit_minor > 0 and self.debit_minor == 0
        if not (is_debit or is_credit):
            msg = (
                f"Journal line must have exactly one positive side "
                f"(debit={self.debit_minor}, credit={self.credit_minor})"
            )
            raise ValueError(msg)
        return self


class Journal(BaseModel):
    """Posting group containing balanced or candidate journal lines."""

    model_config = ConfigDict(frozen=True)

    id: str
    branch_id: str
    posted_at: UtcDatetime
    journal_ref: str
    status: str = "POSTED"
    lines: tuple[JournalLine, ...] = Field(default_factory=tuple)

    def total_debit(self) -> int:
        return sum(line.debit_minor for line in self.lines)

    def total_credit(self) -> int:
        return sum(line.credit_minor for line in self.lines)

    def is_balanced(self) -> bool:
        return len(self.lines) > 0 and self.total_debit() == self.total_credit()


class SourceRecordTransactionLink(BaseModel):
    """Many-to-many lineage link between source records and canonical transactions."""

    model_config = ConfigDict(frozen=True)

    source_record_id: str
    transaction_id: str
    link_type: str = "CANONICAL"
