from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, utc_now

if TYPE_CHECKING:
    from app.db.models.ingestion import SourceRecord, SourceSystem


class ReconciliationRun(Base):
    """3NF Reconciliation Run tracking cross-ledger matching jobs."""

    __tablename__ = "reconciliation_runs"
    __table_args__ = (
        CheckConstraint("cutoff_at > start_at", name="chk_reconciliation_runs_cutoff_after_start"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_left_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("source_systems.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_right_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("source_systems.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    policy_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_checkpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    source_left: Mapped[SourceSystem] = relationship("SourceSystem", foreign_keys=[source_left_id])
    source_right: Mapped[SourceSystem] = relationship(
        "SourceSystem", foreign_keys=[source_right_id]
    )
    results: Mapped[list[ReconciliationResult]] = relationship(
        "ReconciliationResult",
        back_populates="run",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class ReconciliationResult(Base):
    """3NF Individual reconciliation match result record.

    Unique constraint: UNIQUE(run_id, left_record_id, right_record_id).
    """

    __tablename__ = "reconciliation_results"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "left_record_id",
            "right_record_id",
            name="uq_reconciliation_results_run_records",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    left_record_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("source_records.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    right_record_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("source_records.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    variance_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)

    # Relationships
    run: Mapped[ReconciliationRun] = relationship("ReconciliationRun", back_populates="results")
    left_record: Mapped[SourceRecord | None] = relationship(
        "SourceRecord", foreign_keys=[left_record_id]
    )
    right_record: Mapped[SourceRecord | None] = relationship(
        "SourceRecord", foreign_keys=[right_record_id]
    )
