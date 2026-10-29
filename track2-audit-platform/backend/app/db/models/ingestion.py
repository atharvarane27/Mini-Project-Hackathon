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
    from app.db.models.transactions import Transaction


class SourceSystem(Base):
    """3NF Source System registry entity.

    Identifies external data sources, core banking systems, clearing feeds, etc.
    """

    __tablename__ = "source_systems"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    ingestion_jobs: Mapped[list[IngestionJob]] = relationship(
        "IngestionJob",
        back_populates="source_system",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    source_records: Mapped[list[SourceRecord]] = relationship(
        "SourceRecord",
        back_populates="source_system",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class IngestionJob(Base):
    """3NF Ingestion Job tracking batch CSV or stream imports."""

    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_system_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("source_systems.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    counts_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Relationships
    source_system: Mapped[SourceSystem] = relationship(
        "SourceSystem", back_populates="ingestion_jobs"
    )
    source_records: Mapped[list[SourceRecord]] = relationship(
        "SourceRecord",
        back_populates="ingestion_job",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class SourceRecord(Base):
    """3NF Source Record preserving raw ingest row provenance, payload, and revisions.

    Idempotency rule: UNIQUE(source_system_id, external_ref, source_revision).
    Index: source_records(source_system_id, external_ref).
    """

    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint(
            "source_system_id",
            "external_ref",
            "source_revision",
            name="uq_source_records_system_ref_revision",
        ),
        Index("ix_source_records_system_external_ref", "source_system_id", "external_ref"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ingestion_job_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ingestion_jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_system_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("source_systems.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    external_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    source_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    record_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)

    # Relationships
    ingestion_job: Mapped[IngestionJob] = relationship(
        "IngestionJob", back_populates="source_records"
    )
    source_system: Mapped[SourceSystem] = relationship(
        "SourceSystem", back_populates="source_records"
    )
    transaction_links: Mapped[list[SourceRecordTransaction]] = relationship(
        "SourceRecordTransaction",
        back_populates="source_record",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class SourceRecordTransaction(Base):
    """3NF Junction table mapping SourceRecord to CanonicalTransaction.

    Composite PK: (source_record_id, transaction_id).
    Strictly RESTRICT on delete to protect financial audit evidence.
    """

    __tablename__ = "source_record_transactions"

    source_record_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("source_records.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    transaction_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    link_type: Mapped[str] = mapped_column(String(32), default="CANONICAL", nullable=False)

    # Relationships
    source_record: Mapped[SourceRecord] = relationship(
        "SourceRecord", back_populates="transaction_links"
    )
    transaction: Mapped[Transaction] = relationship(
        "Transaction", back_populates="source_record_links"
    )
