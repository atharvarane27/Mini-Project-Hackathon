from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, utc_now

if TYPE_CHECKING:
    from app.db.models.cases import CaseFinding
    from app.db.models.transactions import Transaction


class DetectorConfig(Base):
    """3NF Configuration record for core algorithmic detectors.

    Unique constraint: UNIQUE(detector_type, version).
    """

    __tablename__ = "detector_configs"
    __table_args__ = (
        UniqueConstraint("detector_type", "version", name="uq_detector_configs_type_version"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    detector_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    findings: Mapped[list[Finding]] = relationship(
        "Finding",
        back_populates="detector_config",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class Finding(Base):
    """3NF Finding entity emitted by detection algorithms.

    Contains typed evidence facts, SHA-256 fingerprint, and references to associated transactions.
    Index: findings(finding_type, created_at).
    """

    __tablename__ = "findings"
    __table_args__ = (Index("ix_findings_type_created", "finding_type", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    finding_type: Mapped[str] = mapped_column(String(32), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    detector_config_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("detector_configs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="FLAGGED_FOR_REVIEW", nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    detector_config: Mapped[DetectorConfig | None] = relationship(
        "DetectorConfig",
        back_populates="findings",
    )
    transaction_links: Mapped[list[FindingTransaction]] = relationship(
        "FindingTransaction",
        back_populates="finding",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    case_links: Mapped[list[CaseFinding]] = relationship(
        "CaseFinding",
        back_populates="finding",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class FindingTransaction(Base):
    """3NF Junction table mapping Finding to CanonicalTransaction.

    Composite PK: (finding_id, transaction_id).
    Strictly RESTRICT on delete.
    """

    __tablename__ = "finding_transactions"

    finding_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("findings.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    transaction_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    path_position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    finding: Mapped[Finding] = relationship("Finding", back_populates="transaction_links")
    transaction: Mapped[Transaction] = relationship("Transaction", back_populates="finding_links")
