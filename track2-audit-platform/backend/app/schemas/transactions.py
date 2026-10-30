"""Shared source, canonical transaction, and journal contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import Field, model_validator

from .common import (
    CurrencyCode,
    FrozenContract,
    MinorUnits,
    PositiveMinorUnits,
    StableId,
    UtcDateTime,
)


class SourceRecord(FrozenContract):
    source_record_id: StableId
    source_system: StableId
    external_id: StableId
    revision: int = Field(strict=True, ge=1)
    received_at: UtcDateTime
    raw_payload: Mapping[str, Any]


class CanonicalTransaction(FrozenContract):
    transaction_id: StableId
    source_record_ids: tuple[StableId, ...]
    sender_account_id: StableId
    receiver_account_id: StableId
    amount_minor: PositiveMinorUnits
    currency: CurrencyCode
    occurred_at: UtcDateTime
    transaction_type: StableId
    status: StableId

    @model_validator(mode="after")
    def validate_sources(self) -> CanonicalTransaction:
        if not self.source_record_ids:
            raise ValueError("source_record_ids must not be empty")
        if len(set(self.source_record_ids)) != len(self.source_record_ids):
            raise ValueError("source_record_ids must be unique")
        return self


class JournalLine(FrozenContract):
    journal_line_id: StableId
    journal_id: StableId
    account_id: StableId
    debit_minor: MinorUnits
    credit_minor: MinorUnits
    currency: CurrencyCode
    occurred_at: UtcDateTime

    @model_validator(mode="after")
    def validate_side(self) -> JournalLine:
        if (self.debit_minor == 0) == (self.credit_minor == 0):
            raise ValueError("exactly one of debit_minor or credit_minor must be positive")
        return self
