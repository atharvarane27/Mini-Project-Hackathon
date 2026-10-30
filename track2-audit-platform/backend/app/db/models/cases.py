"""Audit cases and finding associations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, IdMixin


class AuditCase(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_cases"
    __table_args__ = (
        CheckConstraint("priority >= 0 AND priority <= 100", name="priority_range"),
        CheckConstraint("row_version > 0", name="positive_row_version"),
        Index("ix_audit_cases_queue", "state", "priority", "created_at"),
    )
    case_code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    stable_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    priority: Mapped[int] = mapped_column(nullable=False)
    row_version: Mapped[int] = mapped_column(default=1, nullable=False)
    rule_version_id: Mapped[str] = mapped_column(
        ForeignKey("audit_rule_versions.id", ondelete="RESTRICT")
    )
    assignee_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    lease_until: Mapped[datetime | None] = mapped_column(index=True)


class CaseFinding(Base):
    __tablename__ = "case_findings"
    case_id: Mapped[str] = mapped_column(
        ForeignKey("audit_cases.id", ondelete="RESTRICT"), primary_key=True
    )
    finding_id: Mapped[str] = mapped_column(
        ForeignKey("findings.id", ondelete="RESTRICT"), primary_key=True
    )
