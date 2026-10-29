from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, utc_now

if TYPE_CHECKING:
    from app.db.models.accounts import Account, Branch


class Journal(Base):
    """3NF Accounting Journal header entity."""

    __tablename__ = "journals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    branch_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("branches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    journal_ref: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="POSTED", nullable=False)

    # Relationships
    branch: Mapped[Branch] = relationship("Branch", back_populates="journals")
    lines: Mapped[list[JournalLine]] = relationship(
        "JournalLine",
        back_populates="journal",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class JournalLine(Base):
    """3NF Journal Line entity.

    Enforces double-entry line validity:
    - debit_minor >= 0 and credit_minor >= 0
    - Exactly one side must be positive: (debit > 0 and credit == 0) OR (debit == 0 and credit > 0).
    """

    __tablename__ = "journal_lines"
    __table_args__ = (
        CheckConstraint(
            "debit_minor >= 0 AND credit_minor >= 0 AND "
            "((debit_minor > 0 AND credit_minor = 0) OR (debit_minor = 0 AND credit_minor > 0))",
            name="chk_journal_lines_exactly_one_side_positive",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    journal_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("journals.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    debit_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    credit_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # Relationships
    journal: Mapped[Journal] = relationship("Journal", back_populates="lines")
    account: Mapped[Account] = relationship("Account", back_populates="journal_lines")
