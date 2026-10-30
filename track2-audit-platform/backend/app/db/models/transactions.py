"""Raw source revisions, canonical transactions, and provenance links."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, IdMixin


class SourceRecord(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint("source_system_id", "external_id", "revision"),
        CheckConstraint("revision > 0", name="positive_revision"),
    )
    source_system_id: Mapped[str] = mapped_column(
        ForeignKey("source_systems.id", ondelete="RESTRICT"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(160), nullable=False)
    revision: Mapped[int] = mapped_column(nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    received_at: Mapped[datetime] = mapped_column(nullable=False)


class CanonicalTransaction(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "canonical_transactions"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="positive_amount"),
        CheckConstraint("length(currency) = 3", name="currency_iso_length"),
        Index("ix_canonical_transactions_occurred_currency", "occurred_at", "currency"),
    )
    transaction_reference: Mapped[str] = mapped_column(String(160), index=True)
    sender_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    receiver_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    amount_minor: Mapped[int] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    reversal_of_transaction_id: Mapped[str | None] = mapped_column(
        ForeignKey("canonical_transactions.id", ondelete="RESTRICT"), nullable=True
    )


class SourceRecordLink(Base):
    __tablename__ = "source_record_links"
    source_record_id: Mapped[str] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT"), primary_key=True
    )
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("canonical_transactions.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
    )
