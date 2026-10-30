"""Double-entry journals with traceable source postings."""

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, IdMixin


class Journal(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "journals"
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("canonical_transactions.id", ondelete="RESTRICT"),
        unique=True,
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class JournalLine(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "journal_lines"
    __table_args__ = (
        CheckConstraint("debit_minor >= 0", name="nonnegative_debit"),
        CheckConstraint("credit_minor >= 0", name="nonnegative_credit"),
        CheckConstraint(
            "(debit_minor > 0 AND credit_minor = 0) OR "
            "(credit_minor > 0 AND debit_minor = 0)",
            name="single_posting_side",
        ),
    )
    journal_id: Mapped[str] = mapped_column(
        ForeignKey("journals.id", ondelete="RESTRICT"), index=True
    )
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    source_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )
    debit_minor: Mapped[int] = mapped_column(default=0, nullable=False)
    credit_minor: Mapped[int] = mapped_column(default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
