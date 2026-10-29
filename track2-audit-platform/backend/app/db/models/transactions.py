from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base

if TYPE_CHECKING:
    from app.db.models.accounts import Account
    from app.db.models.findings import FindingTransaction
    from app.db.models.ingestion import SourceRecordTransaction


class Transaction(Base):
    """3NF Canonical Transaction entity representing one single economic fund transfer.

    Invariants:
    - amount_minor > 0 (strictly positive integer minor units, e.g. paise).
    - Foreign keys to accounts are strictly RESTRICT on delete.
    - Explicit performance indexes on (occurred_at, sender_account_id)
      and (receiver_account_id, occurred_at).
    """

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="chk_transactions_amount_minor_positive"),
        Index("ix_transactions_occurred_sender", "occurred_at", "sender_account_id"),
        Index("ix_transactions_receiver_occurred", "receiver_account_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    external_canonical_ref: Mapped[str | None] = mapped_column(
        String(128),
        unique=True,
        nullable=True,
        index=True,
    )
    sender_account_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    receiver_account_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    txn_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="POSTED", nullable=False)

    # Relationships
    sender_account: Mapped[Account] = relationship(
        "Account",
        foreign_keys=[sender_account_id],
        back_populates="sent_transactions",
    )
    receiver_account: Mapped[Account] = relationship(
        "Account",
        foreign_keys=[receiver_account_id],
        back_populates="received_transactions",
    )
    source_record_links: Mapped[list[SourceRecordTransaction]] = relationship(
        "SourceRecordTransaction",
        back_populates="transaction",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    finding_links: Mapped[list[FindingTransaction]] = relationship(
        "FindingTransaction",
        back_populates="transaction",
        cascade="save-update, merge",
        passive_deletes=True,
    )
