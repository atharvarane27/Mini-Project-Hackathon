"""Branches, accounts, and source-system reference data."""

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, IdMixin


class Branch(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "branches"
    branch_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class Account(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("length(currency) = 3", name="currency_iso_length"),
        UniqueConstraint("branch_id", "account_number"),
    )
    branch_id: Mapped[str] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), index=True
    )
    account_number: Mapped[str] = mapped_column(String(100), nullable=False)
    account_name: Mapped[str] = mapped_column(String(200), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SourceSystem(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "source_systems"
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
