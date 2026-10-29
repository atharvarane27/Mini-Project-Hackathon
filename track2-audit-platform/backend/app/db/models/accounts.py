from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, utc_now

if TYPE_CHECKING:
    from app.db.models.journals import Journal, JournalLine
    from app.db.models.transactions import Transaction


class Branch(Base):
    """3NF Branch entity.

    Represents an internal or external bank branch or organizational unit.
    """

    __tablename__ = "branches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships (NO ACTION / RESTRICT prevents cascade deletion of financial evidence)
    accounts: Mapped[list[Account]] = relationship(
        "Account",
        back_populates="branch",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    journals: Mapped[list[Journal]] = relationship(
        "Journal",
        back_populates="branch",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class Account(Base):
    """3NF Account entity.

    Scoped strictly to its branch. Uniqueness enforced on (branch_id, masked_label).
    """

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("branch_id", "masked_label", name="uq_accounts_branch_masked_label"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    branch_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("branches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    masked_label: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    branch: Mapped[Branch] = relationship("Branch", back_populates="accounts")
    sent_transactions: Mapped[list[Transaction]] = relationship(
        "Transaction",
        foreign_keys="Transaction.sender_account_id",
        back_populates="sender_account",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    received_transactions: Mapped[list[Transaction]] = relationship(
        "Transaction",
        foreign_keys="Transaction.receiver_account_id",
        back_populates="receiver_account",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    journal_lines: Mapped[list[JournalLine]] = relationship(
        "JournalLine",
        back_populates="account",
        cascade="save-update, merge",
        passive_deletes=True,
    )
