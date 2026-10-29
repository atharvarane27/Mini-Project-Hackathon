from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, utc_now

if TYPE_CHECKING:
    from app.db.models.auth import User
    from app.db.models.findings import Finding
    from app.db.models.workflow import WorkflowTaskTemplate


class AuditCase(Base):
    """3NF Audit Case entity managed in priority queue and review workflow.

    Invariants:
    - priority between 0 and 100 inclusive.
    - Index: (state, priority) for fast priority-queue scanning and recovery.
    """

    __tablename__ = "audit_cases"
    __table_args__ = (
        CheckConstraint(
            "priority >= 0 AND priority <= 100", name="chk_audit_cases_priority_bounds"
        ),
        Index("ix_audit_cases_state_priority", "state", "priority"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(32), default="QUEUED", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    assignee_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    assignee: Mapped[User | None] = relationship("User", foreign_keys=[assignee_id])
    finding_links: Mapped[list[CaseFinding]] = relationship(
        "CaseFinding",
        back_populates="case",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    tasks: Mapped[list[CaseTask]] = relationship(
        "CaseTask",
        back_populates="case",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class CaseFinding(Base):
    """3NF Junction table mapping AuditCase to Finding.

    Composite PK: (case_id, finding_id).
    Strictly RESTRICT on delete.
    """

    __tablename__ = "case_findings"

    case_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("audit_cases.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    finding_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("findings.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    # Relationships
    case: Mapped[AuditCase] = relationship("AuditCase", back_populates="finding_links")
    finding: Mapped[Finding] = relationship("Finding", back_populates="case_links")


class CaseTask(Base):
    """3NF Runtime task instance belonging to an AuditCase.

    Index: (case_id, state).
    """

    __tablename__ = "case_tasks"
    __table_args__ = (Index("ix_case_tasks_case_state", "case_id", "state"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("audit_cases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    task_template_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflow_task_templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    state: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Relationships
    case: Mapped[AuditCase] = relationship("AuditCase", back_populates="tasks")
    task_template: Mapped[WorkflowTaskTemplate] = relationship("WorkflowTaskTemplate")
