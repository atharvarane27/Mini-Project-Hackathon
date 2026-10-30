"""Import jobs, files, row provenance, and quarantine diagnostics."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, IdMixin


class IngestionJob(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint("last_row_number >= 1", name="valid_checkpoint"),
        CheckConstraint(
            "processed_count >= 0 AND accepted_count >= 0 AND "
            "rejected_count >= 0 AND duplicate_count >= 0",
            name="nonnegative_counts",
        ),
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_system_id: Mapped[str] = mapped_column(
        ForeignKey("source_systems.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    last_row_number: Mapped[int] = mapped_column(default=1, nullable=False)
    processed_count: Mapped[int] = mapped_column(default=0, nullable=False)
    accepted_count: Mapped[int] = mapped_column(default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(default=0, nullable=False)
    failure_message: Mapped[str | None] = mapped_column(String(1000))


class SourceFile(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "source_files"
    __table_args__ = (UniqueConstraint("source_system_id", "file_hash"),)
    source_system_id: Mapped[str] = mapped_column(
        ForeignKey("source_systems.id", ondelete="RESTRICT"), index=True
    )
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class IngestionSourceRow(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "ingestion_source_rows"
    __table_args__ = (UniqueConstraint("job_id", "row_number"),)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="RESTRICT"), index=True
    )
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("source_files.id", ondelete="RESTRICT")
    )
    source_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )
    row_number: Mapped[int] = mapped_column(nullable=False)
    raw_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class IngestionRowError(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "ingestion_row_errors"
    __table_args__ = (UniqueConstraint("job_id", "row_number", "diagnostic_code"),)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="RESTRICT"), index=True
    )
    row_number: Mapped[int] = mapped_column(nullable=False)
    diagnostic_code: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
