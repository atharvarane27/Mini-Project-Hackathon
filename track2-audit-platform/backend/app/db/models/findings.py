"""Detector, reconciliation, finding, evidence, and rule models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, IdMixin


class DetectorRun(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "detector_runs"
    __table_args__ = (UniqueConstraint("detector_type", "run_key"),)
    detector_type: Mapped[str] = mapped_column(String(60), nullable=False)
    run_key: Mapped[str] = mapped_column(String(64), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint: Mapped[str] = mapped_column(String(256), nullable=False)
    config_version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)


class Finding(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "findings"
    __table_args__ = (Index("ix_findings_type_status", "finding_type", "status"),)
    detector_run_id: Mapped[str] = mapped_column(
        ForeignKey("detector_runs.id", ondelete="RESTRICT"), index=True
    )
    finding_type: Mapped[str] = mapped_column(String(60), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(80), nullable=False)
    config_version: Mapped[int] = mapped_column(nullable=False)
    facts: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class FindingEvidence(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "finding_evidence"
    __table_args__ = (UniqueConstraint("finding_id", "transaction_id"),)
    finding_id: Mapped[str] = mapped_column(
        ForeignKey("findings.id", ondelete="RESTRICT"), index=True
    )
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("canonical_transactions.id", ondelete="RESTRICT"), index=True
    )
    sequence_number: Mapped[int] = mapped_column(nullable=False)
    evidence: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class ReconciliationRun(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "reconciliation_runs"
    run_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    policy_version: Mapped[int] = mapped_column(nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)


class ReconciliationResult(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "reconciliation_results"
    __table_args__ = (UniqueConstraint("run_id", "left_transaction_id", "right_transaction_id"),)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"), index=True
    )
    left_transaction_id: Mapped[str | None] = mapped_column(
        ForeignKey("canonical_transactions.id", ondelete="RESTRICT")
    )
    right_transaction_id: Mapped[str | None] = mapped_column(
        ForeignKey("canonical_transactions.id", ondelete="RESTRICT")
    )
    classification: Mapped[str] = mapped_column(String(40), nullable=False)
    variance_minor: Mapped[int] = mapped_column(nullable=False, default=0)
    evidence: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class AuditRule(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_rules"
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)


class AuditRuleVersion(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version"),)
    rule_id: Mapped[str] = mapped_column(
        ForeignKey("audit_rules.id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(nullable=False)
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
